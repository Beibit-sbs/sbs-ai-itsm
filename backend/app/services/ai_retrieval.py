from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from datetime import UTC, datetime
import hashlib
import json
import math
import re
import time
import uuid
from typing import Any, Iterable

from sqlalchemy import delete, func, or_, select
from sqlalchemy.orm import Session

from app.api.v1.routes.auth import AuthUserResponse
from app.core.config import Settings
from app.models.ai_retrieval import (
    AiRetrievalChunk,
    AiRetrievalDocument,
    AiRetrievalIngestionRun,
    AiRetrievalQueryLog,
)
from app.models.asset import Asset
from app.models.change_request import ChangeRequest
from app.models.knowledge_article import KnowledgeArticle
from app.models.problem import Problem
from app.models.ticket import Ticket
from app.services.ai.pii import redact_pii
from app.services.rbac import can_read_ticket, has_permission, is_saas_root


RAG_SOURCE_TYPES = ("knowledge", "ticket", "problem", "change", "asset")
SOURCE_PERMISSIONS = {
    "knowledge": "knowledge.read",
    "ticket": "tickets.read",
    "problem": "problems.read",
    "change": "changes.read",
    "asset": "assets.read",
}
_TOKEN_RE = re.compile(r"[0-9A-Za-zА-Яа-яЁё][0-9A-Za-zА-Яа-яЁё_.-]{1,}")
_WHITESPACE_RE = re.compile(r"\s+")
_PROMPT_INJECTION_PATTERNS = (
    re.compile(r"ignore\s+(?:all\s+)?(?:previous|prior|above)\s+instructions", re.I),
    re.compile(r"forget\s+(?:all\s+)?(?:previous|prior)\s+instructions", re.I),
    re.compile(r"(?:reveal|show|print|repeat).{0,40}(?:system|developer)\s+prompt", re.I),
    re.compile(r"(?:system|developer)\s+message\s*:", re.I),
    re.compile(r"игнорируй.{0,40}(?:предыдущ|системн).{0,40}инструкц", re.I),
    re.compile(r"(?:покажи|раскрой|выведи).{0,40}системн.{0,20}(?:промпт|инструкц)", re.I),
)


class RagError(ValueError):
    pass


class RagSafetyError(RagError):
    pass


@dataclass(slots=True)
class SourceRecord:
    tenant_id: str | None
    source_type: str
    source_id: str
    source_key: str
    title: str
    url_path: str
    visibility: str
    permission_code: str
    content: str
    source_updated_at: datetime
    source_version: str
    metadata: dict[str, Any]


def utcnow() -> datetime:
    return datetime.now(UTC)


def canonical_json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def digest_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def json_object(value: str | None) -> dict[str, Any]:
    if not value:
        return {}
    try:
        parsed = json.loads(value)
    except (TypeError, ValueError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def normalize_text(value: str) -> str:
    return _WHITESPACE_RE.sub(" ", (value or "").strip()).lower()


def tokenize(value: str) -> list[str]:
    return [match.group(0).lower() for match in _TOKEN_RE.finditer(value or "")]


def detects_prompt_injection(value: str) -> bool:
    return any(pattern.search(value or "") for pattern in _PROMPT_INJECTION_PATTERNS)


def sparse_embedding(value: str, dimensions: int) -> dict[str, float]:
    tokens = tokenize(value)
    if not tokens:
        return {}
    features: Counter[int] = Counter()
    for token in tokens:
        candidates = [token]
        if len(token) >= 5:
            candidates.extend(token[index : index + 3] for index in range(len(token) - 2))
        for feature in candidates:
            raw = hashlib.blake2b(feature.encode("utf-8"), digest_size=8).digest()
            encoded = int.from_bytes(raw, "big")
            index = encoded % dimensions
            sign = -1 if encoded & (1 << 63) else 1
            features[index] += sign
    norm = math.sqrt(sum(value * value for value in features.values()))
    if norm == 0:
        return {}
    return {
        str(index): round(value / norm, 8)
        for index, value in sorted(features.items())
        if value
    }


def cosine_sparse(left: dict[str, float], right: dict[str, float]) -> float:
    if not left or not right:
        return 0.0
    if len(left) > len(right):
        left, right = right, left
    return sum(value * right.get(index, 0.0) for index, value in left.items())


def chunk_text(value: str, *, maximum: int, overlap: int) -> list[str]:
    normalized = (value or "").strip()
    if not normalized:
        return []
    chunks: list[str] = []
    cursor = 0
    length = len(normalized)
    while cursor < length:
        end = min(length, cursor + maximum)
        if end < length:
            break_at = max(
                normalized.rfind("\n", cursor + maximum // 2, end),
                normalized.rfind(". ", cursor + maximum // 2, end),
                normalized.rfind(" ", cursor + maximum // 2, end),
            )
            if break_at > cursor:
                end = break_at + 1
        candidate = normalized[cursor:end].strip()
        if candidate:
            chunks.append(candidate)
        if end >= length:
            break
        next_cursor = max(cursor + 1, end - overlap)
        cursor = next_cursor
    return chunks


def _timestamp(value: datetime | None) -> datetime:
    if value is None:
        return datetime(1970, 1, 1, tzinfo=UTC)
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def _record_version(updated_at: datetime, version: object | None = None) -> str:
    stamp = _timestamp(updated_at).isoformat()
    return f"{stamp}:{version}" if version is not None else stamp


def _content(*sections: tuple[str, object | None]) -> str:
    return "\n\n".join(
        f"{label}:\n{str(value).strip()}"
        for label, value in sections
        if value is not None and str(value).strip()
    )


def _knowledge_sources(db: Session, tenant_id: str) -> list[SourceRecord]:
    items = db.scalars(
        select(KnowledgeArticle).where(
            KnowledgeArticle.status == "published",
            or_(
                KnowledgeArticle.tenant_id == tenant_id,
                KnowledgeArticle.tenant_id.is_(None),
            ),
        )
    ).all()
    return [
        SourceRecord(
            tenant_id=item.tenant_id,
            source_type="knowledge",
            source_id=item.id,
            source_key=item.article_number,
            title=item.title,
            url_path=f"/knowledge?article={item.id}",
            visibility=item.visibility
            if item.visibility in {"public", "internal", "restricted"}
            else "restricted",
            permission_code="knowledge.read",
            content=_content(
                ("Заголовок", item.title),
                ("Краткое описание", item.summary),
                ("Содержание", item.content),
                ("Теги", item.tags),
            ),
            source_updated_at=item.updated_at or item.created_at,
            source_version=_record_version(item.updated_at or item.created_at),
            metadata={
                "article_number": item.article_number,
                "ticket_category": item.ticket_category,
                "asset_type": item.asset_type,
            },
        )
        for item in items
    ]


def _ticket_sources(db: Session, tenant_id: str) -> list[SourceRecord]:
    items = db.scalars(
        select(Ticket).where(
            Ticket.tenant_id == tenant_id,
            Ticket.status.in_(("RESOLVED", "CLOSED", "resolved", "closed")),
        )
    ).all()
    return [
        SourceRecord(
            tenant_id=tenant_id,
            source_type="ticket",
            source_id=item.id,
            source_key=item.ticket_number or item.id,
            title=item.title,
            url_path=f"/tickets?ticket={item.id}",
            visibility="restricted",
            permission_code="tickets.read",
            content=_content(
                ("Инцидент", item.title),
                ("Описание", item.description),
                ("Категория", item.category),
                ("Приоритет", item.priority),
                ("Статус", item.status),
                ("Причина повторного открытия", item.reopen_reason),
            ),
            source_updated_at=item.updated_at or item.created_at,
            source_version=_record_version(item.updated_at or item.created_at),
            metadata={
                "ticket_number": item.ticket_number,
                "category": item.category,
                "priority": item.priority,
                "status": item.status,
            },
        )
        for item in items
    ]


def _problem_sources(db: Session, tenant_id: str) -> list[SourceRecord]:
    items = db.scalars(
        select(Problem).where(
            Problem.tenant_id == tenant_id,
            or_(
                Problem.known_error_published_at.is_not(None),
                Problem.status.in_(("KNOWN_ERROR", "RESOLVED", "CLOSED")),
            ),
        )
    ).all()
    return [
        SourceRecord(
            tenant_id=tenant_id,
            source_type="problem",
            source_id=item.id,
            source_key=item.problem_number,
            title=item.known_error_title or item.title,
            url_path=f"/problems?problem={item.id}",
            visibility="internal",
            permission_code="problems.read",
            content=_content(
                ("Проблема", item.title),
                ("Описание", item.description),
                ("Симптомы", item.symptoms),
                ("Корневая причина", item.root_cause),
                ("Обходное решение", item.workaround),
                ("Решение", item.resolution_summary),
                ("Проверка", item.validation_summary),
                ("Сервис", item.service_name),
            ),
            source_updated_at=item.updated_at or item.created_at,
            source_version=_record_version(item.updated_at or item.created_at, item.version),
            metadata={
                "problem_number": item.problem_number,
                "status": item.status,
                "priority": item.priority,
                "known_error": bool(item.known_error_published_at),
            },
        )
        for item in items
    ]


def _change_sources(db: Session, tenant_id: str) -> list[SourceRecord]:
    items = db.scalars(
        select(ChangeRequest).where(
            ChangeRequest.tenant_id == tenant_id,
            ChangeRequest.status.in_(("COMPLETED", "ROLLED_BACK", "FAILED")),
        )
    ).all()
    return [
        SourceRecord(
            tenant_id=tenant_id,
            source_type="change",
            source_id=item.id,
            source_key=item.change_number,
            title=item.title,
            url_path=f"/changes?change={item.id}",
            visibility="internal",
            permission_code="changes.read",
            content=_content(
                ("Изменение", item.title),
                ("Описание", item.description),
                ("Обоснование", item.business_justification),
                ("План реализации", item.implementation_plan),
                ("План проверки", item.validation_plan),
                ("План отката", item.rollback_plan),
                ("Причина неудачи", item.failure_reason),
                ("Post implementation review", item.post_implementation_review),
                ("Результат", item.outcome),
                ("Сервис", item.service_name),
            ),
            source_updated_at=item.updated_at or item.created_at,
            source_version=_record_version(item.updated_at or item.created_at, item.version),
            metadata={
                "change_number": item.change_number,
                "status": item.status,
                "change_type": item.change_type,
                "risk_level": item.risk_level,
                "environment": item.environment,
            },
        )
        for item in items
    ]


def _asset_sources(db: Session, tenant_id: str) -> list[SourceRecord]:
    items = db.scalars(
        select(Asset).where(
            Asset.tenant_id == tenant_id,
            func.lower(func.coalesce(Asset.verification_status, "")).in_(
                ("verified", "certified")
            ),
            func.upper(func.coalesce(Asset.lifecycle_status, "ACTIVE")) == "ACTIVE",
        )
    ).all()
    return [
        SourceRecord(
            tenant_id=tenant_id,
            source_type="asset",
            source_id=item.id,
            source_key=item.asset_tag,
            title=item.name,
            url_path=f"/assets?asset={item.id}",
            visibility="restricted",
            permission_code="assets.read",
            content=_content(
                ("CI / Актив", item.name),
                ("Тип", item.asset_type),
                ("Класс CI", item.ci_class_name),
                ("Производитель", item.manufacturer),
                ("Модель", item.model),
                ("Статус", item.status),
                ("Критичность", item.criticality),
                ("Среда", item.environment),
                ("Сервисная группа", item.support_group),
                ("Расположение", item.location_label or item.location),
                ("Описание", item.description),
            ),
            source_updated_at=item.updated_at or item.created_at,
            source_version=_record_version(
                item.updated_at or item.created_at,
                item.ci_version,
            ),
            metadata={
                "asset_tag": item.asset_tag,
                "asset_type": item.asset_type,
                "ci_class_code": item.ci_class_code,
                "criticality": item.criticality,
                "environment": item.environment,
                "verification_status": item.verification_status,
            },
        )
        for item in items
    ]


_SOURCE_LOADERS = {
    "knowledge": _knowledge_sources,
    "ticket": _ticket_sources,
    "problem": _problem_sources,
    "change": _change_sources,
    "asset": _asset_sources,
}


def _replace_chunks(
    db: Session,
    document: AiRetrievalDocument,
    content: str,
    settings: Settings,
) -> None:
    db.execute(delete(AiRetrievalChunk).where(AiRetrievalChunk.document_id == document.id))
    for ordinal, text in enumerate(
        chunk_text(
            content,
            maximum=settings.ai_rag_chunk_chars,
            overlap=settings.ai_rag_chunk_overlap_chars,
        )
    ):
        normalized = normalize_text(text)
        db.add(
            AiRetrievalChunk(
                id=str(uuid.uuid4()),
                document_id=document.id,
                ordinal=ordinal,
                content_text=text,
                content_sha256=digest_text(text),
                search_text=normalized,
                embedding_json=canonical_json(
                    sparse_embedding(text, settings.ai_rag_embedding_dimensions)
                ),
                token_count=len(tokenize(text)),
            )
        )


def synchronize_retrieval_index(
    db: Session,
    *,
    tenant_id: str,
    source_types: set[str],
    actor_id: str | None,
    settings: Settings,
) -> tuple[AiRetrievalIngestionRun, dict[str, int]]:
    unsupported = source_types - set(RAG_SOURCE_TYPES)
    if unsupported:
        raise RagError("Unsupported RAG source types: " + ", ".join(sorted(unsupported)))
    if not source_types:
        raise RagError("At least one RAG source type is required")
    running = db.scalar(
        select(AiRetrievalIngestionRun).where(
            AiRetrievalIngestionRun.tenant_id == tenant_id,
            AiRetrievalIngestionRun.status == "RUNNING",
        )
    )
    if running is not None:
        raise RagError("A retrieval ingestion run is already active for this tenant")
    now = utcnow()
    run = AiRetrievalIngestionRun(
        id=str(uuid.uuid4()),
        tenant_id=tenant_id,
        status="RUNNING",
        source_types_json=canonical_json(sorted(source_types)),
        requested_by_id=actor_id,
        started_at=now,
    )
    db.add(run)
    db.flush()
    counts = {
        "scanned": 0,
        "indexed": 0,
        "updated": 0,
        "unchanged": 0,
        "deleted": 0,
    }
    try:
        for source_type in sorted(source_types):
            sources = _SOURCE_LOADERS[source_type](db, tenant_id)
            seen: set[tuple[str, str]] = set()
            for source in sources:
                content = source.content[: settings.ai_rag_document_max_chars]
                if not content.strip():
                    continue
                scope_key = source.tenant_id or "global"
                seen.add((scope_key, source.source_id))
                counts["scanned"] += 1
                document = db.scalar(
                    select(AiRetrievalDocument).where(
                        AiRetrievalDocument.scope_key == scope_key,
                        AiRetrievalDocument.source_type == source.source_type,
                        AiRetrievalDocument.source_id == source.source_id,
                    )
                )
                content_hash = digest_text(content)
                if document is None:
                    document = AiRetrievalDocument(
                        id=str(uuid.uuid4()),
                        tenant_id=source.tenant_id,
                        scope_key=scope_key,
                        source_type=source.source_type,
                        source_id=source.source_id,
                        source_key=source.source_key,
                        title=source.title[:320],
                        url_path=source.url_path,
                        visibility=source.visibility,
                        permission_code=source.permission_code,
                        status="ACTIVE",
                        content_sha256=content_hash,
                        source_version=source.source_version,
                        source_updated_at=source.source_updated_at,
                        metadata_json=canonical_json(source.metadata),
                        version=1,
                        indexed_at=now,
                    )
                    db.add(document)
                    db.flush()
                    _replace_chunks(db, document, content, settings)
                    counts["indexed"] += 1
                elif (
                    document.content_sha256 == content_hash
                    and document.source_version == source.source_version
                    and document.status == "ACTIVE"
                ):
                    document.indexed_at = now
                    counts["unchanged"] += 1
                else:
                    document.tenant_id = source.tenant_id
                    document.scope_key = scope_key
                    document.source_key = source.source_key
                    document.title = source.title[:320]
                    document.url_path = source.url_path
                    document.visibility = source.visibility
                    document.permission_code = source.permission_code
                    document.status = "ACTIVE"
                    document.content_sha256 = content_hash
                    document.source_version = source.source_version
                    document.source_updated_at = source.source_updated_at
                    document.metadata_json = canonical_json(source.metadata)
                    document.version += 1
                    document.indexed_at = now
                    document.deleted_at = None
                    _replace_chunks(db, document, content, settings)
                    counts["updated"] += 1
            scope_condition = (
                AiRetrievalDocument.scope_key.in_((tenant_id, "global"))
                if source_type == "knowledge"
                else AiRetrievalDocument.scope_key == tenant_id
            )
            existing = db.scalars(
                select(AiRetrievalDocument).where(
                    AiRetrievalDocument.source_type == source_type,
                    AiRetrievalDocument.status == "ACTIVE",
                    scope_condition,
                )
            ).all()
            for document in existing:
                if (document.scope_key, document.source_id) not in seen:
                    document.status = "DELETED"
                    document.deleted_at = now
                    document.version += 1
                    db.execute(
                        delete(AiRetrievalChunk).where(
                            AiRetrievalChunk.document_id == document.id
                        )
                    )
                    counts["deleted"] += 1
        run.status = "COMPLETED"
        run.scanned_count = counts["scanned"]
        run.indexed_count = counts["indexed"]
        run.updated_count = counts["updated"]
        run.unchanged_count = counts["unchanged"]
        run.deleted_count = counts["deleted"]
        run.completed_at = utcnow()
        db.flush()
        return run, counts
    except Exception as exc:
        run.status = "FAILED"
        run.error_message = f"{exc.__class__.__name__}: {str(exc)[:1500]}"
        run.completed_at = utcnow()
        db.flush()
        raise


def _source_is_eligible(source_type: str, item: Any) -> bool:
    if source_type == "knowledge":
        return item.status == "published"
    if source_type == "ticket":
        return str(item.status).upper() in {"RESOLVED", "CLOSED"}
    if source_type == "problem":
        return bool(item.known_error_published_at) or str(item.status).upper() in {
            "KNOWN_ERROR",
            "RESOLVED",
            "CLOSED",
        }
    if source_type == "change":
        return str(item.status).upper() in {"COMPLETED", "ROLLED_BACK", "FAILED"}
    if source_type == "asset":
        return (
            str(item.verification_status or "").lower() in {"verified", "certified"}
            and str(item.lifecycle_status or "ACTIVE").upper() == "ACTIVE"
        )
    return False


def _load_live_sources(
    db: Session,
    documents: list[AiRetrievalDocument],
) -> dict[tuple[str, str], Any]:
    by_type: dict[str, list[str]] = {}
    for document in documents:
        by_type.setdefault(document.source_type, []).append(document.source_id)
    model_by_type = {
        "knowledge": KnowledgeArticle,
        "ticket": Ticket,
        "problem": Problem,
        "change": ChangeRequest,
        "asset": Asset,
    }
    result: dict[tuple[str, str], Any] = {}
    for source_type, ids in by_type.items():
        model = model_by_type[source_type]
        for item in db.scalars(select(model).where(model.id.in_(ids))).all():
            result[(source_type, item.id)] = item
    return result


def _user_can_read_document(
    current_user: AuthUserResponse,
    document: AiRetrievalDocument,
    source: Any,
    tenant_id: str,
) -> bool:
    if not is_saas_root(current_user) and document.tenant_id not in {
        None,
        current_user.tenant_id,
    }:
        return False
    if document.tenant_id is not None and document.tenant_id != tenant_id:
        return False
    if not has_permission(current_user, document.permission_code):
        return False
    if document.source_type == "knowledge":
        if source.tenant_id not in {None, tenant_id}:
            return False
        if document.visibility == "restricted":
            return has_permission(current_user, "knowledge.update") or has_permission(
                current_user, "knowledge.publish"
            )
        return True
    if getattr(source, "tenant_id", None) != tenant_id:
        return False
    if document.source_type == "ticket":
        return can_read_ticket(current_user, source)
    return True


def _document_is_fresh(document: AiRetrievalDocument, source: Any) -> bool:
    updated_at = getattr(source, "updated_at", None) or getattr(source, "created_at", None)
    return (
        _source_is_eligible(document.source_type, source)
        and _timestamp(updated_at) <= _timestamp(document.source_updated_at)
    )


def retrieve_authorized_context(
    db: Session,
    *,
    tenant_id: str,
    current_user: AuthUserResponse,
    query: str,
    source_types: set[str],
    limit: int,
    minimum_score: float,
    settings: Settings,
) -> dict[str, Any]:
    started = time.perf_counter()
    normalized_query = normalize_text(query)
    if not normalized_query:
        raise RagError("RAG query cannot be empty")
    if detects_prompt_injection(query):
        raise RagSafetyError("Potential prompt-injection instruction detected")
    unsupported = source_types - set(RAG_SOURCE_TYPES)
    if unsupported:
        raise RagError("Unsupported RAG source types: " + ", ".join(sorted(unsupported)))
    allowed_source_types = {
        source_type
        for source_type in source_types
        if has_permission(current_user, SOURCE_PERMISSIONS[source_type])
    }
    denied_by_permission = len(source_types - allowed_source_types)
    if not allowed_source_types:
        return {
            "citations": [],
            "retrieved_count": 0,
            "permission_denied_count": denied_by_permission,
            "stale_count": 0,
            "unsafe_source_count": 0,
            "latency_ms": round((time.perf_counter() - started) * 1000),
        }
    documents = db.scalars(
        select(AiRetrievalDocument).where(
            AiRetrievalDocument.status == "ACTIVE",
            AiRetrievalDocument.source_type.in_(allowed_source_types),
            or_(
                AiRetrievalDocument.scope_key == tenant_id,
                AiRetrievalDocument.scope_key == "global",
            ),
        )
    ).all()
    live = _load_live_sources(db, documents)
    authorized: list[AiRetrievalDocument] = []
    stale_count = 0
    denied_count = denied_by_permission
    now = utcnow()
    for document in documents:
        source = live.get((document.source_type, document.source_id))
        if source is None or not _source_is_eligible(document.source_type, source):
            document.status = "DELETED"
            document.deleted_at = now
            document.version += 1
            db.execute(
                delete(AiRetrievalChunk).where(
                    AiRetrievalChunk.document_id == document.id
                )
            )
            stale_count += 1
            continue
        if not _user_can_read_document(current_user, document, source, tenant_id):
            denied_count += 1
            continue
        if not _document_is_fresh(document, source):
            stale_count += 1
            continue
        authorized.append(document)
    if not authorized:
        return {
            "citations": [],
            "retrieved_count": 0,
            "permission_denied_count": denied_count,
            "stale_count": stale_count,
            "unsafe_source_count": 0,
            "latency_ms": round((time.perf_counter() - started) * 1000),
        }
    document_map = {item.id: item for item in authorized}
    chunks = db.scalars(
        select(AiRetrievalChunk)
        .where(AiRetrievalChunk.document_id.in_(document_map))
        .order_by(AiRetrievalChunk.created_at.desc())
        .limit(settings.ai_rag_max_candidate_chunks)
    ).all()
    query_tokens = set(tokenize(query))
    query_vector = sparse_embedding(query, settings.ai_rag_embedding_dimensions)
    scored: list[tuple[float, AiRetrievalChunk, AiRetrievalDocument]] = []
    unsafe_source_count = 0
    for chunk in chunks:
        document = document_map[chunk.document_id]
        if detects_prompt_injection(chunk.content_text):
            unsafe_source_count += 1
            continue
        chunk_tokens = set(tokenize(chunk.search_text))
        lexical = (
            len(query_tokens & chunk_tokens) / max(1, len(query_tokens))
            if query_tokens
            else 0.0
        )
        try:
            chunk_vector = {
                str(key): float(value)
                for key, value in json_object(chunk.embedding_json).items()
            }
        except (TypeError, ValueError):
            chunk_vector = {}
        semantic = max(0.0, cosine_sparse(query_vector, chunk_vector))
        title_tokens = set(tokenize(document.title))
        title_match = len(query_tokens & title_tokens) / max(1, len(query_tokens))
        exact = 1.0 if normalized_query in chunk.search_text else 0.0
        age_days = max(
            0.0,
            (now - _timestamp(document.source_updated_at)).total_seconds() / 86_400,
        )
        freshness = max(0.0, 1.0 - min(age_days, 730.0) / 730.0)
        score = (
            lexical * 0.48
            + semantic * 0.30
            + title_match * 0.12
            + exact * 0.06
            + freshness * 0.04
        )
        if score >= minimum_score:
            scored.append((score, chunk, document))
    scored.sort(key=lambda item: (-item[0], item[2].source_key, item[1].ordinal))
    citations: list[dict[str, Any]] = []
    seen_documents: set[str] = set()
    context_chars = 0
    for score, chunk, document in scored:
        if document.id in seen_documents:
            continue
        excerpt = chunk.content_text[:1_200]
        if context_chars + len(excerpt) > settings.ai_rag_max_context_chars:
            break
        seen_documents.add(document.id)
        context_chars += len(excerpt)
        citations.append(
            {
                "citation_id": f"S{len(citations) + 1}",
                "source_type": document.source_type,
                "source_id": document.source_id,
                "source_key": document.source_key,
                "title": document.title,
                "url_path": document.url_path,
                "excerpt": excerpt,
                "score": round(score, 6),
                "content_sha256": chunk.content_sha256,
                "source_updated_at": _timestamp(document.source_updated_at).isoformat(),
                "indexed_at": _timestamp(document.indexed_at).isoformat(),
                "metadata": json_object(document.metadata_json),
            }
        )
        if len(citations) >= min(limit, settings.ai_rag_max_citations):
            break
    return {
        "citations": citations,
        "retrieved_count": len(citations),
        "permission_denied_count": denied_count,
        "stale_count": stale_count,
        "unsafe_source_count": unsafe_source_count,
        "latency_ms": round((time.perf_counter() - started) * 1000),
    }


def create_query_log(
    db: Session,
    *,
    tenant_id: str,
    user_id: str,
    query: str,
    source_types: Iterable[str],
    citations: list[dict[str, Any]],
    answer: str | None,
    provider: str,
    model: str,
    permission_denied_count: int,
    stale_count: int,
    injection_detected: bool,
    grounded: bool,
    latency_ms: int,
) -> AiRetrievalQueryLog:
    redacted = redact_pii(query).text[:500]
    evidence = [
        {
            "citation_id": item["citation_id"],
            "source_type": item["source_type"],
            "source_id": item["source_id"],
            "source_key": item["source_key"],
            "content_sha256": item["content_sha256"],
            "source_updated_at": item["source_updated_at"],
        }
        for item in citations
    ]
    item = AiRetrievalQueryLog(
        id=str(uuid.uuid4()),
        tenant_id=tenant_id,
        user_id=user_id,
        query_sha256=digest_text(query),
        query_preview_redacted=redacted,
        source_types_json=canonical_json(sorted(source_types)),
        citation_evidence_json=canonical_json(evidence),
        answer_sha256=digest_text(answer) if answer else None,
        provider=provider,
        model=model,
        retrieved_count=len(citations),
        permission_denied_count=permission_denied_count,
        stale_count=stale_count,
        injection_detected=injection_detected,
        grounded=grounded,
        no_result=not citations,
        latency_ms=max(0, latency_ms),
    )
    db.add(item)
    return item


def retrieval_dashboard(db: Session, tenant_id: str) -> dict[str, Any]:
    documents = db.scalars(
        select(AiRetrievalDocument).where(
            or_(
                AiRetrievalDocument.scope_key == tenant_id,
                AiRetrievalDocument.scope_key == "global",
            )
        )
    ).all()
    runs = db.scalars(
        select(AiRetrievalIngestionRun).where(
            AiRetrievalIngestionRun.tenant_id == tenant_id
        )
    ).all()
    queries = db.scalars(
        select(AiRetrievalQueryLog).where(AiRetrievalQueryLog.tenant_id == tenant_id)
    ).all()
    type_counts: dict[str, int] = {}
    for document in documents:
        if document.status == "ACTIVE":
            type_counts[document.source_type] = type_counts.get(document.source_type, 0) + 1
    latest_run = max(runs, key=lambda item: item.started_at, default=None)
    return {
        "active_documents": sum(item.status == "ACTIVE" for item in documents),
        "deleted_documents": sum(item.status == "DELETED" for item in documents),
        "source_type_counts": type_counts,
        "total_queries": len(queries),
        "grounded_queries": sum(item.grounded for item in queries),
        "no_result_queries": sum(item.no_result for item in queries),
        "stale_sources_blocked": sum(item.stale_count for item in queries),
        "permission_denials": sum(item.permission_denied_count for item in queries),
        "injection_attempts": sum(item.injection_detected for item in queries),
        "latest_ingestion": (
            {
                "id": latest_run.id,
                "status": latest_run.status,
                "source_types": json.loads(latest_run.source_types_json),
                "scanned_count": latest_run.scanned_count,
                "indexed_count": latest_run.indexed_count,
                "updated_count": latest_run.updated_count,
                "unchanged_count": latest_run.unchanged_count,
                "deleted_count": latest_run.deleted_count,
                "started_at": latest_run.started_at,
                "completed_at": latest_run.completed_at,
            }
            if latest_run
            else None
        ),
    }
