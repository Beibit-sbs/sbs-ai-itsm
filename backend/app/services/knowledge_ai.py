from __future__ import annotations

import re
import uuid
from datetime import UTC, datetime

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.models.ai_suggestion import AiSuggestion
from app.models.asset import Asset
from app.models.knowledge_article import KnowledgeArticle
from app.models.knowledge_category import KnowledgeCategory
from app.models.ticket import Ticket


def _uuid() -> str:
    return str(uuid.uuid4())


def _now() -> datetime:
    return datetime.now(UTC)


def _to_confidence_label(value: float) -> str:
    return f"{int(value * 100)}%"


def _split_tags(tags: str | None) -> list[str]:
    if not tags:
        return []
    return [item.strip() for item in tags.split(",") if item.strip()]


def _join_tags(tags: list[str]) -> str:
    return ", ".join(sorted({item.strip().lower() for item in tags if item.strip()}))


CATEGORY_SEEDS = [
    {"code": "NETWORK", "name": "Сеть и интернет", "description": "Интернет, Wi-Fi, сетевые подключения"},
    {"code": "PRINTER", "name": "Принтеры", "description": "Печать и обслуживание принтеров"},
    {"code": "ACCESS", "name": "Доступы и учетные записи", "description": "Пароли, доступы и аккаунты"},
    {"code": "IS", "name": "Информационные системы", "description": "Moodle, Platonus и внутренние ИС"},
    {"code": "MAIL", "name": "Корпоративная почта", "description": "Почта, письма, мобильная настройка"},
    {"code": "SECURITY", "name": "Информационная безопасность", "description": "Фишинг и инциденты безопасности"},
    {"code": "HARDWARE", "name": "Оборудование", "description": "Ноутбуки, ПК и железо"},
    {"code": "CLASSROOM", "name": "Аудиторное оборудование", "description": "Проекторы и интерактивные панели"},
]

ARTICLE_SEEDS = [
    ("KB-1001", "Не работает интернет в кабинете", "NETWORK", "NETWORK_INTERNET", "SWITCH", "internet,network,wifi", "Проверьте линк порта, шлюз, DNS и DHCP; перезапустите порт на коммутаторе."),
    ("KB-1002", "Нет подключения к Wi-Fi", "NETWORK", "NETWORK_WIFI", "WIFI_AP", "wifi,network,dhcp", "Проверьте точку доступа, пул DHCP и уровень сигнала в зоне покрытия."),
    ("KB-1003", "Компьютер не включается", "HARDWARE", "HARDWARE_WORKSTATION", "DESKTOP", "hardware,power,desktop", "Проверьте БП, кабель, ИБП и индикаторы материнской платы."),
    ("KB-1004", "Медленно работает ноутбук", "HARDWARE", "HARDWARE_WORKSTATION", "LAPTOP", "laptop,performance,ssd", "Проверьте загрузку CPU, диск, свободное место и автозагрузку."),
    ("KB-1005", "Не печатает принтер", "PRINTER", "PRINTING", "PRINTER", "printer,printing,spooler", "Проверьте статус устройства, подключение и службу печати."),
    ("KB-1006", "Очистка очереди печати", "PRINTER", "PRINTING", "PRINTER", "printer,queue,spool", "Остановите spooler, очистите очередь и запустите сервис заново."),
    ("KB-1007", "Сброс пароля пользователя", "ACCESS", "ACCOUNT_PASSWORD", "ACCOUNT", "access,password,account", "Подтвердите личность и выполните безопасный сброс пароля."),
    ("KB-1008", "Нет доступа к Platonus", "IS", "ACCESS_PLATONUS", "ACCOUNT", "platonus,access,education", "Проверьте роль, доменные группы и блокировки аккаунта."),
    ("KB-1009", "Нет доступа к Moodle", "IS", "ACCESS_MOODLE", "ACCOUNT", "moodle,access,education", "Проверьте синхронизацию учетной записи и права на курс."),
    ("KB-1010", "Не открывается корпоративная почта", "MAIL", "MAIL", "LAPTOP", "mail,zimbra,outlook", "Проверьте профиль почтового клиента и доступ к webmail."),
    ("KB-1011", "Настройка почты на телефоне", "MAIL", "MAIL", "SMARTPHONE", "mail,smartphone,imap", "Используйте корпоративные IMAP/SMTP параметры и SSL/TLS."),
    ("KB-1012", "Подозрительное фишинговое письмо", "SECURITY", "SECURITY_PHISHING", "ACCOUNT", "security,phishing,email", "Не открывайте ссылку, изолируйте письмо и передайте в ИБ."),
    ("KB-1013", "Проверка сетевого кабеля", "NETWORK", "NETWORK_INTERNET", "SWITCH", "network,cable,link", "Проверьте патчкорд, коннектор, порт и переключите в резервный порт."),
    ("KB-1014", "Проектор не выводит изображение", "CLASSROOM", "AV_PROJECTOR", "PROJECTOR", "projector,av,hdmi", "Проверьте вход, кабель HDMI и разрешение источника."),
    ("KB-1015", "Интерактивная панель не реагирует", "CLASSROOM", "AV_PROJECTOR", "INTERACTIVE_PANEL", "panel,touch,classroom", "Проверьте USB-линк тача, калибровку и режим источника."),
    ("KB-1016", "Установка офисного ПО", "HARDWARE", "SOFTWARE_INSTALL", "LAPTOP", "software,office,install", "Проверьте лицензию и установите пакет из корпоративного каталога."),
    ("KB-1017", "Заявка на новое оборудование", "HARDWARE", "PROCUREMENT", "LAPTOP", "procurement,asset,new", "Оформите обоснование, согласуйте бюджет и наличие на складе."),
    ("KB-1018", "Проверка гарантии оборудования", "HARDWARE", "PROCUREMENT", "LAPTOP", "warranty,asset,repair", "Сверьте серийный номер и дату окончания гарантии в реестре."),
    ("KB-1019", "Что делать при массовом сбое интернета", "NETWORK", "NETWORK_INTERNET", "SWITCH", "major-incident,network,outage", "Запустите major incident процесс, уведомите пользователей и эскалируйте NOC."),
    ("KB-1020", "Как правильно описать ИТ-проблему", "ACCESS", "SOFTWARE_INSTALL", "ACCOUNT", "template,description,request", "Укажите симптомы, время, локацию и шаги воспроизведения проблемы."),
]


def seed_knowledge_ai_demo_data(db: Session) -> None:
    if db.scalar(select(KnowledgeCategory.id)) is None:
        db.add_all([KnowledgeCategory(id=_uuid(), **seed) for seed in CATEGORY_SEEDS])
        db.flush()

    categories = {item.code: item for item in db.scalars(select(KnowledgeCategory)).all()}
    existing_numbers = set(db.scalars(select(KnowledgeArticle.article_number)).all())

    for article_number, title, category_code, ticket_category, asset_type, tags, solution in ARTICLE_SEEDS:
        if article_number in existing_numbers:
            continue
        category = categories[category_code]
        now = _now()
        db.add(
            KnowledgeArticle(
                id=_uuid(),
                article_number=article_number,
                title=title,
                summary=f"Инструкция: {title.lower()}.",
                content=solution,
                category_id=category.id,
                ticket_category=ticket_category,
                asset_type=asset_type,
                tags=tags,
                status="published",
                visibility="internal",
                author_name="SBS Knowledge Bot",
                helpful_count=3,
                not_helpful_count=1,
                created_at=now,
                updated_at=now,
                published_at=now,
            )
        )


def next_article_number(db: Session) -> str:
    existing = [value for value in db.scalars(select(KnowledgeArticle.article_number)).all() if value]
    max_value = 1000
    for value in existing:
        match = re.search(r"(\d+)$", value)
        if match:
            max_value = max(max_value, int(match.group(1)))
    return f"KB-{max_value + 1:04d}"


def _mock_rule(text: str) -> dict[str, object]:
    lowered = text.lower()
    rules = [
        (("интернет", "wi-fi", "wifi", "сеть"), "Сеть и интернет", "HIGH", "WIFI_AP", "Проверьте сеть, DHCP и порт коммутатора.", "Сбой сетевого узла или точки доступа.", "Сетевой инженер", 0.88, "NETWORK_INTERNET"),
        (("принтер", "печать"), "Принтеры", "MEDIUM", "PRINTER", "Очистите очередь печати и перезапустите spooler.", "Зависла очередь или недоступен принтер.", "Инженер печати", 0.79, "PRINTING"),
        (("пароль", "доступ"), "Доступы и учетные записи", "HIGH", "ACCOUNT", "Сбросьте пароль и проверьте блокировку аккаунта.", "Ошибочные учетные данные или блокировка.", "Service Desk Lead", 0.84, "ACCOUNT_PASSWORD"),
        (("moodle", "platonus"), "Информационные системы", "HIGH", "ACCOUNT", "Проверьте роли и синхронизацию в ИС.", "Некорректные права в системе.", "Системный администратор", 0.82, "ACCESS_PLATONUS"),
        (("фишинг", "подозрительное письмо"), "Информационная безопасность", "CRITICAL", "ACCOUNT", "Изолируйте письмо и передайте инцидент в ИБ.", "Попытка компрометации учетной записи.", "Специалист ИБ", 0.94, "SECURITY_PHISHING"),
        (("почта", "zimbra", "письмо"), "Корпоративная почта", "MEDIUM", "LAPTOP", "Проверьте профиль клиента и сервер почты.", "Сбой профиля или серверной синхронизации.", "Инженер поддержки", 0.77, "MAIL"),
        (("ноутбук", "компьютер", "не включается"), "Оборудование", "HIGH", "LAPTOP", "Проверьте питание, SSD и аппаратные ошибки.", "Аппаратный сбой рабочего места.", "Инженер поддержки", 0.83, "HARDWARE_WORKSTATION"),
        (("проектор", "интерактивная панель"), "Аудиторное оборудование", "MEDIUM", "PROJECTOR", "Проверьте источник сигнала и кабели AV.", "Проблема AV-коммутации в аудитории.", "AV-инженер", 0.78, "AV_PROJECTOR"),
    ]

    for keywords, category, priority, asset_type, solution, cause, assignee, confidence, ticket_category in rules:
        if any(keyword in lowered for keyword in keywords):
            return {
                "recommended_category": category,
                "recommended_priority": priority,
                "recommended_asset_type": asset_type,
                "summary": f"MockAI: обнаружена тема '{category.lower()}'.",
                "possible_cause": cause,
                "suggested_solution": solution,
                "recommended_assignee": assignee,
                "confidence": confidence,
                "ticket_category": ticket_category,
            }

    return {
        "recommended_category": "Общая поддержка",
        "recommended_priority": "MEDIUM",
        "recommended_asset_type": "LAPTOP",
        "summary": "MockAI: требуется дополнительная классификация обращения.",
        "possible_cause": "Недостаточно деталей для точного класса инцидента.",
        "suggested_solution": "Уточните симптомы, локацию, затронутый сервис и время появления ошибки.",
        "recommended_assignee": "Инженер поддержки",
        "confidence": 0.62,
        "ticket_category": None,
    }


def _related_articles(db: Session, ticket_category: str | None, recommended_category: str) -> list[KnowledgeArticle]:
    statement = select(KnowledgeArticle).order_by(KnowledgeArticle.helpful_count.desc(), KnowledgeArticle.created_at.desc())
    if ticket_category:
        statement = statement.where(
            or_(
                KnowledgeArticle.ticket_category == ticket_category,
                func.lower(KnowledgeArticle.summary).like(f"%{recommended_category.lower()}%"),
            )
        )
    else:
        statement = statement.where(func.lower(KnowledgeArticle.summary).like(f"%{recommended_category.lower()}%"))
    return db.scalars(statement.limit(5)).all()


def _similar_tickets(db: Session, ticket_category: str | None) -> list[Ticket]:
    if not ticket_category:
        return []
    return db.scalars(
        select(Ticket)
        .where(Ticket.category == ticket_category)
        .order_by(Ticket.updated_at.desc(), Ticket.created_at.desc())
        .limit(5)
    ).all()


def analyze_text_with_mock_ai(db: Session, input_text: str, ticket_id: str | None = None) -> dict[str, object]:
    matched = _mock_rule(input_text)
    related_articles = _related_articles(db, matched["ticket_category"], str(matched["recommended_category"]))
    similar_tickets = _similar_tickets(db, matched["ticket_category"])

    suggestion = AiSuggestion(
        id=_uuid(),
        ticket_id=ticket_id,
        input_text=input_text,
        recommended_category=str(matched["recommended_category"]),
        recommended_priority=str(matched["recommended_priority"]),
        recommended_asset_type=str(matched["recommended_asset_type"]),
        recommended_article_id=related_articles[0].id if related_articles else None,
        summary=str(matched["summary"]),
        possible_cause=str(matched["possible_cause"]),
        suggested_solution=str(matched["suggested_solution"]),
        recommended_assignee=str(matched["recommended_assignee"]),
        confidence=_to_confidence_label(float(matched["confidence"])),
    )
    db.add(suggestion)
    db.commit()
    db.refresh(suggestion)

    return {
        "id": suggestion.id,
        "ticket_id": suggestion.ticket_id,
        "input_text": suggestion.input_text,
        "recommended_category": suggestion.recommended_category,
        "recommended_priority": suggestion.recommended_priority,
        "recommended_asset_type": suggestion.recommended_asset_type,
        "recommended_article_id": suggestion.recommended_article_id,
        "summary": suggestion.summary,
        "possible_cause": suggestion.possible_cause,
        "suggested_solution": suggestion.suggested_solution,
        "recommended_assignee": suggestion.recommended_assignee,
        "confidence": suggestion.confidence,
        "related_articles": [
            {
                "id": article.id,
                "article_number": article.article_number,
                "title": article.title,
                "summary": article.summary,
            }
            for article in related_articles
        ],
        "similar_tickets": [
            {
                "id": ticket.id,
                "ticket_number": ticket.ticket_number,
                "title": ticket.title,
                "status": ticket.status,
            }
            for ticket in similar_tickets
        ],
        "next_actions": [
            "Проверить связанные активы и сервисы.",
            "Уточнить влияние на пользователей и масштаб инцидента.",
            "Применить инструкцию из базы знаний и зафиксировать результат.",
        ],
        "created_at": suggestion.created_at,
    }


def get_suggestions_for_ticket(db: Session, ticket_id: str) -> list[dict[str, object]]:
    suggestions = db.scalars(
        select(AiSuggestion).where(AiSuggestion.ticket_id == ticket_id).order_by(AiSuggestion.created_at.desc())
    ).all()
    result: list[dict[str, object]] = []
    for suggestion in suggestions:
        article = db.scalar(select(KnowledgeArticle).where(KnowledgeArticle.id == suggestion.recommended_article_id)) if suggestion.recommended_article_id else None
        result.append(
            {
                "id": suggestion.id,
                "ticket_id": suggestion.ticket_id,
                "input_text": suggestion.input_text,
                "recommended_category": suggestion.recommended_category,
                "recommended_priority": suggestion.recommended_priority,
                "recommended_asset_type": suggestion.recommended_asset_type,
                "recommended_article_id": suggestion.recommended_article_id,
                "summary": suggestion.summary,
                "possible_cause": suggestion.possible_cause,
                "suggested_solution": suggestion.suggested_solution,
                "recommended_assignee": suggestion.recommended_assignee,
                "confidence": suggestion.confidence,
                "related_articles": [
                    {
                        "id": article.id,
                        "article_number": article.article_number,
                        "title": article.title,
                        "summary": article.summary,
                    }
                ]
                if article
                else [],
                "similar_tickets": [
                    {
                        "id": suggestion.ticket_id,
                        "ticket_number": None,
                        "title": "Текущая заявка",
                        "status": "IN_PROGRESS",
                    }
                ]
                if suggestion.ticket_id
                else [],
                "next_actions": [
                    "Сверить рекомендации с текущим SLA.",
                    "Применить решение и добавить комментарий в заявку.",
                    "Если решение типовое, создать или обновить статью в базе знаний.",
                ],
                "created_at": suggestion.created_at,
            }
        )
    return result


def create_article_from_ticket(db: Session, ticket: Ticket, author_name: str) -> KnowledgeArticle:
    category_id = db.scalars(select(KnowledgeCategory.id).order_by(KnowledgeCategory.created_at.asc())).first()
    asset_type = db.scalar(select(Asset.asset_type).where(Asset.id == ticket.asset_id)) if ticket.asset_id else None
    article = KnowledgeArticle(
        id=_uuid(),
        article_number=next_article_number(db),
        title=f"Решение: {ticket.title}",
        summary=f"Инструкция, сформированная из заявки {ticket.ticket_number or ticket.id}.",
        content=(
            "Симптомы:\n"
            f"- {ticket.description or ticket.title}\n\n"
            "Шаги решения:\n"
            "1. Подтвердить влияние и приоритет.\n"
            "2. Проверить связанный актив/сервис.\n"
            "3. Применить корректирующие действия и зафиксировать результат.\n"
        ),
        category_id=category_id,
        ticket_category=ticket.category,
        asset_type=asset_type,
        tags=_join_tags([ticket.category.lower(), ticket.priority.lower(), "ticket-derived"]),
        status="draft",
        visibility="internal",
        author_name=author_name,
        helpful_count=0,
        not_helpful_count=0,
        published_at=None,
    )
    db.add(article)
    db.commit()
    db.refresh(article)
    return article


def search_articles(db: Session, query: str) -> list[KnowledgeArticle]:
    pattern = f"%{query.lower()}%"
    return db.scalars(
        select(KnowledgeArticle)
        .where(
            or_(
                func.lower(KnowledgeArticle.title).like(pattern),
                func.lower(KnowledgeArticle.summary).like(pattern),
                func.lower(KnowledgeArticle.content).like(pattern),
                func.lower(KnowledgeArticle.tags).like(pattern),
            )
        )
        .order_by(KnowledgeArticle.helpful_count.desc(), KnowledgeArticle.created_at.desc())
    ).all()


def article_payload(article: KnowledgeArticle, category_name: str | None = None) -> dict[str, object]:
    return {
        "id": article.id,
        "article_number": article.article_number,
        "title": article.title,
        "summary": article.summary,
        "content": article.content,
        "category_id": article.category_id,
        "category_name": category_name,
        "ticket_category": article.ticket_category,
        "asset_type": article.asset_type,
        "tags": _split_tags(article.tags),
        "status": article.status,
        "visibility": article.visibility,
        "author_name": article.author_name,
        "helpful_count": article.helpful_count,
        "not_helpful_count": article.not_helpful_count,
        "created_at": article.created_at,
        "updated_at": article.updated_at,
        "published_at": article.published_at,
    }
