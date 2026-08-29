from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
import hashlib
import json
import re
import uuid
from typing import Any
from urllib.parse import urljoin, urlsplit

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.models.asset import Asset
from app.models.asset_discovery import (
    AssetDiscoveryConnector,
    AssetDiscoveryRun,
    AssetDiscoveryStaleCandidate,
)
from app.models.asset_history import AssetHistory
from app.models.cmdb_reconciliation import CMDBSource, CMDBSourceIdentity
from app.models.user import User
from app.services.cmdb_reconciliation import (
    ReconciliationConflict,
    apply_reconciliation,
    preview_reconciliation,
)
from app.services.cmdb_schema import canonical_json
from app.services.credential_crypto import decrypt_credential, encrypt_credential


_DIRECTORY_PATTERN = re.compile(r"^[A-Za-z0-9.-]{3,255}$")
_PROVIDER_AUTH = {
    "INTUNE": {"OAUTH_CLIENT_CREDENTIALS"},
    "AZURE_RESOURCE_GRAPH": {"OAUTH_CLIENT_CREDENTIALS"},
    "SCCM_ADMIN_SERVICE": {"BASIC", "BEARER"},
    "LANSWEEPER_DATA_API": {"API_TOKEN", "BEARER"},
}
_INTUNE_SELECT = (
    "id,deviceName,serialNumber,manufacturer,model,operatingSystem,"
    "osVersion,complianceState,managementAgent,managedDeviceOwnerType,"
    "lastSyncDateTime,azureADDeviceId,userDisplayName,userPrincipalName,"
    "wiFiMacAddress,ethernetMacAddress,imei"
)
_MAX_PROVIDER_PAGES = 5_000


class AssetDiscoveryError(RuntimeError):
    def __init__(
        self,
        message: str,
        *,
        retryable: bool,
        status_code: int | None = None,
        retry_after_seconds: int | None = None,
    ) -> None:
        super().__init__(message)
        self.retryable = retryable
        self.status_code = status_code
        self.retry_after_seconds = retry_after_seconds


@dataclass(frozen=True)
class DiscoveryFetchResult:
    records: list[dict[str, Any]]
    pages: int
    complete_snapshot: bool
    cursor: str | None = None
    request_id: str | None = None


def utcnow() -> datetime:
    return datetime.now(UTC)


def _json_object(value: str | None) -> dict[str, Any]:
    if not value:
        return {}
    try:
        parsed = json.loads(value)
    except (TypeError, ValueError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _credential_purpose(connector_id: str) -> str:
    return f"asset-discovery:{connector_id}:credential"


def encrypt_discovery_credential(
    connector: AssetDiscoveryConnector,
    credential: dict[str, str],
    *,
    settings: Settings | None = None,
) -> str:
    return encrypt_credential(
        canonical_json(credential),
        purpose=_credential_purpose(connector.id),
        tenant_id=connector.tenant_id,
        settings=settings,
    )


def decrypt_discovery_credential(
    connector: AssetDiscoveryConnector,
    *,
    settings: Settings | None = None,
) -> dict[str, str]:
    if not connector.credential_encrypted:
        raise AssetDiscoveryError(
            "Discovery credential is not configured",
            retryable=False,
        )
    raw = decrypt_credential(
        connector.credential_encrypted,
        purpose=_credential_purpose(connector.id),
        tenant_id=connector.tenant_id,
        settings=settings,
    )
    parsed = _json_object(raw)
    return {str(key): str(value) for key, value in parsed.items() if value is not None}


def validate_discovery_credential(
    provider: str,
    auth_type: str,
    credential: dict[str, str],
) -> dict[str, str]:
    provider = provider.strip().upper()
    auth_type = auth_type.strip().upper()
    if provider not in _PROVIDER_AUTH:
        raise ValueError("Unsupported asset discovery provider")
    if auth_type not in _PROVIDER_AUTH[provider]:
        raise ValueError(f"{auth_type} is not supported for {provider}")
    normalized = {
        str(key).strip(): str(value).strip()
        for key, value in credential.items()
        if str(key).strip() and str(value).strip()
    }
    if auth_type == "OAUTH_CLIENT_CREDENTIALS":
        required = {"directory_tenant_id", "client_id", "client_secret"}
        if not required.issubset(normalized):
            raise ValueError(
                "OAuth credential requires directory_tenant_id, client_id, and client_secret"
            )
        if not _DIRECTORY_PATTERN.fullmatch(normalized["directory_tenant_id"]):
            raise ValueError("directory_tenant_id is invalid")
        if len(normalized["client_secret"]) < 8:
            raise ValueError("client_secret is too short")
    elif auth_type == "BASIC":
        if not {"username", "password"}.issubset(normalized):
            raise ValueError("Basic credential requires username and password")
    elif "token" not in normalized or len(normalized["token"]) < 8:
        raise ValueError("Token credential requires a token of at least 8 characters")
    return normalized


def discovery_credential_hint(auth_type: str, credential: dict[str, str]) -> str:
    if auth_type == "OAUTH_CLIENT_CREDENTIALS":
        return f"app …{credential['client_id'][-6:]}"
    if auth_type == "BASIC":
        return f"user {credential['username'][:20]}"
    return f"token …{credential['token'][-6:]}"


def _host_allowed(hostname: str, allowed_hosts: list[str]) -> bool:
    host = hostname.rstrip(".").lower()
    return any(host == item.strip().lower().rstrip(".") for item in allowed_hosts)


def _configuration_secret_paths(
    value: object,
    *,
    path: str = "configuration",
) -> list[str]:
    secret_markers = ("secret", "password", "token", "credential", "api_key")
    found: list[str] = []
    if isinstance(value, dict):
        for raw_key, nested in value.items():
            key = str(raw_key).strip()
            nested_path = f"{path}.{key}"
            if any(marker in key.lower() for marker in secret_markers):
                found.append(nested_path)
            found.extend(_configuration_secret_paths(nested, path=nested_path))
    elif isinstance(value, list):
        for index, nested in enumerate(value):
            found.extend(
                _configuration_secret_paths(nested, path=f"{path}[{index}]")
            )
    return found


def validate_discovery_configuration(
    provider: str,
    base_url: str | None,
    configuration: dict[str, Any],
    *,
    settings: Settings | None = None,
) -> tuple[str | None, dict[str, Any]]:
    runtime = settings or get_settings()
    provider = provider.strip().upper()
    config = dict(configuration)
    forbidden_paths = sorted(set(_configuration_secret_paths(config)))
    if forbidden_paths:
        raise ValueError(
            "Secrets must be stored in credential, not configuration: "
            + ", ".join(forbidden_paths)
        )
    normalized_base: str | None = None
    if provider == "SCCM_ADMIN_SERVICE":
        parsed = urlsplit((base_url or "").strip())
        if (
            parsed.scheme != "https"
            or not parsed.hostname
            or parsed.username
            or parsed.password
            or parsed.query
            or parsed.fragment
        ):
            raise ValueError("SCCM AdminService requires an explicit HTTPS base URL")
        if not _host_allowed(
            parsed.hostname,
            [str(item) for item in runtime.asset_discovery_sccm_allowed_hosts],
        ):
            raise ValueError(
                "SCCM host is not in the allowed host list "
                "(ASSET_DISCOVERY_SCCM_ALLOWED_HOSTS)"
            )
        normalized_base = (base_url or "").strip().rstrip("/")
        config["endpoint_path"] = str(
            config.get("endpoint_path") or "/AdminService/v1.0/Device"
        ).strip()
        if not config["endpoint_path"].startswith("/AdminService/"):
            raise ValueError("SCCM endpoint_path must stay below /AdminService/")
    elif provider == "INTUNE":
        normalized_base = "https://graph.microsoft.com"
    elif provider == "AZURE_RESOURCE_GRAPH":
        normalized_base = "https://management.azure.com"
        subscriptions = config.get("subscription_ids", [])
        if not isinstance(subscriptions, list) or len(subscriptions) > 500:
            raise ValueError("subscription_ids must be an array with at most 500 items")
        config["subscription_ids"] = [
            str(item).strip() for item in subscriptions if str(item).strip()
        ]
        query = str(
            config.get("query")
            or "Resources | project id, name, type, location, tags, resourceGroup, subscriptionId"
        ).strip()
        if not query or len(query) > 20_000:
            raise ValueError("Azure Resource Graph query is invalid")
        config["query"] = query
    elif provider == "LANSWEEPER_DATA_API":
        normalized_base = "https://api.lansweeper.com"
        site_id = str(config.get("site_id") or "").strip()
        if not site_id or len(site_id) > 255:
            raise ValueError("Lansweeper site_id is required")
        config["site_id"] = site_id
        page_size = int(config.get("page_size") or 100)
        if page_size < 1 or page_size > 500:
            raise ValueError("Lansweeper page_size must be between 1 and 500")
        config["page_size"] = page_size
    else:
        raise ValueError("Unsupported asset discovery provider")
    return normalized_base, config


def _retry_after(headers: httpx.Headers) -> int | None:
    value = headers.get("retry-after")
    if not value:
        return None
    try:
        return max(1, min(int(value), 86_400))
    except ValueError:
        return None


def _request_json(
    client: httpx.Client,
    method: str,
    url: str,
    *,
    headers: dict[str, str] | None = None,
    data: dict[str, str] | None = None,
    json_body: dict[str, Any] | None = None,
    max_bytes: int = 20 * 1024 * 1024,
) -> tuple[dict[str, Any], httpx.Headers]:
    try:
        with client.stream(
            method,
            url,
            headers=headers,
            data=data,
            json=json_body,
        ) as response:
            chunks: list[bytes] = []
            total = 0
            for chunk in response.iter_bytes():
                total += len(chunk)
                if total > max_bytes:
                    raise AssetDiscoveryError(
                        "Provider response exceeded the configured safety limit",
                        retryable=False,
                    )
                chunks.append(chunk)
            raw = b"".join(chunks)
            if response.is_redirect:
                raise AssetDiscoveryError(
                    "Provider redirect was rejected",
                    retryable=False,
                    status_code=response.status_code,
                )
            if response.status_code >= 400:
                retryable = response.status_code in {408, 425, 429} or (
                    response.status_code >= 500
                )
                raise AssetDiscoveryError(
                    f"Provider returned HTTP {response.status_code}",
                    retryable=retryable,
                    status_code=response.status_code,
                    retry_after_seconds=_retry_after(response.headers),
                )
            try:
                payload = json.loads(raw or b"{}")
            except (TypeError, ValueError) as exc:
                raise AssetDiscoveryError(
                    "Provider returned invalid JSON",
                    retryable=False,
                ) from exc
            if not isinstance(payload, dict):
                raise AssetDiscoveryError(
                    "Provider response must be a JSON object",
                    retryable=False,
                )
            return payload, response.headers
    except AssetDiscoveryError:
        raise
    except (httpx.TimeoutException, httpx.NetworkError) as exc:
        raise AssetDiscoveryError(
            f"Provider network failure: {exc.__class__.__name__}",
            retryable=True,
        ) from exc


def _oauth_token(
    client: httpx.Client,
    credential: dict[str, str],
    *,
    scope: str,
) -> str:
    tenant = credential["directory_tenant_id"]
    payload, _ = _request_json(
        client,
        "POST",
        f"https://login.microsoftonline.com/{tenant}/oauth2/v2.0/token",
        data={
            "client_id": credential["client_id"],
            "client_secret": credential["client_secret"],
            "grant_type": "client_credentials",
            "scope": scope,
        },
        max_bytes=1_048_576,
    )
    token = payload.get("access_token")
    if not isinstance(token, str) or not token:
        raise AssetDiscoveryError(
            "OAuth provider did not return access_token",
            retryable=False,
        )
    return token


def _bounded_external_id(provider: str, value: object) -> str:
    raw = str(value or "").strip()
    if not raw:
        raise AssetDiscoveryError(
            f"{provider} record is missing its external identifier",
            retryable=False,
        )
    if len(raw) <= 255:
        return raw
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()
    return f"{provider.lower()}:{digest}"


def _clean(value: object, maximum: int) -> str | None:
    if value is None:
        return None
    text = " ".join(str(value).replace("\x00", "").split())
    return text[:maximum] or None


def normalize_intune_device(item: dict[str, Any]) -> dict[str, Any]:
    external_id = _bounded_external_id("INTUNE", item.get("id"))
    name = _clean(item.get("deviceName"), 200) or f"Intune device {external_id[-8:]}"
    compliance = _clean(item.get("complianceState"), 64)
    return {
        "external_id": external_id,
        "name": name,
        "serial_number": _clean(item.get("serialNumber"), 120),
        "manufacturer": _clean(item.get("manufacturer"), 200),
        "model": _clean(item.get("model"), 200),
        "original_type": "Intune managed device",
        "lifecycle_status": "ACTIVE",
        "condition": "good" if compliance == "compliant" else compliance,
        "assigned_to_name": _clean(item.get("userDisplayName"), 200),
        "verification_status": "DISCOVERED",
        "attributes": {
            "operating_system": item.get("operatingSystem"),
            "os_version": item.get("osVersion"),
            "compliance_state": item.get("complianceState"),
            "management_agent": item.get("managementAgent"),
            "owner_type": item.get("managedDeviceOwnerType"),
            "last_sync_at": item.get("lastSyncDateTime"),
            "azure_ad_device_id": item.get("azureADDeviceId"),
            "user_principal_name": item.get("userPrincipalName"),
            "wifi_mac": item.get("wiFiMacAddress"),
            "ethernet_mac": item.get("ethernetMacAddress"),
            "imei": item.get("imei"),
        },
    }


def normalize_azure_resource(item: dict[str, Any]) -> dict[str, Any]:
    raw_id = str(item.get("id") or "").strip()
    external_id = _bounded_external_id("AZURE", raw_id)
    tags = item.get("tags") if isinstance(item.get("tags"), dict) else {}
    environment = str(tags.get("environment") or tags.get("Environment") or "OTHER")
    environment = environment.strip().upper()
    if environment not in {"PRODUCTION", "STAGING", "TEST", "DEVELOPMENT"}:
        environment = "OTHER"
    resource_type = _clean(item.get("type"), 120)
    return {
        "external_id": external_id,
        "name": _clean(item.get("name"), 200) or f"Azure resource {external_id[-8:]}",
        "original_type": resource_type or "Azure resource",
        "lifecycle_status": "ACTIVE",
        "environment": environment,
        "location": _clean(item.get("location"), 200),
        "verification_status": "DISCOVERED",
        "attributes": {
            "azure_resource_id": raw_id,
            "azure_resource_type": item.get("type"),
            "resource_group": item.get("resourceGroup"),
            "subscription_id": item.get("subscriptionId"),
            "tags": tags,
        },
    }


def normalize_sccm_device(item: dict[str, Any]) -> dict[str, Any]:
    raw_id = (
        item.get("MachineId")
        or item.get("ResourceId")
        or item.get("ResourceID")
        or item.get("SMSID")
        or item.get("Id")
        or item.get("Name")
    )
    external_id = _bounded_external_id("SCCM", raw_id)
    name = (
        _clean(item.get("Name"), 200)
        or _clean(item.get("DeviceName"), 200)
        or f"SCCM device {external_id[-8:]}"
    )
    return {
        "external_id": external_id,
        "name": name,
        "serial_number": _clean(
            item.get("SerialNumber") or item.get("SerialNumber0"),
            120,
        ),
        "manufacturer": _clean(item.get("Manufacturer"), 200),
        "model": _clean(item.get("Model"), 200),
        "original_type": "Configuration Manager device",
        "lifecycle_status": "ACTIVE",
        "assigned_to_name": _clean(
            item.get("PrimaryUser") or item.get("UserName"),
            200,
        ),
        "verification_status": "DISCOVERED",
        "attributes": {
            "sccm_resource_id": raw_id,
            "client_version": item.get("ClientVersion"),
            "operating_system": item.get("OperatingSystem"),
            "site_code": item.get("SiteCode"),
            "last_active_time": item.get("LastActiveTime"),
        },
    }


def normalize_lansweeper_asset(item: dict[str, Any]) -> dict[str, Any]:
    external_id = _bounded_external_id(
        "LANSWEEPER",
        item.get("key") or item.get("_id"),
    )
    basic = item.get("assetBasicInfo")
    custom = item.get("assetCustom")
    operating_system = item.get("operatingSystem")
    basic = basic if isinstance(basic, dict) else {}
    custom = custom if isinstance(custom, dict) else {}
    operating_system = operating_system if isinstance(operating_system, dict) else {}
    return {
        "external_id": external_id,
        "name": _clean(basic.get("name"), 200)
        or f"Lansweeper asset {external_id[-8:]}",
        "serial_number": _clean(custom.get("serialNumber"), 120),
        "manufacturer": _clean(custom.get("manufacturer"), 200),
        "model": _clean(custom.get("model"), 200),
        "original_type": _clean(
            basic.get("type") or basic.get("typeGroup"),
            120,
        ),
        "lifecycle_status": "ACTIVE",
        "condition": _clean(custom.get("stateName"), 32) or "good",
        "assigned_to_name": _clean(basic.get("userName"), 200),
        "verification_status": "DISCOVERED",
        "description": _clean(basic.get("description"), 10_000),
        "attributes": {
            "lansweeper_url": item.get("url"),
            "last_seen_at": basic.get("lastSeen"),
            "ip_address": basic.get("ipAddress"),
            "mac_address": basic.get("mac"),
            "cloud_provider": basic.get("cloudProvider"),
            "cloud_region": basic.get("cloudRegion"),
            "cloud_tags": basic.get("cloudTags"),
            "operating_system": operating_system.get("name"),
            "os_version": operating_system.get("version"),
        },
    }


def _same_origin_url(candidate: str, origin: str) -> str:
    parsed = urlsplit(candidate)
    expected = urlsplit(origin)
    if (
        parsed.scheme != "https"
        or parsed.hostname != expected.hostname
        or parsed.port != expected.port
        or parsed.username
        or parsed.password
        or parsed.fragment
    ):
        raise AssetDiscoveryError(
            "Provider pagination URL changed origin",
            retryable=False,
        )
    return candidate


def _fetch_intune(
    client: httpx.Client,
    credential: dict[str, str],
    max_records: int,
) -> DiscoveryFetchResult:
    token = _oauth_token(
        client,
        credential,
        scope="https://graph.microsoft.com/.default",
    )
    url = (
        "https://graph.microsoft.com/v1.0/deviceManagement/managedDevices"
        f"?$select={_INTUNE_SELECT}&$top=100"
    )
    records: list[dict[str, Any]] = []
    pages = 0
    request_id = None
    complete = True
    visited_urls: set[str] = set()
    while url:
        safe_url = _same_origin_url(url, "https://graph.microsoft.com")
        if safe_url in visited_urls or pages >= _MAX_PROVIDER_PAGES:
            raise AssetDiscoveryError(
                "Intune pagination did not make progress",
                retryable=False,
            )
        visited_urls.add(safe_url)
        payload, headers = _request_json(
            client,
            "GET",
            safe_url,
            headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
        )
        pages += 1
        request_id = headers.get("request-id") or request_id
        values = payload.get("value")
        if not isinstance(values, list):
            raise AssetDiscoveryError(
                "Intune response is missing value[]",
                retryable=False,
            )
        for item_index, item in enumerate(values):
            if isinstance(item, dict):
                records.append(normalize_intune_device(item))
                if len(records) >= max_records:
                    complete = (
                        item_index == len(values) - 1
                        and not bool(payload.get("@odata.nextLink"))
                    )
                    return DiscoveryFetchResult(
                        records[:max_records],
                        pages,
                        complete,
                        str(payload.get("@odata.nextLink") or "") or None,
                        request_id,
                    )
        next_link = payload.get("@odata.nextLink")
        url = str(next_link) if isinstance(next_link, str) and next_link else ""
    return DiscoveryFetchResult(records, pages, complete, None, request_id)


def _fetch_azure_resource_graph(
    client: httpx.Client,
    credential: dict[str, str],
    configuration: dict[str, Any],
    max_records: int,
) -> DiscoveryFetchResult:
    token = _oauth_token(
        client,
        credential,
        scope="https://management.azure.com/.default",
    )
    url = (
        "https://management.azure.com/providers/Microsoft.ResourceGraph/resources"
        "?api-version=2024-04-01"
    )
    records: list[dict[str, Any]] = []
    pages = 0
    cursor: str | None = None
    request_id = None
    complete = True
    visited_cursors: set[str] = set()
    while True:
        page_key = cursor or "__FIRST__"
        if page_key in visited_cursors or pages >= _MAX_PROVIDER_PAGES:
            raise AssetDiscoveryError(
                "Azure Resource Graph pagination did not make progress",
                retryable=False,
            )
        visited_cursors.add(page_key)
        body: dict[str, Any] = {
            "query": configuration["query"],
            "options": {"$top": min(1000, max_records - len(records))},
        }
        subscriptions = configuration.get("subscription_ids")
        if subscriptions:
            body["subscriptions"] = subscriptions
        if cursor:
            body["options"]["$skipToken"] = cursor
        payload, headers = _request_json(
            client,
            "POST",
            url,
            headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
            json_body=body,
        )
        pages += 1
        request_id = headers.get("x-ms-request-id") or request_id
        rows = payload.get("data")
        if not isinstance(rows, list):
            raise AssetDiscoveryError(
                "Azure Resource Graph response is missing data[]",
                retryable=False,
            )
        for row_index, row in enumerate(rows):
            if isinstance(row, dict):
                records.append(normalize_azure_resource(row))
                if len(records) >= max_records:
                    complete = (
                        row_index == len(rows) - 1
                        and not bool(payload.get("$skipToken"))
                    )
                    return DiscoveryFetchResult(
                        records[:max_records],
                        pages,
                        complete,
                        str(payload.get("$skipToken") or "") or None,
                        request_id,
                    )
        next_cursor = payload.get("$skipToken")
        if not isinstance(next_cursor, str) or not next_cursor:
            break
        cursor = next_cursor
    return DiscoveryFetchResult(records, pages, complete, cursor, request_id)


def _fetch_sccm(
    client: httpx.Client,
    connector: AssetDiscoveryConnector,
    credential: dict[str, str],
    configuration: dict[str, Any],
    max_records: int,
) -> DiscoveryFetchResult:
    origin = (connector.base_url or "").rstrip("/")
    url = urljoin(origin + "/", configuration["endpoint_path"].lstrip("/"))
    headers = {"Accept": "application/json"}
    auth: httpx.BasicAuth | None = None
    if connector.auth_type == "BEARER":
        headers["Authorization"] = f"Bearer {credential['token']}"
    else:
        auth = httpx.BasicAuth(credential["username"], credential["password"])
    records: list[dict[str, Any]] = []
    pages = 0
    request_id = None
    complete = True
    visited_urls: set[str] = set()
    while url:
        safe_url = _same_origin_url(url, origin)
        if safe_url in visited_urls or pages >= _MAX_PROVIDER_PAGES:
            raise AssetDiscoveryError(
                "SCCM pagination did not make progress",
                retryable=False,
            )
        visited_urls.add(safe_url)
        try:
            with client.stream(
                "GET",
                safe_url,
                headers=headers,
                auth=auth,
            ) as response:
                chunks: list[bytes] = []
                total = 0
                for chunk in response.iter_bytes():
                    total += len(chunk)
                    if total > 20 * 1024 * 1024:
                        raise AssetDiscoveryError(
                            "SCCM response exceeded the safety limit",
                            retryable=False,
                        )
                    chunks.append(chunk)
                if response.is_redirect:
                    raise AssetDiscoveryError(
                        "SCCM redirect was rejected",
                        retryable=False,
                    )
                if response.status_code >= 400:
                    raise AssetDiscoveryError(
                        f"SCCM returned HTTP {response.status_code}",
                        retryable=response.status_code in {408, 425, 429}
                        or response.status_code >= 500,
                        status_code=response.status_code,
                        retry_after_seconds=_retry_after(response.headers),
                    )
                payload = json.loads(b"".join(chunks) or b"{}")
                response_headers = response.headers
        except AssetDiscoveryError:
            raise
        except (httpx.TimeoutException, httpx.NetworkError) as exc:
            raise AssetDiscoveryError(
                f"SCCM network failure: {exc.__class__.__name__}",
                retryable=True,
            ) from exc
        except (TypeError, ValueError) as exc:
            raise AssetDiscoveryError(
                "SCCM returned invalid JSON",
                retryable=False,
            ) from exc
        if not isinstance(payload, dict) or not isinstance(payload.get("value"), list):
            raise AssetDiscoveryError(
                "SCCM response is missing value[]",
                retryable=False,
            )
        pages += 1
        request_id = response_headers.get("request-id") or request_id
        for item_index, item in enumerate(payload["value"]):
            if isinstance(item, dict):
                records.append(normalize_sccm_device(item))
                if len(records) >= max_records:
                    complete = (
                        item_index == len(payload["value"]) - 1
                        and not bool(payload.get("@odata.nextLink"))
                    )
                    return DiscoveryFetchResult(
                        records[:max_records],
                        pages,
                        complete,
                        str(payload.get("@odata.nextLink") or "") or None,
                        request_id,
                    )
        next_link = payload.get("@odata.nextLink")
        url = str(next_link) if isinstance(next_link, str) and next_link else ""
    return DiscoveryFetchResult(records, pages, complete, None, request_id)


def _fetch_lansweeper(
    client: httpx.Client,
    connector: AssetDiscoveryConnector,
    credential: dict[str, str],
    configuration: dict[str, Any],
    max_records: int,
) -> DiscoveryFetchResult:
    query = """
    query AssetDiscovery($siteId: ID!, $pagination: AssetsPaginationInputValidated) {
      site(id: $siteId) {
        assetResources(assetPagination: $pagination, fields: [
          "key", "url", "assetBasicInfo.name", "assetBasicInfo.description",
          "assetBasicInfo.type", "assetBasicInfo.typeGroup",
          "assetBasicInfo.lastSeen", "assetBasicInfo.ipAddress",
          "assetBasicInfo.mac", "assetBasicInfo.userName",
          "assetBasicInfo.cloudProvider", "assetBasicInfo.cloudRegion",
          "assetBasicInfo.cloudTags", "assetCustom.manufacturer",
          "assetCustom.model", "assetCustom.serialNumber",
          "assetCustom.stateName", "operatingSystem.name",
          "operatingSystem.version"
        ]) {
          total
          pagination { limit current next page }
          items
        }
      }
    }
    """
    if connector.auth_type == "API_TOKEN":
        authorization = f"Token {credential['token']}"
    else:
        authorization = f"Bearer {credential['token']}"
    page_size = min(int(configuration.get("page_size") or 100), max_records)
    pagination: dict[str, Any] = {"limit": page_size, "page": "FIRST"}
    records: list[dict[str, Any]] = []
    pages = 0
    cursor: str | None = None
    request_id = None
    complete = True
    visited_cursors: set[str] = set()
    while True:
        page_key = cursor or "__FIRST__"
        if page_key in visited_cursors or pages >= _MAX_PROVIDER_PAGES:
            raise AssetDiscoveryError(
                "Lansweeper pagination did not make progress",
                retryable=False,
            )
        visited_cursors.add(page_key)
        payload, headers = _request_json(
            client,
            "POST",
            "https://api.lansweeper.com/api/v2/graphql",
            headers={
                "Authorization": authorization,
                "Accept": "application/json",
            },
            json_body={
                "query": query,
                "operationName": "AssetDiscovery",
                "variables": {
                    "siteId": configuration["site_id"],
                    "pagination": pagination,
                },
            },
            max_bytes=5 * 1024 * 1024,
        )
        errors = payload.get("errors")
        if isinstance(errors, list) and errors:
            first = errors[0] if isinstance(errors[0], dict) else {}
            message = _clean(first.get("message"), 500) or "GraphQL error"
            raise AssetDiscoveryError(
                f"Lansweeper rejected the query: {message}",
                retryable=False,
            )
        data = payload.get("data")
        site = data.get("site") if isinstance(data, dict) else None
        result = site.get("assetResources") if isinstance(site, dict) else None
        if not isinstance(result, dict) or not isinstance(result.get("items"), list):
            raise AssetDiscoveryError(
                "Lansweeper response is missing assetResources.items[]",
                retryable=False,
            )
        pages += 1
        request_id = headers.get("x-request-id") or request_id
        for item_index, item in enumerate(result["items"]):
            if isinstance(item, dict):
                records.append(normalize_lansweeper_asset(item))
                if len(records) >= max_records:
                    page_info = result.get("pagination")
                    next_cursor = (
                        page_info.get("next") if isinstance(page_info, dict) else None
                    )
                    complete = (
                        item_index == len(result["items"]) - 1
                        and not bool(next_cursor)
                    )
                    return DiscoveryFetchResult(
                        records[:max_records],
                        pages,
                        complete,
                        str(next_cursor) if next_cursor else None,
                        request_id,
                    )
        page_info = result.get("pagination")
        next_cursor = page_info.get("next") if isinstance(page_info, dict) else None
        if not next_cursor:
            break
        cursor = str(next_cursor)
        pagination = {
            "limit": page_size,
            "page": "NEXT",
            "cursor": cursor,
        }
    return DiscoveryFetchResult(records, pages, complete, cursor, request_id)


def fetch_discovery_records(
    connector: AssetDiscoveryConnector,
    *,
    max_records: int | None = None,
    settings: Settings | None = None,
) -> DiscoveryFetchResult:
    runtime = settings or get_settings()
    credential = decrypt_discovery_credential(connector, settings=runtime)
    configuration = _json_object(connector.configuration_json)
    effective_max = max(1, min(max_records or connector.max_records, 50_000))
    timeout = httpx.Timeout(runtime.asset_discovery_request_timeout_seconds)
    with httpx.Client(timeout=timeout, follow_redirects=False) as client:
        if connector.provider == "INTUNE":
            return _fetch_intune(client, credential, effective_max)
        if connector.provider == "AZURE_RESOURCE_GRAPH":
            return _fetch_azure_resource_graph(
                client,
                credential,
                configuration,
                effective_max,
            )
        if connector.provider == "SCCM_ADMIN_SERVICE":
            return _fetch_sccm(
                client,
                connector,
                credential,
                configuration,
                effective_max,
            )
        if connector.provider == "LANSWEEPER_DATA_API":
            return _fetch_lansweeper(
                client,
                connector,
                credential,
                configuration,
                effective_max,
            )
    raise AssetDiscoveryError("Unsupported provider", retryable=False)


def enqueue_discovery_run(
    db: Session,
    connector: AssetDiscoveryConnector,
    *,
    trigger_type: str,
    requested_by_id: str | None,
    idempotency_key: str | None = None,
) -> AssetDiscoveryRun:
    key = (idempotency_key or str(uuid.uuid4())).strip()
    existing = db.scalar(
        select(AssetDiscoveryRun).where(
            AssetDiscoveryRun.connector_id == connector.id,
            AssetDiscoveryRun.idempotency_key == key,
        )
    )
    if existing is not None:
        return existing
    now = utcnow()
    run = AssetDiscoveryRun(
        id=str(uuid.uuid4()),
        tenant_id=connector.tenant_id,
        connector_id=connector.id,
        idempotency_key=key,
        trigger_type=trigger_type,
        status="QUEUED",
        attempts=0,
        max_attempts=4,
        next_attempt_at=now,
        requested_by_id=requested_by_id,
        pages_fetched=0,
        records_fetched=0,
        complete_snapshot=False,
        reconciliation_run_ids_json="[]",
        created_count=0,
        updated_count=0,
        unchanged_count=0,
        ambiguous_count=0,
        invalid_count=0,
        missing_count=0,
        stale_count=0,
        result_json="{}",
        created_at=now,
        updated_at=now,
    )
    db.add(run)
    db.flush()
    return run


def _govern_discovery_records(
    db: Session,
    connector: AssetDiscoveryConnector,
    records: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    retired_external_ids = set(
        db.scalars(
            select(AssetDiscoveryStaleCandidate.external_id).where(
                AssetDiscoveryStaleCandidate.connector_id == connector.id,
                AssetDiscoveryStaleCandidate.status == "RETIRED",
            )
        ).all()
    )
    seen: set[str] = set()
    governed: list[dict[str, Any]] = []
    for record in records:
        external_id = str(record.get("external_id") or "").strip()
        if not external_id:
            raise AssetDiscoveryError(
                "Normalized discovery record is missing external_id",
                retryable=False,
            )
        if external_id in seen:
            raise AssetDiscoveryError(
                f"Provider returned duplicate external_id: {external_id[:120]}",
                retryable=False,
            )
        seen.add(external_id)
        normalized = dict(record)
        if external_id in retired_external_ids:
            # A human retirement decision is sticky. Discovery may continue to
            # refresh technical facts, but it cannot silently reactivate the CI.
            normalized.pop("lifecycle_status", None)
            normalized.pop("verification_status", None)
        governed.append(normalized)
    return governed


def _process_missing_identities(
    db: Session,
    connector: AssetDiscoveryConnector,
    run: AssetDiscoveryRun,
    seen_external_ids: set[str],
) -> tuple[int, int]:
    now = utcnow()
    missing = 0
    stale = 0
    identities = db.scalars(
        select(CMDBSourceIdentity).where(
            CMDBSourceIdentity.source_id == connector.cmdb_source_id
        )
    ).all()
    for identity in identities:
        candidate = db.scalar(
            select(AssetDiscoveryStaleCandidate).where(
                AssetDiscoveryStaleCandidate.source_identity_id == identity.id
            )
        )
        if identity.external_id in seen_external_ids:
            identity.discovery_state = "ACTIVE"
            identity.missing_run_count = 0
            identity.first_missing_at = None
            identity.last_missing_at = None
            identity.last_seen_run_id = run.id
            identity.last_seen_at = now
            identity.updated_at = now
            if candidate is not None and candidate.status in {"OPEN", "DISMISSED"}:
                candidate.status = "RECOVERED"
                candidate.version += 1
                candidate.decided_at = now
                candidate.decision_reason = "Asset returned in a complete discovery snapshot"
                candidate.updated_at = now
            continue
        missing += 1
        identity.missing_run_count += 1
        identity.first_missing_at = identity.first_missing_at or now
        identity.last_missing_at = now
        identity.discovery_state = (
            "STALE"
            if identity.missing_run_count >= connector.missing_threshold_runs
            else "MISSING"
        )
        identity.updated_at = now
        if identity.discovery_state != "STALE":
            continue
        stale += 1
        if candidate is None:
            candidate = AssetDiscoveryStaleCandidate(
                id=str(uuid.uuid4()),
                tenant_id=connector.tenant_id,
                connector_id=connector.id,
                source_identity_id=identity.id,
                asset_id=identity.asset_id,
                external_id=identity.external_id,
                status="OPEN",
                missing_run_count=identity.missing_run_count,
                first_missing_at=identity.first_missing_at,
                last_missing_at=now,
                version=1,
                created_at=now,
                updated_at=now,
            )
            db.add(candidate)
        elif candidate.status in {"OPEN", "RECOVERED"}:
            candidate.status = "OPEN"
            candidate.missing_run_count = identity.missing_run_count
            candidate.first_missing_at = identity.first_missing_at
            candidate.last_missing_at = now
            candidate.version += 1
            candidate.decision_reason = None
            candidate.decided_by_id = None
            candidate.decided_at = None
            candidate.updated_at = now
    # SessionLocal intentionally disables autoflush. Persist reconciliation side
    # effects before callers issue follow-up reads or decisions in the same unit
    # of work.
    db.flush()
    return missing, stale


def _actor_id(db: Session, connector: AssetDiscoveryConnector, run: AssetDiscoveryRun) -> str:
    candidate = run.requested_by_id or connector.updated_by_id or connector.created_by_id
    if candidate and db.get(User, candidate):
        return candidate
    actor = db.scalar(
        select(User)
        .where(
            User.tenant_id == connector.tenant_id,
            User.is_active.is_(True),
        )
        .order_by(User.created_at, User.id)
    )
    if actor is None:
        raise AssetDiscoveryError(
            "No active tenant actor is available for reconciliation",
            retryable=False,
        )
    return actor.id


def process_discovery_run(
    db: Session,
    run: AssetDiscoveryRun,
    *,
    settings: Settings | None = None,
) -> AssetDiscoveryRun:
    connector = db.get(AssetDiscoveryConnector, run.connector_id)
    if connector is None or connector.status != "ACTIVE":
        run.status = "CANCELLED"
        run.last_error = "Connector is unavailable or not active"
        run.completed_at = utcnow()
        run.updated_at = run.completed_at
        db.flush()
        return run
    source = db.get(CMDBSource, connector.cmdb_source_id)
    if source is None or source.status != "ACTIVE":
        raise AssetDiscoveryError("CMDB source is unavailable or inactive", retryable=False)
    now = utcnow()
    run.status = "RUNNING"
    run.attempts += 1
    run.started_at = run.started_at or now
    run.updated_at = now
    connector.last_started_at = now
    connector.updated_at = now
    db.flush()

    result = fetch_discovery_records(connector, settings=settings)
    records = _govern_discovery_records(db, connector, result.records)
    actor_id = _actor_id(db, connector, run)
    reconciliation_ids: list[str] = []
    created = updated = unchanged = ambiguous = invalid = 0
    for index in range(0, len(records), 500):
        chunk = records[index : index + 500]
        reconciliation = preview_reconciliation(
            db,
            source=source,
            idempotency_key=f"asset-discovery:{run.id}:{index // 500 + 1}",
            records=chunk,
            actor_id=actor_id,
        )
        reconciliation_ids.append(reconciliation.id)
        if connector.auto_apply and not (
            reconciliation.invalid_count or reconciliation.ambiguous_count
        ):
            reconciliation = apply_reconciliation(
                db,
                run_id=reconciliation.id,
                actor_id=actor_id,
            )
        created += reconciliation.create_count
        updated += reconciliation.update_count
        unchanged += reconciliation.unchanged_count
        ambiguous += reconciliation.ambiguous_count
        invalid += reconciliation.invalid_count

    run.pages_fetched = result.pages
    run.records_fetched = len(records)
    run.complete_snapshot = result.complete_snapshot
    run.reconciliation_run_ids_json = canonical_json(reconciliation_ids)
    run.created_count = created
    run.updated_count = updated
    run.unchanged_count = unchanged
    run.ambiguous_count = ambiguous
    run.invalid_count = invalid
    run.provider_cursor = result.cursor
    run.provider_request_id = result.request_id
    if result.complete_snapshot and run.trigger_type != "TEST":
        missing, stale = _process_missing_identities(
            db,
            connector,
            run,
            {str(item["external_id"]) for item in records},
        )
        run.missing_count = missing
        run.stale_count = stale
    completed = utcnow()
    run.status = (
        "COMPLETED_WITH_ERRORS" if ambiguous or invalid else "COMPLETED"
    )
    run.result_json = canonical_json(
        {
            "auto_apply": connector.auto_apply,
            "complete_snapshot": result.complete_snapshot,
            "reconciliation_runs": reconciliation_ids,
            "truncated_at_max_records": not result.complete_snapshot,
        }
    )
    run.last_error = None
    run.completed_at = completed
    run.updated_at = completed
    connector.last_completed_at = completed
    connector.last_success_at = completed
    connector.last_error = None
    connector.successful_runs += 1
    connector.discovered_records += len(records)
    connector.next_run_at = completed + timedelta(minutes=connector.schedule_minutes)
    connector.updated_at = completed
    db.flush()
    return run


def decide_stale_candidate(
    db: Session,
    candidate: AssetDiscoveryStaleCandidate,
    *,
    decision: str,
    expected_version: int,
    actor_id: str,
    reason: str,
) -> AssetDiscoveryStaleCandidate:
    if candidate.version != expected_version:
        raise ReconciliationConflict(
            f"Stale candidate changed; current version is {candidate.version}"
        )
    if candidate.status != "OPEN":
        raise ReconciliationConflict("Stale candidate is already resolved")
    now = utcnow()
    decision = decision.upper()
    if decision == "RETIRE":
        asset = db.get(Asset, candidate.asset_id)
        if asset is None or asset.tenant_id != candidate.tenant_id:
            raise ReconciliationConflict("Candidate asset is unavailable")
        before = {
            "lifecycle_status": asset.lifecycle_status,
            "status": asset.status,
            "verification_status": asset.verification_status,
        }
        asset.lifecycle_status = "RETIRED"
        asset.status = "inactive"
        asset.verification_status = "STALE_DISCOVERY_RETIRED"
        asset.ci_version += 1
        asset.updated_at = now
        db.add(
            AssetHistory(
                id=str(uuid.uuid4()),
                asset_id=asset.id,
                actor_id=actor_id,
                action="asset_discovery_stale_retired",
                old_value=before,
                new_value={
                    "lifecycle_status": asset.lifecycle_status,
                    "status": asset.status,
                    "verification_status": asset.verification_status,
                    "candidate_id": candidate.id,
                },
                comment=reason.strip(),
                created_at=now,
            )
        )
        candidate.status = "RETIRED"
    elif decision == "DISMISS":
        candidate.status = "DISMISSED"
    else:
        raise ValueError("decision must be RETIRE or DISMISS")
    candidate.version += 1
    candidate.decision_reason = reason.strip()
    candidate.decided_by_id = actor_id
    candidate.decided_at = now
    candidate.updated_at = now
    db.flush()
    return candidate


def _schedule_due_connectors(db: Session, *, batch_size: int) -> int:
    now = utcnow()
    statement = (
        select(AssetDiscoveryConnector)
        .where(
            AssetDiscoveryConnector.status == "ACTIVE",
            AssetDiscoveryConnector.next_run_at.is_not(None),
            AssetDiscoveryConnector.next_run_at <= now,
        )
        .order_by(AssetDiscoveryConnector.next_run_at)
        .limit(batch_size)
    )
    if db.get_bind().dialect.name == "postgresql":
        statement = statement.with_for_update(skip_locked=True)
    connectors = db.scalars(
        statement
    ).all()
    scheduled = 0
    for connector in connectors:
        pending = db.scalar(
            select(AssetDiscoveryRun.id).where(
                AssetDiscoveryRun.connector_id == connector.id,
                AssetDiscoveryRun.status.in_({"QUEUED", "RUNNING", "RETRY"}),
            )
        )
        if pending:
            continue
        key = f"scheduled:{connector.next_run_at.isoformat()}"
        enqueue_discovery_run(
            db,
            connector,
            trigger_type="SCHEDULED",
            requested_by_id=connector.updated_by_id or connector.created_by_id,
            idempotency_key=key,
        )
        connector.next_run_at = now + timedelta(minutes=connector.schedule_minutes)
        scheduled += 1
    db.flush()
    return scheduled


def run_asset_discovery_cycle(
    db: Session,
    *,
    settings: Settings | None = None,
) -> dict[str, int]:
    runtime = settings or get_settings()
    scheduled = _schedule_due_connectors(
        db,
        batch_size=runtime.asset_discovery_worker_batch_size,
    )
    db.commit()
    now = utcnow()
    run_ids = db.scalars(
        select(AssetDiscoveryRun)
        .with_only_columns(AssetDiscoveryRun.id)
        .where(
            AssetDiscoveryRun.status.in_({"QUEUED", "RETRY"}),
            AssetDiscoveryRun.next_attempt_at <= now,
        )
        .order_by(AssetDiscoveryRun.created_at)
        .limit(runtime.asset_discovery_worker_batch_size)
    ).all()
    db.commit()
    processed = retried = dead_lettered = 0
    for run_id in run_ids:
        statement = select(AssetDiscoveryRun).where(
            AssetDiscoveryRun.id == run_id,
            AssetDiscoveryRun.status.in_({"QUEUED", "RETRY"}),
            AssetDiscoveryRun.next_attempt_at <= utcnow(),
        )
        if db.get_bind().dialect.name == "postgresql":
            statement = statement.with_for_update(skip_locked=True)
        run = db.scalar(statement)
        if run is None:
            db.rollback()
            continue
        connector = db.get(AssetDiscoveryConnector, run.connector_id)
        try:
            process_discovery_run(db, run, settings=runtime)
            db.commit()
            processed += 1
        except AssetDiscoveryError as exc:
            db.rollback()
            run = db.get(AssetDiscoveryRun, run.id)
            connector = (
                db.get(AssetDiscoveryConnector, run.connector_id) if run else None
            )
            if run is None:
                continue
            failed_at = utcnow()
            run.attempts += 1
            run.last_error = str(exc)[:2_000]
            run.updated_at = failed_at
            if exc.retryable and run.attempts < run.max_attempts:
                delay = exc.retry_after_seconds or min(3600, 30 * (2 ** run.attempts))
                run.status = "RETRY"
                run.next_attempt_at = failed_at + timedelta(seconds=delay)
                retried += 1
            else:
                run.status = "DEAD_LETTER" if exc.retryable else "FAILED"
                run.completed_at = failed_at
                dead_lettered += int(run.status == "DEAD_LETTER")
            if connector is not None:
                connector.last_failure_at = failed_at
                connector.last_error = str(exc)[:2_000]
                connector.failed_runs += 1
                connector.next_run_at = failed_at + timedelta(
                    minutes=connector.schedule_minutes
                )
                connector.updated_at = failed_at
            db.commit()
        except Exception as exc:
            db.rollback()
            run = db.get(AssetDiscoveryRun, run.id)
            if run is None:
                continue
            failed_at = utcnow()
            run.attempts += 1
            run.last_error = f"{exc.__class__.__name__}: internal processing failure"
            run.updated_at = failed_at
            if run.attempts < run.max_attempts:
                run.status = "RETRY"
                run.next_attempt_at = failed_at + timedelta(
                    seconds=min(3600, 30 * (2 ** run.attempts))
                )
                retried += 1
            else:
                run.status = "DEAD_LETTER"
                run.completed_at = failed_at
                dead_lettered += 1
            connector = db.get(AssetDiscoveryConnector, run.connector_id)
            if connector is not None:
                connector.last_failure_at = failed_at
                connector.last_error = run.last_error
                connector.failed_runs += 1
                connector.next_run_at = failed_at + timedelta(
                    minutes=connector.schedule_minutes
                )
                connector.updated_at = failed_at
            db.commit()
    return {
        "scheduled": scheduled,
        "processed": processed,
        "retried": retried,
        "dead_lettered": dead_lettered,
    }
