from __future__ import annotations

import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import asc, desc, func, select
from sqlalchemy.orm import Session

from app.api.v1.routes.auth import AuthUserResponse, get_current_user
from app.db.session import get_db
from app.models.knowledge_article import KnowledgeArticle
from app.models.knowledge_article_feedback import KnowledgeArticleFeedback
from app.models.knowledge_category import KnowledgeCategory
from app.models.knowledge_usage_log import KnowledgeUsageLog
from app.models.ticket import Ticket
from app.models.user import User
from app.services.automation import trigger_automation_event
from app.services.audit import log_audit
from app.services.knowledge_ai import article_payload, create_article_from_ticket, next_article_number, search_articles
from app.services.notifications import create_domain_event_notification
from app.services.rbac import require_permissions

router = APIRouter(prefix="/knowledge")


class KnowledgeCategoryResponse(BaseModel):
    id: str
    code: str
    name: str
    description: str | None
    created_at: datetime
    updated_at: datetime


class KnowledgeArticleResponse(BaseModel):
    id: str
    article_number: str
    title: str
    slug: str | None = None
    summary: str
    content: str
    category_id: str
    category_name: str | None
    ticket_category: str | None
    asset_type: str | None
    tags: list[str] = Field(default_factory=list)
    status: str
    visibility: str
    author_name: str
    source_ticket_id: str | None = None
    source_asset_id: str | None = None
    created_by_id: str | None = None
    updated_by_id: str | None = None
    view_count: int = 0
    helpful_count: int
    not_helpful_count: int
    last_used_at: datetime | None = None
    created_at: datetime
    updated_at: datetime
    published_at: datetime | None
    archived_at: datetime | None = None


class KnowledgeArticlePageResponse(BaseModel):
    items: list[KnowledgeArticleResponse]
    total: int
    page: int
    page_size: int


class KnowledgeArticleCreateRequest(BaseModel):
    title: str
    slug: str | None = None
    summary: str
    content: str
    category_id: str
    ticket_category: str | None = None
    asset_type: str | None = None
    tags: list[str] = Field(default_factory=list)
    status: str = "draft"
    visibility: str = "internal"


class KnowledgeArticlePatchRequest(BaseModel):
    title: str | None = None
    slug: str | None = None
    summary: str | None = None
    content: str | None = None
    category_id: str | None = None
    ticket_category: str | None = None
    asset_type: str | None = None
    tags: list[str] | None = None
    status: str | None = None
    visibility: str | None = None
    published_at: datetime | None = None


class KnowledgeFeedbackRequest(BaseModel):
    is_helpful: bool
    comment: str | None = None


class KnowledgeFeedbackResponse(BaseModel):
    id: str
    article_id: str
    user_name: str
    is_helpful: bool
    comment: str | None
    created_at: datetime


class KnowledgeArticleStatusResponse(BaseModel):
    id: str
    status: str
    published_at: datetime | None
    archived_at: datetime | None


class KnowledgeLogUsageRequest(BaseModel):
    ticket_id: str | None = None
    action: str = "used"
    context: dict[str, object] | None = None


class KnowledgeUsageResponse(BaseModel):
    id: str
    article_id: str
    ticket_id: str | None
    user_id: str | None
    action: str
    context: dict[str, object] | None
    created_at: datetime


class KnowledgeCreateFromTicketResponse(BaseModel):
    id: str
    article_number: str
    title: str
    summary: str
    status: str
    visibility: str


def _article_to_response(article: KnowledgeArticle, categories: dict[str, KnowledgeCategory]) -> KnowledgeArticleResponse:
    category = categories.get(article.category_id)
    return KnowledgeArticleResponse(**article_payload(article, category.name if category else None))


def _article_base_query():
    return select(KnowledgeArticle)


def _track_usage(db: Session, article: KnowledgeArticle, user: AuthUserResponse, action: str, ticket_id: str | None = None, context: dict[str, object] | None = None) -> KnowledgeUsageLog:
    usage = KnowledgeUsageLog(
        id=str(uuid.uuid4()),
        article_id=article.id,
        ticket_id=ticket_id,
        user_id=user.id,
        action=action,
        context=context,
    )
    article.last_used_at = datetime.now(UTC)
    db.add(usage)
    return usage


@router.get("/categories", response_model=list[KnowledgeCategoryResponse])
def list_categories(current_user: AuthUserResponse = Depends(get_current_user), db: Session = Depends(get_db)) -> list[KnowledgeCategoryResponse]:
    require_permissions(current_user, "knowledge.read")
    categories = db.scalars(select(KnowledgeCategory).order_by(KnowledgeCategory.name.asc())).all()
    return [KnowledgeCategoryResponse(**{k: getattr(item, k) for k in KnowledgeCategoryResponse.model_fields.keys()}) for item in categories]


@router.get("/articles", response_model=list[KnowledgeArticleResponse])
def list_articles(
    current_user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
    category_id: str | None = Query(default=None),
    tag: str | None = Query(default=None),
    status_filter: str | None = Query(default=None, alias="status"),
) -> list[KnowledgeArticleResponse]:
    require_permissions(current_user, "knowledge.read")
    statement = _article_base_query().order_by(KnowledgeArticle.updated_at.desc(), KnowledgeArticle.created_at.desc())
    if category_id:
        statement = statement.where(KnowledgeArticle.category_id == category_id)
    if status_filter and status_filter != "ALL":
        statement = statement.where(KnowledgeArticle.status == status_filter)

    articles = db.scalars(statement).all()
    if tag:
        normalized = tag.lower()
        articles = [item for item in articles if normalized in (item.tags or "").lower()]

    categories = {item.id: item for item in db.scalars(select(KnowledgeCategory)).all()}
    return [_article_to_response(article, categories) for article in articles]


@router.get("/articles/page", response_model=KnowledgeArticlePageResponse)
def list_articles_page(
    current_user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
    q: str | None = Query(default=None, min_length=1),
    category_id: str | None = Query(default=None),
    status_filter: str | None = Query(default=None, alias="status"),
    visibility: str | None = Query(default=None),
    sort_by: str = Query(default="updated_at"),
    sort_dir: str = Query(default="desc"),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=200),
) -> KnowledgeArticlePageResponse:
    require_permissions(current_user, "knowledge.read")
    statement = _article_base_query()
    if q:
        pattern = f"%{q.strip().lower()}%"
        statement = statement.where(
            func.lower(KnowledgeArticle.title).like(pattern)
            | func.lower(KnowledgeArticle.summary).like(pattern)
            | func.lower(KnowledgeArticle.content).like(pattern)
            | func.lower(func.coalesce(KnowledgeArticle.tags, "")).like(pattern)
        )
    if category_id:
        statement = statement.where(KnowledgeArticle.category_id == category_id)
    if status_filter and status_filter != "ALL":
        statement = statement.where(KnowledgeArticle.status == status_filter)
    if visibility and visibility != "ALL":
        statement = statement.where(KnowledgeArticle.visibility == visibility)

    total = db.scalar(select(func.count()).select_from(statement.subquery())) or 0
    sort_map = {
        "updated_at": KnowledgeArticle.updated_at,
        "created_at": KnowledgeArticle.created_at,
        "published_at": KnowledgeArticle.published_at,
        "title": KnowledgeArticle.title,
        "helpful_count": KnowledgeArticle.helpful_count,
        "view_count": KnowledgeArticle.view_count,
        "last_used_at": KnowledgeArticle.last_used_at,
    }
    order_column = sort_map.get(sort_by, KnowledgeArticle.updated_at)
    direction = asc if sort_dir.lower() == "asc" else desc
    categories = {item.id: item for item in db.scalars(select(KnowledgeCategory)).all()}
    items = db.scalars(statement.order_by(direction(order_column), KnowledgeArticle.created_at.desc()).offset((page - 1) * page_size).limit(page_size)).all()
    return KnowledgeArticlePageResponse(items=[_article_to_response(item, categories) for item in items], total=total, page=page, page_size=page_size)


@router.get("/articles/{article_id}", response_model=KnowledgeArticleResponse)
def get_article(article_id: str, current_user: AuthUserResponse = Depends(get_current_user), db: Session = Depends(get_db)) -> KnowledgeArticleResponse:
    require_permissions(current_user, "knowledge.read")
    article = db.scalar(select(KnowledgeArticle).where(KnowledgeArticle.id == article_id))
    if article is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Article not found")
    article.view_count = (article.view_count or 0) + 1
    _track_usage(db, article, current_user, action="view")
    db.commit()
    db.refresh(article)
    categories = {item.id: item for item in db.scalars(select(KnowledgeCategory)).all()}
    return _article_to_response(article, categories)


@router.post("/articles", response_model=KnowledgeArticleResponse, status_code=status.HTTP_201_CREATED)
def create_article(
    request: KnowledgeArticleCreateRequest,
    http_request: Request,
    current_user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> KnowledgeArticleResponse:
    require_permissions(current_user, "knowledge.create")
    if request.status == "published":
        require_permissions(current_user, "knowledge.publish")
    category = db.scalar(select(KnowledgeCategory).where(KnowledgeCategory.id == request.category_id))
    if category is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Unknown knowledge category")

    now = datetime.now(UTC)
    article = KnowledgeArticle(
        id=str(uuid.uuid4()),
        article_number=next_article_number(db),
        title=request.title,
        slug=request.slug,
        summary=request.summary,
        content=request.content,
        category_id=request.category_id,
        ticket_category=request.ticket_category,
        asset_type=request.asset_type,
        tags=", ".join(request.tags),
        tags_json=request.tags,
        status=request.status,
        visibility=request.visibility,
        author_name=current_user.full_name,
        created_by_id=current_user.id,
        updated_by_id=current_user.id,
        view_count=0,
        helpful_count=0,
        not_helpful_count=0,
        created_at=now,
        updated_at=now,
        published_at=now if request.status == "published" else None,
    )
    db.add(article)
    actor = db.scalar(select(User).where(User.id == current_user.id))
    log_audit(
        db,
        action="knowledge_article_created",
        entity_type="knowledge_article",
        entity_id=article.id,
        actor_user=actor,
        ip_address=http_request.client.host if http_request.client else None,
        user_agent=http_request.headers.get("user-agent"),
        metadata={"article_number": article.article_number},
    )
    if article.status == "published":
        create_domain_event_notification(
            db,
            tenant_id=current_user.tenant_id,
            event_type="knowledge_article_published",
            title=f"Опубликована статья: {article.article_number}",
            message=f"Статья '{article.title}' опубликована в базе знаний.",
            recipient_name=current_user.full_name,
            recipient_email=current_user.email,
            recipient_user_id=current_user.id,
            severity="info",
            entity_type="knowledge_article",
            entity_id=article.id,
            action_url="/knowledge",
            metadata={"article_number": article.article_number, "title": article.title},
        )
        trigger_automation_event(
            db,
            tenant_id=current_user.tenant_id,
            trigger_type="knowledge_article_published",
            context={"entity_type": "knowledge_article", "entity_id": article.id, "article": {"id": article.id, "title": article.title}},
            actor_email=current_user.email,
        )
    db.commit()
    db.refresh(article)
    return _article_to_response(article, {category.id: category})


@router.patch("/articles/{article_id}", response_model=KnowledgeArticleResponse)
def patch_article(
    article_id: str,
    request: KnowledgeArticlePatchRequest,
    http_request: Request,
    current_user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> KnowledgeArticleResponse:
    require_permissions(current_user, "knowledge.update")
    article = db.scalar(select(KnowledgeArticle).where(KnowledgeArticle.id == article_id))
    if article is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Article not found")

    updates = request.model_dump(exclude_unset=True)
    if updates.get("status") == "published":
        require_permissions(current_user, "knowledge.publish")
    if "category_id" in updates:
        category = db.scalar(select(KnowledgeCategory).where(KnowledgeCategory.id == updates["category_id"]))
        if category is None:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Unknown knowledge category")

    for field_name, new_value in updates.items():
        if field_name == "tags" and isinstance(new_value, list):
            setattr(article, "tags", ", ".join(new_value))
            setattr(article, "tags_json", new_value)
        else:
            setattr(article, field_name, new_value)

    article.updated_by_id = current_user.id
    article.updated_at = datetime.now(UTC)

    actor = db.scalar(select(User).where(User.id == current_user.id))
    if article.status == "published":
        log_audit(
            db,
            action="article_published",
            entity_type="knowledge_article",
            entity_id=article.id,
            actor_user=actor,
            ip_address=http_request.client.host if http_request.client else None,
            user_agent=http_request.headers.get("user-agent"),
            metadata={"article_number": article.article_number},
        )
        create_domain_event_notification(
            db,
            tenant_id=current_user.tenant_id,
            event_type="knowledge_article_published",
            title=f"Опубликована статья: {article.article_number}",
            message=f"Статья '{article.title}' опубликована или обновлена в статусе published.",
            recipient_name=current_user.full_name,
            recipient_email=current_user.email,
            recipient_user_id=current_user.id,
            severity="info",
            entity_type="knowledge_article",
            entity_id=article.id,
            action_url="/knowledge",
            metadata={"article_number": article.article_number, "title": article.title},
        )
        trigger_automation_event(
            db,
            tenant_id=current_user.tenant_id,
            trigger_type="knowledge_article_published",
            context={"entity_type": "knowledge_article", "entity_id": article.id, "article": {"id": article.id, "title": article.title}},
            actor_email=current_user.email,
        )
    db.commit()
    db.refresh(article)
    categories = {item.id: item for item in db.scalars(select(KnowledgeCategory)).all()}
    return _article_to_response(article, categories)


@router.post("/articles/{article_id}/publish", response_model=KnowledgeArticleStatusResponse)
def publish_article(
    article_id: str,
    http_request: Request,
    current_user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> KnowledgeArticleStatusResponse:
    require_permissions(current_user, "knowledge.publish")
    article = db.scalar(select(KnowledgeArticle).where(KnowledgeArticle.id == article_id))
    if article is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Article not found")
    now = datetime.now(UTC)
    article.status = "published"
    article.published_at = now
    article.archived_at = None
    article.updated_at = now
    article.updated_by_id = current_user.id
    actor = db.scalar(select(User).where(User.id == current_user.id))
    log_audit(
        db,
        action="knowledge_article_published",
        entity_type="knowledge_article",
        entity_id=article.id,
        actor_user=actor,
        ip_address=http_request.client.host if http_request.client else None,
        user_agent=http_request.headers.get("user-agent"),
        metadata={"article_number": article.article_number},
    )
    db.commit()
    db.refresh(article)
    return KnowledgeArticleStatusResponse(id=article.id, status=article.status, published_at=article.published_at, archived_at=article.archived_at)


@router.post("/articles/{article_id}/archive", response_model=KnowledgeArticleStatusResponse)
def archive_article(
    article_id: str,
    http_request: Request,
    current_user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> KnowledgeArticleStatusResponse:
    require_permissions(current_user, "knowledge.archive")
    article = db.scalar(select(KnowledgeArticle).where(KnowledgeArticle.id == article_id))
    if article is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Article not found")
    now = datetime.now(UTC)
    article.status = "archived"
    article.archived_at = now
    article.updated_at = now
    article.updated_by_id = current_user.id
    actor = db.scalar(select(User).where(User.id == current_user.id))
    log_audit(
        db,
        action="knowledge_article_archived",
        entity_type="knowledge_article",
        entity_id=article.id,
        actor_user=actor,
        ip_address=http_request.client.host if http_request.client else None,
        user_agent=http_request.headers.get("user-agent"),
        metadata={"article_number": article.article_number},
    )
    db.commit()
    db.refresh(article)
    return KnowledgeArticleStatusResponse(id=article.id, status=article.status, published_at=article.published_at, archived_at=article.archived_at)


@router.post("/articles/{article_id}/usage", response_model=KnowledgeUsageResponse, status_code=status.HTTP_201_CREATED)
def log_article_usage(
    article_id: str,
    request: KnowledgeLogUsageRequest,
    current_user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> KnowledgeUsageResponse:
    require_permissions(current_user, "knowledge.usage.write")
    article = db.scalar(select(KnowledgeArticle).where(KnowledgeArticle.id == article_id))
    if article is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Article not found")

    if request.ticket_id is not None:
        ticket = db.scalar(select(Ticket).where(Ticket.id == request.ticket_id))
        if ticket is None:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Unknown ticket")

    usage = _track_usage(db, article, current_user, action=request.action, ticket_id=request.ticket_id, context=request.context)
    db.commit()
    db.refresh(usage)
    return KnowledgeUsageResponse(
        id=usage.id,
        article_id=usage.article_id,
        ticket_id=usage.ticket_id,
        user_id=usage.user_id,
        action=usage.action,
        context=usage.context,
        created_at=usage.created_at,
    )


@router.post("/articles/{article_id}/feedback", response_model=KnowledgeFeedbackResponse, status_code=status.HTTP_201_CREATED)
def leave_feedback(
    article_id: str,
    request: KnowledgeFeedbackRequest,
    current_user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> KnowledgeFeedbackResponse:
    require_permissions(current_user, "knowledge.feedback")
    article = db.scalar(select(KnowledgeArticle).where(KnowledgeArticle.id == article_id))
    if article is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Article not found")

    feedback = KnowledgeArticleFeedback(
        id=str(uuid.uuid4()),
        article_id=article.id,
        user_name=current_user.full_name,
        is_helpful=request.is_helpful,
        comment=request.comment,
    )
    if request.is_helpful:
        article.helpful_count += 1
    else:
        article.not_helpful_count += 1
    _track_usage(
        db,
        article,
        current_user,
        action="feedback_helpful" if request.is_helpful else "feedback_not_helpful",
        context={"has_comment": bool(request.comment)},
    )

    db.add(feedback)
    db.commit()
    db.refresh(feedback)
    return KnowledgeFeedbackResponse(
        id=feedback.id,
        article_id=feedback.article_id,
        user_name=feedback.user_name,
        is_helpful=feedback.is_helpful,
        comment=feedback.comment,
        created_at=feedback.created_at,
    )


@router.post("/articles/from-ticket/{ticket_id}", response_model=KnowledgeCreateFromTicketResponse, status_code=status.HTTP_201_CREATED)
def create_article_by_ticket(
    ticket_id: str,
    current_user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> KnowledgeCreateFromTicketResponse:
    require_permissions(current_user, "knowledge.create_from_ticket")
    ticket = db.scalar(select(Ticket).where(Ticket.id == ticket_id))
    if ticket is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Ticket not found")

    article = create_article_from_ticket(db, ticket, current_user.full_name)
    article.source_ticket_id = ticket.id
    article.created_by_id = current_user.id
    article.updated_by_id = current_user.id
    db.commit()
    db.refresh(article)
    payload = article_payload(article)
    return KnowledgeCreateFromTicketResponse(
        id=str(payload["id"]),
        article_number=str(payload["article_number"]),
        title=str(payload["title"]),
        summary=str(payload["summary"]),
        status=str(payload["status"]),
        visibility=str(payload["visibility"]),
    )


@router.get("/search", response_model=list[KnowledgeArticleResponse])
def search_knowledge(
    q: str = Query(..., min_length=1),
    current_user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[KnowledgeArticleResponse]:
    require_permissions(current_user, "knowledge.read")
    categories = {item.id: item for item in db.scalars(select(KnowledgeCategory)).all()}
    return [_article_to_response(article, categories) for article in search_articles(db, q)]
