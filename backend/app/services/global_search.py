from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import Select, and_, case, func, literal_column, or_, select
from sqlalchemy.orm import Session

from app.api.v1.routes.auth import AuthUserResponse
from app.models.asset import Asset
from app.models.change_request import ChangeRequest
from app.models.knowledge_article import KnowledgeArticle
from app.models.problem import Problem
from app.models.service_request import ServiceRequest
from app.models.ticket import Ticket
from app.models.user import User
from app.services.rbac import has_permission, is_saas_root


SEARCH_ENTITY_TYPES = (
    "ticket",
    "request",
    "knowledge",
    "asset",
    "change",
    "problem",
    "user",
)

ENTITY_PERMISSIONS = {
    "ticket": "tickets.read",
    "request": "requests.read",
    "knowledge": "knowledge.read",
    "asset": "assets.read",
    "change": "changes.read",
    "problem": "problems.read",
    "user": "admin.users.read",
}


@dataclass(frozen=True)
class SearchRecord:
    entity_type: str
    id: str
    tenant_id: str | None
    identifier: str
    title: str
    subtitle: str | None
    status: str | None
    href: str
    updated_at: datetime
    score: int
    matched_fields: list[str]


def escape_like(value: str) -> str:
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def normalize_entity_types(values: list[str] | None) -> list[str]:
    if not values:
        return list(SEARCH_ENTITY_TYPES)
    normalized: list[str] = []
    for item in values:
        candidate = item.strip().lower()
        if candidate not in SEARCH_ENTITY_TYPES:
            raise ValueError(f"Unsupported search entity type: {candidate}")
        if candidate not in normalized:
            normalized.append(candidate)
    return normalized


def _scope_tenant(statement: Select[Any], model: Any, user: AuthUserResponse):
    if is_saas_root(user):
        return statement
    return statement.where(model.tenant_id == user.tenant_id)


def _search_document(*columns: Any):
    empty = literal_column("''")
    separator = literal_column("' '")
    document = func.coalesce(columns[0], empty)
    for column in columns[1:]:
        document = document + separator + func.coalesce(column, empty)
    return document


def _search_predicate(
    db: Session,
    query: str,
    pattern: str,
    *columns: Any,
):
    if db.get_bind().dialect.name == "postgresql":
        return _search_document(*columns).ilike(pattern, escape="\\")
    return or_(*(column.ilike(pattern, escape="\\") for column in columns))


def _ordered(
    statement: Select[Any],
    *,
    identifier: Any,
    title: Any,
    normalized_query: str,
    updated_at: Any,
):
    prefix_pattern = f"{escape_like(normalized_query)}%"
    priority = case(
        (func.lower(identifier) == normalized_query, 0),
        (func.lower(identifier).like(prefix_pattern, escape="\\"), 1),
        (func.lower(title).like(prefix_pattern, escape="\\"), 2),
        else_=3,
    )
    return statement.order_by(priority.asc(), updated_at.desc())


def _match_details(
    query: str,
    *,
    identifier: str,
    title: str,
    searchable: dict[str, str | None],
) -> tuple[int, list[str]]:
    normalized = query.casefold()
    identifier_value = identifier.casefold()
    title_value = title.casefold()
    matched = [
        key
        for key, value in searchable.items()
        if value and normalized in value.casefold()
    ]
    if identifier_value == normalized:
        score = 100
    elif identifier_value.startswith(normalized):
        score = 90
    elif title_value.startswith(normalized):
        score = 80
    elif normalized in identifier_value:
        score = 70
    elif normalized in title_value:
        score = 60
    else:
        score = 40
    return score, matched


def _bounded_rows(
    db: Session,
    statement: Select[Any],
    *,
    identifier: Any,
    title: Any,
    query: str,
    updated_at: Any,
    per_type_limit: int,
) -> list[Any]:
    ordered = _ordered(
        statement,
        identifier=identifier,
        title=title,
        normalized_query=query.casefold(),
        updated_at=updated_at,
    )
    candidate_limit = min(100, max(25, per_type_limit * 5))
    return list(db.scalars(ordered.limit(candidate_limit)).all())


def _ticket_records(
    db: Session,
    user: AuthUserResponse,
    query: str,
    pattern: str,
    limit: int,
) -> list[SearchRecord]:
    statement = _scope_tenant(select(Ticket), Ticket, user)
    if user.role == "requester":
        statement = statement.where(
            func.lower(Ticket.requester_email) == user.email.lower()
        )
    elif user.role == "it_agent":
        statement = statement.where(
            or_(
                Ticket.assignee_id == user.id,
                func.lower(func.coalesce(Ticket.assignee_name, ""))
                == user.full_name.lower(),
                and_(
                    Ticket.assignee_id.is_(None),
                    or_(
                        Ticket.assignee_name.is_(None),
                        func.length(func.trim(Ticket.assignee_name)) == 0,
                    ),
                ),
            )
        )
    statement = statement.where(
        _search_predicate(
            db,
            query,
            pattern,
            Ticket.ticket_number,
            Ticket.title,
            Ticket.description,
            Ticket.category,
        )
    )
    rows = _bounded_rows(
        db,
        statement,
        identifier=Ticket.ticket_number,
        title=Ticket.title,
        query=query,
        updated_at=Ticket.updated_at,
        per_type_limit=limit,
    )
    return [
        _record(
            "ticket",
            row,
            row.ticket_number or row.id,
            row.title,
            f"{row.priority} · {row.category}",
            row.status,
            f"/tickets?ticket={row.id}",
            query,
            {
                "identifier": row.ticket_number,
                "title": row.title,
                "description": row.description,
                "category": row.category,
            },
        )
        for row in rows
    ]


def _request_records(
    db: Session,
    user: AuthUserResponse,
    query: str,
    pattern: str,
    limit: int,
) -> list[SearchRecord]:
    statement = _scope_tenant(select(ServiceRequest), ServiceRequest, user)
    if user.role == "requester":
        statement = statement.where(
            or_(
                ServiceRequest.requester_id == user.id,
                func.lower(ServiceRequest.requester_email) == user.email.lower(),
            )
        )
    statement = statement.where(
        _search_predicate(
            db,
            query,
            pattern,
            ServiceRequest.request_number,
            ServiceRequest.title,
            ServiceRequest.description,
        )
    )
    rows = _bounded_rows(
        db,
        statement,
        identifier=ServiceRequest.request_number,
        title=ServiceRequest.title,
        query=query,
        updated_at=ServiceRequest.updated_at,
        per_type_limit=limit,
    )
    return [
        _record(
            "request",
            row,
            row.request_number,
            row.title,
            row.priority,
            row.status,
            f"/requests?request_id={row.id}",
            query,
            {
                "identifier": row.request_number,
                "title": row.title,
                "description": row.description,
            },
        )
        for row in rows
    ]


def _knowledge_records(
    db: Session,
    user: AuthUserResponse,
    query: str,
    pattern: str,
    limit: int,
) -> list[SearchRecord]:
    statement = select(KnowledgeArticle)
    if not is_saas_root(user):
        statement = statement.where(
            or_(
                KnowledgeArticle.tenant_id == user.tenant_id,
                KnowledgeArticle.tenant_id.is_(None),
            )
        )
    if not (
        has_permission(user, "knowledge.update")
        or has_permission(user, "knowledge.publish")
    ):
        statement = statement.where(
            KnowledgeArticle.status == "published",
            KnowledgeArticle.visibility.in_(("public", "internal")),
        )
    statement = statement.where(
        _search_predicate(
            db,
            query,
            pattern,
            KnowledgeArticle.article_number,
            KnowledgeArticle.title,
            KnowledgeArticle.summary,
            KnowledgeArticle.content,
            KnowledgeArticle.tags,
        )
    )
    rows = _bounded_rows(
        db,
        statement,
        identifier=KnowledgeArticle.article_number,
        title=KnowledgeArticle.title,
        query=query,
        updated_at=KnowledgeArticle.updated_at,
        per_type_limit=limit,
    )
    return [
        _record(
            "knowledge",
            row,
            row.article_number,
            row.title,
            row.visibility,
            row.status,
            f"/knowledge?article_id={row.id}",
            query,
            {
                "identifier": row.article_number,
                "title": row.title,
                "summary": row.summary,
                "content": row.content,
                "tags": row.tags,
            },
        )
        for row in rows
    ]


def _asset_records(
    db: Session,
    user: AuthUserResponse,
    query: str,
    pattern: str,
    limit: int,
) -> list[SearchRecord]:
    statement = _scope_tenant(select(Asset), Asset, user).where(
        _search_predicate(
            db,
            query,
            pattern,
            Asset.asset_tag,
            Asset.name,
            Asset.serial_number,
            Asset.inventory_number,
            Asset.description,
        )
    )
    rows = _bounded_rows(
        db,
        statement,
        identifier=Asset.asset_tag,
        title=Asset.name,
        query=query,
        updated_at=Asset.updated_at,
        per_type_limit=limit,
    )
    return [
        _record(
            "asset",
            row,
            row.asset_tag,
            row.name,
            f"{row.asset_type} · {row.location}",
            row.status,
            f"/assets?asset={row.id}",
            query,
            {
                "identifier": row.asset_tag,
                "title": row.name,
                "serial_number": row.serial_number,
                "inventory_number": row.inventory_number,
                "description": row.description,
            },
        )
        for row in rows
    ]


def _change_records(
    db: Session,
    user: AuthUserResponse,
    query: str,
    pattern: str,
    limit: int,
) -> list[SearchRecord]:
    statement = _scope_tenant(select(ChangeRequest), ChangeRequest, user).where(
        _search_predicate(
            db,
            query,
            pattern,
            ChangeRequest.change_number,
            ChangeRequest.title,
            ChangeRequest.description,
            ChangeRequest.service_name,
        )
    )
    rows = _bounded_rows(
        db,
        statement,
        identifier=ChangeRequest.change_number,
        title=ChangeRequest.title,
        query=query,
        updated_at=ChangeRequest.updated_at,
        per_type_limit=limit,
    )
    return [
        _record(
            "change",
            row,
            row.change_number,
            row.title,
            row.change_type,
            row.status,
            f"/changes?change={row.id}",
            query,
            {
                "identifier": row.change_number,
                "title": row.title,
                "description": row.description,
                "service": row.service_name,
            },
        )
        for row in rows
    ]


def _problem_records(
    db: Session,
    user: AuthUserResponse,
    query: str,
    pattern: str,
    limit: int,
) -> list[SearchRecord]:
    statement = _scope_tenant(select(Problem), Problem, user).where(
        _search_predicate(
            db,
            query,
            pattern,
            Problem.problem_number,
            Problem.title,
            Problem.description,
            Problem.symptoms,
            Problem.root_cause,
            Problem.workaround,
        )
    )
    rows = _bounded_rows(
        db,
        statement,
        identifier=Problem.problem_number,
        title=Problem.title,
        query=query,
        updated_at=Problem.updated_at,
        per_type_limit=limit,
    )
    return [
        _record(
            "problem",
            row,
            row.problem_number,
            row.title,
            row.priority,
            row.status,
            f"/problems?problem={row.id}",
            query,
            {
                "identifier": row.problem_number,
                "title": row.title,
                "description": row.description,
                "symptoms": row.symptoms,
                "root_cause": row.root_cause,
                "workaround": row.workaround,
            },
        )
        for row in rows
    ]


def _user_records(
    db: Session,
    user: AuthUserResponse,
    query: str,
    pattern: str,
    limit: int,
) -> list[SearchRecord]:
    statement = _scope_tenant(select(User), User, user).where(
        _search_predicate(
            db,
            query,
            pattern,
            User.email,
            User.full_name,
            User.department,
            User.position,
            User.employee_number,
        )
    )
    rows = _bounded_rows(
        db,
        statement,
        identifier=User.email,
        title=User.full_name,
        query=query,
        updated_at=User.updated_at,
        per_type_limit=limit,
    )
    return [
        _record(
            "user",
            row,
            row.email,
            row.full_name,
            row.department or row.position,
            "active" if row.is_active else "inactive",
            f"/admin?user={row.id}",
            query,
            {
                "identifier": row.email,
                "title": row.full_name,
                "department": row.department,
                "position": row.position,
                "employee_number": row.employee_number,
            },
        )
        for row in rows
    ]


def _record(
    entity_type: str,
    row: Any,
    identifier: str,
    title: str,
    subtitle: str | None,
    status: str | None,
    href: str,
    query: str,
    searchable: dict[str, str | None],
) -> SearchRecord:
    score, matched_fields = _match_details(
        query,
        identifier=identifier,
        title=title,
        searchable=searchable,
    )
    return SearchRecord(
        entity_type=entity_type,
        id=row.id,
        tenant_id=row.tenant_id,
        identifier=identifier,
        title=title,
        subtitle=subtitle,
        status=status,
        href=href,
        updated_at=row.updated_at,
        score=score,
        matched_fields=matched_fields,
    )


SEARCH_HANDLERS: dict[
    str,
    Callable[
        [Session, AuthUserResponse, str, str, int],
        list[SearchRecord],
    ],
] = {
    "ticket": _ticket_records,
    "request": _request_records,
    "knowledge": _knowledge_records,
    "asset": _asset_records,
    "change": _change_records,
    "problem": _problem_records,
    "user": _user_records,
}


def run_global_search(
    db: Session,
    user: AuthUserResponse,
    *,
    query: str,
    entity_types: list[str],
    per_type_limit: int,
    total_limit: int,
) -> tuple[list[SearchRecord], dict[str, int]]:
    pattern = f"%{escape_like(query)}%"
    records: list[SearchRecord] = []
    counts: dict[str, int] = {}
    for entity_type in entity_types:
        permission = ENTITY_PERMISSIONS[entity_type]
        if not has_permission(user, permission):
            continue
        entity_records = SEARCH_HANDLERS[entity_type](
            db,
            user,
            query,
            pattern,
            per_type_limit,
        )
        entity_records.sort(
            key=lambda item: (
                -item.score,
                -item.updated_at.timestamp(),
                item.identifier,
            )
        )
        selected = entity_records[:per_type_limit]
        counts[entity_type] = len(selected)
        records.extend(selected)
    records.sort(
        key=lambda item: (
            -item.score,
            -item.updated_at.timestamp(),
            item.entity_type,
            item.identifier,
        )
    )
    return records[:total_limit], counts
