from __future__ import annotations

import hashlib
import logging
from collections.abc import Callable
from typing import Any

from fastapi import (
    APIRouter,
    Depends,
    Header,
    HTTPException,
    Query,
    Request,
    Response,
    status,
)
from fastapi.responses import JSONResponse
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models.identity_provisioning import (
    IdentityProvisioningConnector,
    IdentityProvisioningEvent,
    ProvisionedGroup,
    ProvisionedIdentity,
)
from app.models.tenant import Tenant
from app.models.user import User
from app.services.identity_lifecycle import (
    connector_allows_ip,
    hash_connector_token,
)
from app.services.scim_provisioning import (
    SCIM_CORE_GROUP,
    SCIM_CORE_USER,
    SCIM_ENTERPRISE_USER,
    SCIM_LIST_RESPONSE,
    ScimProvisioningError,
    apply_group_patch,
    apply_user_patch,
    begin_provisioning_event,
    canonical_payload_hash,
    deactivate_scim_user,
    delete_scim_group,
    mark_event_applied,
    mark_event_failed,
    parse_scim_filter,
    scim_group_resource,
    scim_user_resource,
    upsert_scim_group,
    upsert_scim_user,
)


logger = logging.getLogger(__name__)


class ScimJSONResponse(JSONResponse):
    media_type = "application/scim+json"


router = APIRouter(
    prefix="/scim/v2",
    default_response_class=ScimJSONResponse,
)

GROUP_FILTER_ATTRIBUTES = {"displayname", "externalid", "id"}


def _scim_error(
    status_code: int,
    detail: str,
    *,
    scim_type: str | None = None,
    headers: dict[str, str] | None = None,
) -> HTTPException:
    payload: dict[str, str] = {"message": detail}
    if scim_type:
        payload["scimType"] = scim_type
    return HTTPException(
        status_code=status_code,
        detail=payload,
        headers=headers,
    )


def _base_url(request: Request) -> str:
    raw = str(request.url).split("?", 1)[0]
    marker = "/scim/v2"
    prefix, separator, _ = raw.partition(marker)
    return f"{prefix}{separator}" if separator else raw.rstrip("/")


def _request_id(request: Request, payload: dict[str, Any]) -> str:
    supplied = (
        request.headers.get("x-request-id")
        or request.headers.get("x-ms-client-request-id")
        or request.headers.get("client-request-id")
    )
    if supplied:
        return supplied.strip()[:255]
    fingerprint = hashlib.sha256(
        (
            request.method
            + ":"
            + request.url.path
            + ":"
            + canonical_payload_hash(payload)
        ).encode("utf-8")
    ).hexdigest()
    return f"generated:{fingerprint}"


def _if_match(request: Request, version: int) -> None:
    supplied = request.headers.get("if-match")
    if supplied and supplied not in {"*", f'W/"{version}"', f'"{version}"'}:
        raise _scim_error(
            status.HTTP_412_PRECONDITION_FAILED,
            "Resource version does not match If-Match",
            scim_type="mutability",
        )


def _resource_type_resources(base: str) -> list[dict[str, Any]]:
    return [
        {
            "schemas": [
                "urn:ietf:params:scim:schemas:core:2.0:ResourceType"
            ],
            "id": "User",
            "name": "User",
            "endpoint": "/Users",
            "schema": SCIM_CORE_USER,
            "schemaExtensions": [
                {"schema": SCIM_ENTERPRISE_USER, "required": False}
            ],
            "meta": {
                "resourceType": "ResourceType",
                "location": f"{base}/ResourceTypes/User",
            },
        },
        {
            "schemas": [
                "urn:ietf:params:scim:schemas:core:2.0:ResourceType"
            ],
            "id": "Group",
            "name": "Group",
            "endpoint": "/Groups",
            "schema": SCIM_CORE_GROUP,
            "meta": {
                "resourceType": "ResourceType",
                "location": f"{base}/ResourceTypes/Group",
            },
        },
    ]


def _schema_resources() -> list[dict[str, Any]]:
    common_schema = ["urn:ietf:params:scim:schemas:core:2.0:Schema"]
    return [
        {
            "schemas": common_schema,
            "id": SCIM_CORE_USER,
            "name": "User",
            "description": "SBS ITSM provisioned user",
            "attributes": [
                {
                    "name": "userName",
                    "type": "string",
                    "multiValued": False,
                    "required": True,
                    "caseExact": False,
                    "mutability": "readWrite",
                    "returned": "default",
                    "uniqueness": "server",
                },
                {
                    "name": "externalId",
                    "type": "string",
                    "multiValued": False,
                    "required": True,
                    "caseExact": True,
                    "mutability": "immutable",
                    "returned": "default",
                    "uniqueness": "server",
                },
                {
                    "name": "displayName",
                    "type": "string",
                    "multiValued": False,
                    "required": False,
                    "mutability": "readWrite",
                    "returned": "default",
                },
                {
                    "name": "active",
                    "type": "boolean",
                    "multiValued": False,
                    "required": False,
                    "mutability": "readWrite",
                    "returned": "default",
                },
                {
                    "name": "title",
                    "type": "string",
                    "multiValued": False,
                    "required": False,
                    "mutability": "readWrite",
                    "returned": "default",
                },
                {
                    "name": "emails",
                    "type": "complex",
                    "multiValued": True,
                    "required": False,
                    "mutability": "readWrite",
                    "returned": "default",
                    "subAttributes": [
                        {"name": "value", "type": "string"},
                        {"name": "type", "type": "string"},
                        {"name": "primary", "type": "boolean"},
                    ],
                },
            ],
        },
        {
            "schemas": common_schema,
            "id": SCIM_ENTERPRISE_USER,
            "name": "EnterpriseUser",
            "description": "Enterprise user attributes",
            "attributes": [
                {
                    "name": "employeeNumber",
                    "type": "string",
                    "multiValued": False,
                    "mutability": "readWrite",
                },
                {
                    "name": "costCenter",
                    "type": "string",
                    "multiValued": False,
                    "mutability": "readWrite",
                },
                {
                    "name": "department",
                    "type": "string",
                    "multiValued": False,
                    "mutability": "readWrite",
                },
                {
                    "name": "manager",
                    "type": "complex",
                    "multiValued": False,
                    "mutability": "readWrite",
                    "subAttributes": [
                        {"name": "value", "type": "string"},
                        {"name": "$ref", "type": "reference"},
                        {
                            "name": "displayName",
                            "type": "string",
                            "mutability": "readOnly",
                        },
                    ],
                },
            ],
        },
        {
            "schemas": common_schema,
            "id": SCIM_CORE_GROUP,
            "name": "Group",
            "description": "SBS ITSM provisioned group",
            "attributes": [
                {
                    "name": "displayName",
                    "type": "string",
                    "multiValued": False,
                    "required": True,
                    "mutability": "readWrite",
                    "uniqueness": "server",
                },
                {
                    "name": "externalId",
                    "type": "string",
                    "multiValued": False,
                    "required": True,
                    "mutability": "immutable",
                    "uniqueness": "server",
                },
                {
                    "name": "members",
                    "type": "complex",
                    "multiValued": True,
                    "mutability": "readWrite",
                    "subAttributes": [
                        {"name": "value", "type": "string"},
                        {"name": "$ref", "type": "reference"},
                        {
                            "name": "display",
                            "type": "string",
                            "mutability": "readOnly",
                        },
                    ],
                },
            ],
        },
    ]


def get_scim_connector(
    request: Request,
    authorization: str | None = Header(default=None),
    db: Session = Depends(get_db),
) -> IdentityProvisioningConnector:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise _scim_error(
            status.HTTP_401_UNAUTHORIZED,
            "A SCIM bearer token is required",
            headers={"WWW-Authenticate": "Bearer"},
        )
    token = authorization[7:].strip()
    if not token:
        raise _scim_error(
            status.HTTP_401_UNAUTHORIZED,
            "A SCIM bearer token is required",
            headers={"WWW-Authenticate": "Bearer"},
        )
    connector = db.scalar(
        select(IdentityProvisioningConnector).where(
            IdentityProvisioningConnector.token_hash
            == hash_connector_token(token),
        )
    )
    if connector is None:
        raise _scim_error(
            status.HTTP_401_UNAUTHORIZED,
            "Invalid SCIM bearer token",
            headers={"WWW-Authenticate": "Bearer"},
        )
    if connector.status != "ACTIVE":
        raise _scim_error(
            status.HTTP_403_FORBIDDEN,
            f"SCIM connector is {connector.status.lower()}",
        )
    tenant = db.get(Tenant, connector.tenant_id)
    if tenant is None or tenant.status.lower() != "active":
        raise _scim_error(
            status.HTTP_403_FORBIDDEN,
            "Connector tenant is not active",
        )
    remote_ip = request.client.host if request.client else None
    if not connector_allows_ip(connector, remote_ip):
        raise _scim_error(
            status.HTTP_403_FORBIDDEN,
            "Source IP is outside the connector allowlist",
        )
    return connector


def _get_identity(
    db: Session,
    connector: IdentityProvisioningConnector,
    resource_id: str,
) -> ProvisionedIdentity:
    identity = db.scalar(
        select(ProvisionedIdentity).where(
            ProvisionedIdentity.connector_id == connector.id,
            ProvisionedIdentity.id == resource_id,
        )
    )
    if identity is None:
        raise _scim_error(status.HTTP_404_NOT_FOUND, "User not found")
    return identity


def _get_group(
    db: Session,
    connector: IdentityProvisioningConnector,
    resource_id: str,
) -> ProvisionedGroup:
    group = db.scalar(
        select(ProvisionedGroup).where(
            ProvisionedGroup.connector_id == connector.id,
            ProvisionedGroup.id == resource_id,
        )
    )
    if group is None or not group.is_active:
        raise _scim_error(status.HTTP_404_NOT_FOUND, "Group not found")
    return group


EventCallback = Callable[
    [IdentityProvisioningEvent],
    tuple[dict[str, Any], str | None],
]


def _record_failed_event_after_rollback(
    db: Session,
    *,
    connector_id: str,
    external_event_id: str,
    resource_type: str,
    operation: str,
    external_id: str | None,
    payload: dict[str, Any],
    error_code: str,
    error_message: str,
    retryable: bool,
) -> None:
    connector = db.get(IdentityProvisioningConnector, connector_id)
    if connector is None:
        return
    try:
        event, replay = begin_provisioning_event(
            db,
            connector=connector,
            external_event_id=external_event_id,
            resource_type=resource_type,
            operation=operation,
            external_id=external_id,
            payload=payload,
        )
        if replay is None:
            mark_event_failed(
                event,
                connector,
                error_code=error_code,
                error_message=error_message,
                retryable=retryable,
            )
            db.commit()
    except Exception:
        db.rollback()


def _run_event(
    db: Session,
    *,
    connector: IdentityProvisioningConnector,
    request: Request,
    resource_type: str,
    operation: str,
    external_id: str | None,
    wrapper: dict[str, Any],
    callback: EventCallback,
) -> tuple[dict[str, Any], bool]:
    external_event_id = _request_id(request, wrapper)
    connector_id = connector.id
    try:
        event, replay = begin_provisioning_event(
            db,
            connector=connector,
            external_event_id=external_event_id,
            resource_type=resource_type,
            operation=operation,
            external_id=external_id,
            payload=wrapper,
        )
        if replay is not None:
            return replay, True
        with db.begin_nested():
            response, applied_user_id = callback(event)
        mark_event_applied(
            event,
            connector,
            response=response,
            applied_user_id=applied_user_id,
        )
        db.commit()
        return response, False
    except ScimProvisioningError as exc:
        if "event" in locals():
            mark_event_failed(
                event,
                connector,
                error_code=exc.scim_type or type(exc).__name__,
                error_message=exc.detail,
                retryable=exc.retryable,
            )
            db.commit()
        raise _scim_error(
            exc.status_code,
            exc.detail,
            scim_type=exc.scim_type,
        ) from exc
    except IntegrityError as exc:
        db.rollback()
        _record_failed_event_after_rollback(
            db,
            connector_id=connector_id,
            external_event_id=external_event_id,
            resource_type=resource_type,
            operation=operation,
            external_id=external_id,
            payload=wrapper,
            error_code="INTEGRITY_ERROR",
            error_message="A uniqueness or referential constraint rejected the request",
            retryable=False,
        )
        raise _scim_error(
            status.HTTP_409_CONFLICT,
            "A unique identity or group attribute is already in use",
            scim_type="uniqueness",
        ) from exc
    except HTTPException:
        db.rollback()
        raise
    except Exception as exc:
        db.rollback()
        logger.exception(
            "Unexpected SCIM provisioning failure",
            extra={
                "connector_id": connector_id,
                "resource_type": resource_type,
                "operation": operation,
                "external_event_id": external_event_id,
            },
        )
        _record_failed_event_after_rollback(
            db,
            connector_id=connector_id,
            external_event_id=external_event_id,
            resource_type=resource_type,
            operation=operation,
            external_id=external_id,
            payload=wrapper,
            error_code=type(exc).__name__,
            error_message="Unexpected provisioning failure",
            retryable=True,
        )
        raise _scim_error(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "Provisioning service is temporarily unavailable",
        ) from exc


@router.get("/ServiceProviderConfig")
def service_provider_config(
    _: IdentityProvisioningConnector = Depends(get_scim_connector),
) -> dict[str, Any]:
    return {
        "schemas": [
            "urn:ietf:params:scim:schemas:core:2.0:ServiceProviderConfig"
        ],
        "documentationUri": "https://www.rfc-editor.org/rfc/rfc7644",
        "patch": {"supported": True},
        "bulk": {"supported": False, "maxOperations": 0, "maxPayloadSize": 0},
        "filter": {"supported": True, "maxResults": 200},
        "changePassword": {"supported": False},
        "sort": {"supported": False},
        "etag": {"supported": True},
        "authenticationSchemes": [
            {
                "type": "oauthbearertoken",
                "name": "Bearer Token",
                "description": "Tenant-scoped rotating SCIM bearer token",
                "specUri": "https://www.rfc-editor.org/rfc/rfc6750",
                "primary": True,
            }
        ],
    }


@router.get("/ResourceTypes")
def resource_types(
    request: Request,
    _: IdentityProvisioningConnector = Depends(get_scim_connector),
) -> dict[str, Any]:
    base = _base_url(request)
    resources = _resource_type_resources(base)
    return {
        "schemas": [SCIM_LIST_RESPONSE],
        "totalResults": len(resources),
        "startIndex": 1,
        "itemsPerPage": len(resources),
        "Resources": resources,
    }


@router.get("/ResourceTypes/{resource_type}")
def get_resource_type(
    resource_type: str,
    request: Request,
    _: IdentityProvisioningConnector = Depends(get_scim_connector),
) -> dict[str, Any]:
    resource = next(
        (
            item
            for item in _resource_type_resources(_base_url(request))
            if item["id"].lower() == resource_type.lower()
        ),
        None,
    )
    if resource is None:
        raise _scim_error(
            status.HTTP_404_NOT_FOUND,
            "Resource type not found",
        )
    return resource


@router.get("/Schemas")
def schemas(
    _: IdentityProvisioningConnector = Depends(get_scim_connector),
) -> dict[str, Any]:
    resources = _schema_resources()
    return {
        "schemas": [SCIM_LIST_RESPONSE],
        "totalResults": len(resources),
        "startIndex": 1,
        "itemsPerPage": len(resources),
        "Resources": resources,
    }


@router.get("/Schemas/{schema_id}")
def get_schema(
    schema_id: str,
    _: IdentityProvisioningConnector = Depends(get_scim_connector),
) -> dict[str, Any]:
    resource = next(
        (item for item in _schema_resources() if item["id"] == schema_id),
        None,
    )
    if resource is None:
        raise _scim_error(status.HTTP_404_NOT_FOUND, "Schema not found")
    return resource


@router.get("/Users")
def list_users(
    request: Request,
    filter_value: str | None = Query(default=None, alias="filter"),
    start_index: int = Query(default=1, alias="startIndex", ge=1),
    count: int = Query(default=100, ge=1, le=200),
    connector: IdentityProvisioningConnector = Depends(get_scim_connector),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    statement = (
        select(ProvisionedIdentity)
        .join(User, User.id == ProvisionedIdentity.user_id)
        .where(ProvisionedIdentity.connector_id == connector.id)
    )
    parsed_filter = parse_scim_filter(filter_value)
    if parsed_filter:
        attribute, value = parsed_filter
        normalized = attribute.lower()
        if normalized == "username":
            statement = statement.where(func.lower(User.email) == str(value).lower())
        elif normalized == "externalid":
            statement = statement.where(ProvisionedIdentity.external_id == value)
        elif normalized == "id":
            statement = statement.where(ProvisionedIdentity.id == value)
        elif normalized == "active":
            statement = statement.where(
                User.is_active.is_(bool(value)),
                (
                    ProvisionedIdentity.lifecycle_state == "ACTIVE"
                    if value
                    else ProvisionedIdentity.lifecycle_state != "ACTIVE"
                ),
            )
    total = int(
        db.scalar(select(func.count()).select_from(statement.subquery())) or 0
    )
    identities = db.scalars(
        statement
        .order_by(ProvisionedIdentity.created_at.asc())
        .offset(start_index - 1)
        .limit(count)
    ).all()
    resources = [
        scim_user_resource(db, item, base_url=_base_url(request))
        for item in identities
    ]
    return {
        "schemas": [SCIM_LIST_RESPONSE],
        "totalResults": total,
        "startIndex": start_index,
        "itemsPerPage": len(resources),
        "Resources": resources,
    }


@router.post("/Users", status_code=status.HTTP_201_CREATED)
def create_user(
    payload: dict[str, Any],
    request: Request,
    response: Response,
    connector: IdentityProvisioningConnector = Depends(get_scim_connector),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    wrapper = {"operation": "CREATE", "resource_id": None, "body": payload}

    def apply(event: IdentityProvisioningEvent) -> tuple[dict[str, Any], str | None]:
        identity, resource, _ = upsert_scim_user(
            db,
            connector=connector,
            payload=payload,
            base_url=_base_url(request),
            replace=False,
            provisioning_event_id=event.id,
        )
        return resource, identity.user_id

    resource, replayed = _run_event(
        db,
        connector=connector,
        request=request,
        resource_type="User",
        operation="CREATE",
        external_id=str(payload.get("externalId") or "") or None,
        wrapper=wrapper,
        callback=apply,
    )
    response.headers["Location"] = str(resource.get("meta", {}).get("location", ""))
    response.headers["ETag"] = str(resource.get("meta", {}).get("version", ""))
    if replayed:
        response.status_code = status.HTTP_200_OK
    return resource


@router.get("/Users/{resource_id}")
def get_user(
    resource_id: str,
    request: Request,
    response: Response,
    connector: IdentityProvisioningConnector = Depends(get_scim_connector),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    identity = _get_identity(db, connector, resource_id)
    resource = scim_user_resource(db, identity, base_url=_base_url(request))
    response.headers["ETag"] = f'W/"{identity.scim_version}"'
    return resource


@router.put("/Users/{resource_id}")
def replace_user(
    resource_id: str,
    payload: dict[str, Any],
    request: Request,
    response: Response,
    connector: IdentityProvisioningConnector = Depends(get_scim_connector),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    identity = _get_identity(db, connector, resource_id)
    _if_match(request, identity.scim_version)
    supplied_external = payload.get("externalId")
    if supplied_external is not None and str(supplied_external) != identity.external_id:
        raise _scim_error(
            status.HTTP_400_BAD_REQUEST,
            "externalId is immutable",
            scim_type="mutability",
        )
    payload["externalId"] = identity.external_id
    wrapper = {
        "operation": "REPLACE",
        "resource_id": resource_id,
        "body": payload,
    }

    def apply(event: IdentityProvisioningEvent) -> tuple[dict[str, Any], str | None]:
        updated, resource, _ = upsert_scim_user(
            db,
            connector=connector,
            payload=payload,
            base_url=_base_url(request),
            replace=True,
            provisioning_event_id=event.id,
        )
        return resource, updated.user_id

    resource, _ = _run_event(
        db,
        connector=connector,
        request=request,
        resource_type="User",
        operation="REPLACE",
        external_id=identity.external_id,
        wrapper=wrapper,
        callback=apply,
    )
    response.headers["ETag"] = str(resource.get("meta", {}).get("version", ""))
    return resource


@router.patch("/Users/{resource_id}")
def patch_user(
    resource_id: str,
    payload: dict[str, Any],
    request: Request,
    response: Response,
    connector: IdentityProvisioningConnector = Depends(get_scim_connector),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    identity = _get_identity(db, connector, resource_id)
    _if_match(request, identity.scim_version)
    operations = payload.get("Operations")
    if not isinstance(operations, list):
        raise _scim_error(
            status.HTTP_400_BAD_REQUEST,
            "Operations must be an array",
            scim_type="invalidSyntax",
        )
    current = scim_user_resource(db, identity, base_url=_base_url(request))
    try:
        patched = apply_user_patch(current, operations)
    except ScimProvisioningError as exc:
        raise _scim_error(
            exc.status_code,
            exc.detail,
            scim_type=exc.scim_type,
        ) from exc
    if patched.get("externalId") != identity.external_id:
        raise _scim_error(
            status.HTTP_400_BAD_REQUEST,
            "externalId is immutable",
            scim_type="mutability",
        )
    wrapper = {
        "operation": "PATCH",
        "resource_id": resource_id,
        "body": payload,
    }

    def apply(event: IdentityProvisioningEvent) -> tuple[dict[str, Any], str | None]:
        updated, resource, _ = upsert_scim_user(
            db,
            connector=connector,
            payload=patched,
            base_url=_base_url(request),
            replace=False,
            provisioning_event_id=event.id,
        )
        return resource, updated.user_id

    resource, _ = _run_event(
        db,
        connector=connector,
        request=request,
        resource_type="User",
        operation="PATCH",
        external_id=identity.external_id,
        wrapper=wrapper,
        callback=apply,
    )
    response.headers["ETag"] = str(resource.get("meta", {}).get("version", ""))
    return resource


@router.delete("/Users/{resource_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_user(
    resource_id: str,
    request: Request,
    connector: IdentityProvisioningConnector = Depends(get_scim_connector),
    db: Session = Depends(get_db),
) -> Response:
    identity = _get_identity(db, connector, resource_id)
    _if_match(request, identity.scim_version)
    wrapper = {
        "operation": "DELETE",
        "resource_id": resource_id,
        "body": {},
    }

    def apply(event: IdentityProvisioningEvent) -> tuple[dict[str, Any], str | None]:
        deactivate_scim_user(
            db,
            connector=connector,
            identity=identity,
            provisioning_event_id=event.id,
        )
        return {"deleted": True, "id": identity.id}, identity.user_id

    _run_event(
        db,
        connector=connector,
        request=request,
        resource_type="User",
        operation="DELETE",
        external_id=identity.external_id,
        wrapper=wrapper,
        callback=apply,
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


def _parse_group_filter(filter_value: str | None) -> tuple[str, str] | None:
    if not filter_value:
        return None
    parts = filter_value.strip().split(maxsplit=2)
    if (
        len(parts) != 3
        or parts[0].lower() not in GROUP_FILTER_ATTRIBUTES
        or parts[1].lower() != "eq"
        or len(parts[2]) < 2
        or not (parts[2].startswith('"') and parts[2].endswith('"'))
    ):
        raise _scim_error(
            status.HTTP_400_BAD_REQUEST,
            "Supported group filters are id, externalId, or displayName with eq",
            scim_type="invalidFilter",
        )
    return parts[0].lower(), parts[2][1:-1]


@router.get("/Groups")
def list_groups(
    request: Request,
    filter_value: str | None = Query(default=None, alias="filter"),
    start_index: int = Query(default=1, alias="startIndex", ge=1),
    count: int = Query(default=100, ge=1, le=200),
    connector: IdentityProvisioningConnector = Depends(get_scim_connector),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    statement = select(ProvisionedGroup).where(
        ProvisionedGroup.connector_id == connector.id,
        ProvisionedGroup.is_active.is_(True),
    )
    parsed_filter = _parse_group_filter(filter_value)
    if parsed_filter:
        attribute, value = parsed_filter
        if attribute == "displayname":
            statement = statement.where(
                func.lower(ProvisionedGroup.display_name) == value.lower()
            )
        elif attribute == "externalid":
            statement = statement.where(ProvisionedGroup.external_id == value)
        else:
            statement = statement.where(ProvisionedGroup.id == value)
    total = int(
        db.scalar(select(func.count()).select_from(statement.subquery())) or 0
    )
    groups = db.scalars(
        statement
        .order_by(ProvisionedGroup.created_at.asc())
        .offset(start_index - 1)
        .limit(count)
    ).all()
    resources = [
        scim_group_resource(db, item, base_url=_base_url(request))
        for item in groups
    ]
    return {
        "schemas": [SCIM_LIST_RESPONSE],
        "totalResults": total,
        "startIndex": start_index,
        "itemsPerPage": len(resources),
        "Resources": resources,
    }


@router.post("/Groups", status_code=status.HTTP_201_CREATED)
def create_group(
    payload: dict[str, Any],
    request: Request,
    response: Response,
    connector: IdentityProvisioningConnector = Depends(get_scim_connector),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    wrapper = {"operation": "CREATE", "resource_id": None, "body": payload}

    def apply(event: IdentityProvisioningEvent) -> tuple[dict[str, Any], str | None]:
        _, resource, _ = upsert_scim_group(
            db,
            connector=connector,
            payload=payload,
            base_url=_base_url(request),
            replace=False,
            provisioning_event_id=event.id,
        )
        return resource, None

    resource, replayed = _run_event(
        db,
        connector=connector,
        request=request,
        resource_type="Group",
        operation="CREATE",
        external_id=str(payload.get("externalId") or "") or None,
        wrapper=wrapper,
        callback=apply,
    )
    response.headers["Location"] = str(resource.get("meta", {}).get("location", ""))
    response.headers["ETag"] = str(resource.get("meta", {}).get("version", ""))
    if replayed:
        response.status_code = status.HTTP_200_OK
    return resource


@router.get("/Groups/{resource_id}")
def get_group(
    resource_id: str,
    request: Request,
    response: Response,
    connector: IdentityProvisioningConnector = Depends(get_scim_connector),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    group = _get_group(db, connector, resource_id)
    response.headers["ETag"] = f'W/"{group.scim_version}"'
    return scim_group_resource(db, group, base_url=_base_url(request))


@router.put("/Groups/{resource_id}")
def replace_group(
    resource_id: str,
    payload: dict[str, Any],
    request: Request,
    response: Response,
    connector: IdentityProvisioningConnector = Depends(get_scim_connector),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    group = _get_group(db, connector, resource_id)
    _if_match(request, group.scim_version)
    supplied_external = payload.get("externalId")
    if supplied_external is not None and str(supplied_external) != group.external_id:
        raise _scim_error(
            status.HTTP_400_BAD_REQUEST,
            "externalId is immutable",
            scim_type="mutability",
        )
    payload["externalId"] = group.external_id
    wrapper = {
        "operation": "REPLACE",
        "resource_id": resource_id,
        "body": payload,
    }

    def apply(event: IdentityProvisioningEvent) -> tuple[dict[str, Any], str | None]:
        _, resource, _ = upsert_scim_group(
            db,
            connector=connector,
            payload=payload,
            base_url=_base_url(request),
            replace=True,
            provisioning_event_id=event.id,
        )
        return resource, None

    resource, _ = _run_event(
        db,
        connector=connector,
        request=request,
        resource_type="Group",
        operation="REPLACE",
        external_id=group.external_id,
        wrapper=wrapper,
        callback=apply,
    )
    response.headers["ETag"] = str(resource.get("meta", {}).get("version", ""))
    return resource


@router.patch("/Groups/{resource_id}")
def patch_group(
    resource_id: str,
    payload: dict[str, Any],
    request: Request,
    response: Response,
    connector: IdentityProvisioningConnector = Depends(get_scim_connector),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    group = _get_group(db, connector, resource_id)
    _if_match(request, group.scim_version)
    operations = payload.get("Operations")
    if not isinstance(operations, list):
        raise _scim_error(
            status.HTTP_400_BAD_REQUEST,
            "Operations must be an array",
            scim_type="invalidSyntax",
        )
    wrapper = {
        "operation": "PATCH",
        "resource_id": resource_id,
        "body": payload,
    }

    def apply(event: IdentityProvisioningEvent) -> tuple[dict[str, Any], str | None]:
        apply_group_patch(
            db,
            connector=connector,
            group=group,
            operations=operations,
        )
        return (
            scim_group_resource(db, group, base_url=_base_url(request)),
            None,
        )

    resource, _ = _run_event(
        db,
        connector=connector,
        request=request,
        resource_type="Group",
        operation="PATCH",
        external_id=group.external_id,
        wrapper=wrapper,
        callback=apply,
    )
    response.headers["ETag"] = str(resource.get("meta", {}).get("version", ""))
    return resource


@router.delete("/Groups/{resource_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_group(
    resource_id: str,
    request: Request,
    connector: IdentityProvisioningConnector = Depends(get_scim_connector),
    db: Session = Depends(get_db),
) -> Response:
    group = _get_group(db, connector, resource_id)
    _if_match(request, group.scim_version)
    wrapper = {
        "operation": "DELETE",
        "resource_id": resource_id,
        "body": {},
    }

    def apply(event: IdentityProvisioningEvent) -> tuple[dict[str, Any], str | None]:
        delete_scim_group(
            db,
            connector=connector,
            group=group,
            provisioning_event_id=event.id,
        )
        return {"deleted": True, "id": group.id}, None

    _run_event(
        db,
        connector=connector,
        request=request,
        resource_type="Group",
        operation="DELETE",
        external_id=group.external_id,
        wrapper=wrapper,
        callback=apply,
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)
