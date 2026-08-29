from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
import re
import threading
import time
from typing import Any
from urllib.parse import quote, urlsplit

import httpx

from app.core.config import Settings, get_settings
from app.models.email_channel import EmailChannel
from app.services.credential_crypto import decrypt_credential


GRAPH_BASE_URL = "https://graph.microsoft.com/v1.0"
GRAPH_SCOPE = "https://graph.microsoft.com/.default"
_DIRECTORY_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9.-]{1,126}[A-Za-z0-9]$")
_token_cache: dict[str, tuple[str, float]] = {}
_token_lock = threading.Lock()


class GraphEmailError(RuntimeError):
    def __init__(
        self,
        message: str,
        *,
        status_code: int | None = None,
        retryable: bool = False,
        retry_after_seconds: int | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.retryable = retryable
        self.retry_after_seconds = retry_after_seconds


@dataclass(frozen=True)
class GraphSendResult:
    request_id: str
    accepted_at: datetime


def _parse_retry_after(response: httpx.Response) -> int | None:
    value = response.headers.get("Retry-After")
    if not value:
        return None
    try:
        return max(1, min(int(value), 3600))
    except ValueError:
        return None


def _graph_error(response: httpx.Response, operation: str) -> GraphEmailError:
    request_id = response.headers.get("request-id") or response.headers.get(
        "client-request-id"
    )
    detail = ""
    try:
        payload = response.json()
        error = payload.get("error") if isinstance(payload, dict) else None
        if isinstance(error, dict):
            detail = str(error.get("message") or error.get("code") or "")
    except ValueError:
        detail = ""
    suffix = f": {detail[:500]}" if detail else ""
    if request_id:
        suffix += f" (request_id={request_id})"
    retryable = response.status_code in {408, 409, 425, 429} or response.status_code >= 500
    return GraphEmailError(
        f"Microsoft Graph {operation} failed with HTTP {response.status_code}{suffix}",
        status_code=response.status_code,
        retryable=retryable,
        retry_after_seconds=_parse_retry_after(response),
    )


class MicrosoftGraphEmailClient:
    def __init__(
        self,
        channel: EmailChannel,
        *,
        settings: Settings | None = None,
        client: httpx.Client | None = None,
    ) -> None:
        self.channel = channel
        self.settings = settings or get_settings()
        self._client = client

    @property
    def mailbox_key(self) -> str:
        return self.channel.mailbox_user_id or self.channel.mailbox_address

    def _validate_configuration(self) -> None:
        if not self.channel.entra_tenant_id or not _DIRECTORY_ID.fullmatch(
            self.channel.entra_tenant_id
        ):
            raise GraphEmailError("A valid Microsoft Entra tenant ID is required")
        if not self.channel.client_id:
            raise GraphEmailError("Microsoft Graph client ID is required")
        if not self.channel.client_secret_encrypted:
            raise GraphEmailError("Microsoft Graph client secret is not configured")

    def _client_secret(self) -> str:
        return decrypt_credential(
            self.channel.client_secret_encrypted or "",
            purpose=f"email-channel:{self.channel.id}:client-secret",
            tenant_id=self.channel.tenant_id,
            settings=self.settings,
        )

    def _http(self) -> tuple[httpx.Client, bool]:
        if self._client is not None:
            return self._client, False
        return (
            httpx.Client(
                timeout=httpx.Timeout(self.settings.email_graph_timeout_seconds),
                follow_redirects=False,
            ),
            True,
        )

    def access_token(self, *, force_refresh: bool = False) -> str:
        self._validate_configuration()
        cache_key = self.channel.id
        with _token_lock:
            cached = _token_cache.get(cache_key)
            if not force_refresh and cached and cached[1] > time.monotonic() + 60:
                return cached[0]

        directory_id = quote(self.channel.entra_tenant_id or "", safe="")
        token_url = (
            f"https://login.microsoftonline.com/{directory_id}/oauth2/v2.0/token"
        )
        client, owned = self._http()
        try:
            response = client.post(
                token_url,
                data={
                    "client_id": self.channel.client_id,
                    "client_secret": self._client_secret(),
                    "scope": GRAPH_SCOPE,
                    "grant_type": "client_credentials",
                },
                headers={"Accept": "application/json"},
            )
        except httpx.HTTPError as exc:
            raise GraphEmailError(
                f"Microsoft identity token request failed: {exc.__class__.__name__}",
                retryable=True,
            ) from exc
        finally:
            if owned:
                client.close()
        if response.status_code != 200:
            raise _graph_error(response, "token request")
        try:
            payload = response.json()
            token = str(payload["access_token"])
            expires_in = max(120, int(payload.get("expires_in", 3600)))
        except (KeyError, TypeError, ValueError) as exc:
            raise GraphEmailError("Microsoft identity returned an invalid token response") from exc
        with _token_lock:
            _token_cache[cache_key] = (token, time.monotonic() + expires_in)
        return token

    def request(
        self,
        method: str,
        url: str,
        *,
        json_payload: dict[str, Any] | None = None,
        operation: str,
    ) -> httpx.Response:
        parsed = urlsplit(url)
        if (
            parsed.scheme != "https"
            or parsed.hostname not in {"graph.microsoft.com"}
            or parsed.username
            or parsed.password
        ):
            raise GraphEmailError("Rejected unsafe Microsoft Graph URL")
        client, owned = self._http()
        try:
            try:
                response = client.request(
                    method,
                    url,
                    json=json_payload,
                    headers={
                        "Authorization": f"Bearer {self.access_token()}",
                        "Accept": "application/json",
                        "Content-Type": "application/json",
                    },
                )
            except httpx.HTTPError as exc:
                raise GraphEmailError(
                    f"Microsoft Graph {operation} request failed: {exc.__class__.__name__}",
                    retryable=True,
                ) from exc
            if response.status_code == 401:
                with _token_lock:
                    _token_cache.pop(self.channel.id, None)
                try:
                    response = client.request(
                        method,
                        url,
                        json=json_payload,
                        headers={
                            "Authorization": f"Bearer {self.access_token(force_refresh=True)}",
                            "Accept": "application/json",
                            "Content-Type": "application/json",
                        },
                    )
                except httpx.HTTPError as exc:
                    raise GraphEmailError(
                        f"Microsoft Graph {operation} retry failed: {exc.__class__.__name__}",
                        retryable=True,
                    ) from exc
            if response.status_code >= 400:
                raise _graph_error(response, operation)
            return response
        finally:
            if owned:
                client.close()

    def test_connection(self) -> dict[str, Any]:
        mailbox = quote(self.mailbox_key, safe="")
        response = self.request(
            "GET",
            f"{GRAPH_BASE_URL}/users/{mailbox}/mailFolders/inbox"
            "?$select=id,displayName,totalItemCount,unreadItemCount",
            operation="mailbox validation",
        )
        payload = response.json()
        return {
            "id": payload.get("id"),
            "display_name": payload.get("displayName"),
            "total_item_count": payload.get("totalItemCount"),
            "unread_item_count": payload.get("unreadItemCount"),
            "request_id": response.headers.get("request-id"),
        }

    def send_mail(
        self,
        *,
        to_email: str,
        to_name: str | None,
        subject: str,
        body: str,
        reply_to: str | None,
        headers: dict[str, str],
    ) -> GraphSendResult:
        mailbox = quote(self.mailbox_key, safe="")
        internet_headers = [
            {"name": name, "value": value}
            for name, value in headers.items()
            if name.lower().startswith("x-")
        ]
        message: dict[str, Any] = {
            "subject": subject,
            "body": {"contentType": "Text", "content": body},
            "toRecipients": [
                {
                    "emailAddress": {
                        "address": to_email,
                        **({"name": to_name} if to_name else {}),
                    }
                }
            ],
            "internetMessageHeaders": internet_headers,
        }
        if reply_to:
            message["replyTo"] = [{"emailAddress": {"address": reply_to}}]
        response = self.request(
            "POST",
            f"{GRAPH_BASE_URL}/users/{mailbox}/sendMail",
            json_payload={"message": message, "saveToSentItems": True},
            operation="sendMail",
        )
        if response.status_code != 202:
            raise GraphEmailError(
                f"Microsoft Graph sendMail returned unexpected HTTP {response.status_code}",
                status_code=response.status_code,
                retryable=response.status_code >= 500,
            )
        request_id = (
            response.headers.get("request-id")
            or response.headers.get("client-request-id")
            or f"accepted-{int(time.time() * 1000)}"
        )
        return GraphSendResult(request_id=request_id, accepted_at=datetime.now(UTC))

    def message_delta(
        self,
        *,
        delta_link: str | None,
        page_size: int = 50,
        max_pages: int = 20,
    ) -> tuple[list[dict[str, Any]], str | None]:
        mailbox = quote(self.mailbox_key, safe="")
        url = delta_link or (
            f"{GRAPH_BASE_URL}/users/{mailbox}/mailFolders/inbox/messages/delta"
            "?$select=id,conversationId,internetMessageId,subject,from,toRecipients,"
            "ccRecipients,receivedDateTime,body,bodyPreview,hasAttachments,"
            "internetMessageHeaders,isRead"
            f"&$top={max(1, min(page_size, 100))}"
        )
        messages: list[dict[str, Any]] = []
        final_delta: str | None = None
        for _ in range(max_pages):
            response = self.request("GET", url, operation="messages delta")
            payload = response.json()
            rows = payload.get("value", [])
            if isinstance(rows, list):
                messages.extend(row for row in rows if isinstance(row, dict))
            next_link = payload.get("@odata.nextLink")
            final_delta = payload.get("@odata.deltaLink") or final_delta
            if not next_link:
                break
            url = str(next_link)
        return messages, str(final_delta) if final_delta else None

    def get_message(self, message_id: str) -> dict[str, Any]:
        mailbox = quote(self.mailbox_key, safe="")
        resource = quote(message_id, safe="")
        response = self.request(
            "GET",
            f"{GRAPH_BASE_URL}/users/{mailbox}/messages/{resource}"
            "?$select=id,conversationId,internetMessageId,subject,from,toRecipients,"
            "ccRecipients,receivedDateTime,body,bodyPreview,hasAttachments,"
            "internetMessageHeaders,isRead",
            operation="message fetch",
        )
        payload = response.json()
        if not isinstance(payload, dict):
            raise GraphEmailError("Microsoft Graph returned an invalid message")
        return payload

    def list_attachments(self, message_id: str) -> list[dict[str, Any]]:
        mailbox = quote(self.mailbox_key, safe="")
        resource = quote(message_id, safe="")
        response = self.request(
            "GET",
            f"{GRAPH_BASE_URL}/users/{mailbox}/messages/{resource}/attachments",
            operation="attachment list",
        )
        payload = response.json()
        rows = payload.get("value", []) if isinstance(payload, dict) else []
        return [row for row in rows if isinstance(row, dict)]

    def create_subscription(self, *, notification_url: str, client_state: str) -> dict[str, Any]:
        mailbox = quote(self.mailbox_key, safe="")
        expiry = datetime.now(UTC) + timedelta(hours=48)
        response = self.request(
            "POST",
            f"{GRAPH_BASE_URL}/subscriptions",
            json_payload={
                "changeType": "created,updated",
                "notificationUrl": notification_url,
                "resource": f"/users/{mailbox}/mailFolders('inbox')/messages",
                "expirationDateTime": expiry.isoformat().replace("+00:00", "Z"),
                "clientState": client_state,
                "latestSupportedTlsVersion": "v1_2",
            },
            operation="subscription create",
        )
        payload = response.json()
        if not isinstance(payload, dict):
            raise GraphEmailError("Microsoft Graph returned an invalid subscription")
        return payload

    def renew_subscription(self, subscription_id: str) -> dict[str, Any]:
        resource = quote(subscription_id, safe="")
        expiry = datetime.now(UTC) + timedelta(hours=48)
        response = self.request(
            "PATCH",
            f"{GRAPH_BASE_URL}/subscriptions/{resource}",
            json_payload={
                "expirationDateTime": expiry.isoformat().replace("+00:00", "Z")
            },
            operation="subscription renewal",
        )
        payload = response.json()
        if not isinstance(payload, dict):
            raise GraphEmailError("Microsoft Graph returned an invalid subscription")
        return payload

    def delete_subscription(self, subscription_id: str) -> None:
        resource = quote(subscription_id, safe="")
        self.request(
            "DELETE",
            f"{GRAPH_BASE_URL}/subscriptions/{resource}",
            operation="subscription delete",
        )
