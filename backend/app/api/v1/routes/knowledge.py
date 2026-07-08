from __future__ import annotations

import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.v1.routes.auth import AuthUserResponse, get_current_user
from app.db.session import get_db
from app.models.knowledge_article import KnowledgeArticle
from app.models.knowledge_article_feedback import KnowledgeArticleFeedback
from app.models.knowledge_category import KnowledgeCategory
from app.models.user import User
from app.services.audit import log_audit
from app.services.knowledge_ai import article_payload, next_article_number, search_articles
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
    helpful_count: int
    not_helpful_count: int
    created_at: datetime
    updated_at: datetime
    published_at: datetime | None


class KnowledgeArticleCreateRequest(BaseModel):
    title: str
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


def _article_to_response(article: KnowledgeArticle, categories: dict[str, KnowledgeCategory]) -> KnowledgeArticleResponse:
    category = categories.get(article.category_id)
    return KnowledgeArticleResponse(**article_payload(article, category.name if category else None))


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
) -> list[KnowledgeArticleResponse]:
    require_permissions(current_user, "knowledge.read")
    statement = select(KnowledgeArticle).order_by(KnowledgeArticle.updated_at.desc(), KnowledgeArticle.created_at.desc())
    if category_id:
        statement = statement.where(KnowledgeArticle.category_id == category_id)

    articles = db.scalars(statement).all()
    if tag:
        normalized = tag.lower()
        articles = [item for item in articles if normalized in (item.tags or "").lower()]

    categories = {item.id: item for item in db.scalars(select(KnowledgeCategory)).all()}
    return [_article_to_response(article, categories) for article in articles]


@router.get("/articles/{article_id}", response_model=KnowledgeArticleResponse)
def get_article(article_id: str, current_user: AuthUserResponse = Depends(get_current_user), db: Session = Depends(get_db)) -> KnowledgeArticleResponse:
    require_permissions(current_user, "knowledge.read")
    article = db.scalar(select(KnowledgeArticle).where(KnowledgeArticle.id == article_id))
    if article is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Article not found")
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
        summary=request.summary,
        content=request.content,
        category_id=request.category_id,
        ticket_category=request.ticket_category,
        asset_type=request.asset_type,
        tags=", ".join(request.tags),
        status=request.status,
        visibility=request.visibility,
        author_name=current_user.full_name,
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
        else:
            setattr(article, field_name, new_value)

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
    db.commit()
    db.refresh(article)
    categories = {item.id: item for item in db.scalars(select(KnowledgeCategory)).all()}
    return _article_to_response(article, categories)


@router.post("/articles/{article_id}/feedback", response_model=KnowledgeFeedbackResponse, status_code=status.HTTP_201_CREATED)
def leave_feedback(
    article_id: str,
    request: KnowledgeFeedbackRequest,
    current_user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> KnowledgeFeedbackResponse:
    require_permissions(current_user, "knowledge.read")
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


@router.get("/search", response_model=list[KnowledgeArticleResponse])
def search_knowledge(
    q: str = Query(..., min_length=1),
    current_user: AuthUserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[KnowledgeArticleResponse]:
    require_permissions(current_user, "knowledge.read")
    categories = {item.id: item for item in db.scalars(select(KnowledgeCategory)).all()}
    return [_article_to_response(article, categories) for article in search_articles(db, q)]
