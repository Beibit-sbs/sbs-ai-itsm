from __future__ import annotations

import re
import uuid
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import inspect, select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from app.models.ticket import Ticket
from app.models.ticket_category import TicketCategory
from app.models.ticket_comment import TicketComment
from app.models.ticket_history import TicketHistory
from app.models.ticket_priority import TicketPriority
from app.models.ticket_status import TicketStatus
from app.models.tenant import Tenant


def _uuid() -> str:
    return str(uuid.uuid4())


def _now() -> datetime:
    return datetime.now(UTC)


def _minutes(minutes: int) -> timedelta:
    return timedelta(minutes=minutes)


def _as_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


@dataclass(frozen=True)
class DemoTicketSeed:
    ticket_number: str
    title: str
    description: str
    requester_name: str
    requester_email: str
    department: str
    location: str
    category: str
    priority: str
    status: str
    assignee_name: str | None
    created_minutes_ago: int
    response_minutes: int
    sla_due_delta_minutes: int
    initial_comment: str


CATEGORY_DEFS = [
    {"code": "NETWORK_INTERNET", "name": "Сеть / Интернет", "description": "Обращения по проводному и беспроводному интернету.", "color": "#5db3ff", "sort_order": 1},
    {"code": "HARDWARE_WORKSTATION", "name": "Рабочее место", "description": "Проблемы с компьютером, периферией и рабочим местом.", "color": "#7ad7ff", "sort_order": 2},
    {"code": "PRINTING", "name": "Печать", "description": "Принтеры, сканеры и очереди печати.", "color": "#ffb56e", "sort_order": 3},
    {"code": "ACCESS_PLATONUS", "name": "Доступы / Platonus", "description": "Доступ к Platonus и учётным записям.", "color": "#40a8ff", "sort_order": 4},
    {"code": "ACCESS_MOODLE", "name": "Доступы / Moodle", "description": "Вопросы по Moodle и учебным сервисам.", "color": "#40a8ff", "sort_order": 5},
    {"code": "SOFTWARE_INSTALL", "name": "Установка ПО", "description": "Запросы на установку и настройку программ.", "color": "#33c391", "sort_order": 6},
    {"code": "ACCOUNT_PASSWORD", "name": "Пароли / Учетные записи", "description": "Сброс паролей и блокировки аккаунтов.", "color": "#ffb56e", "sort_order": 7},
    {"code": "MAIL", "name": "Почта", "description": "Почтовые клиенты и почтовые ящики.", "color": "#8fa6bb", "sort_order": 8},
    {"code": "AV_PROJECTOR", "name": "Проектор / Презентации", "description": "Аудио-видео техника и переговорные.", "color": "#c7e6ff", "sort_order": 9},
    {"code": "NETWORK_WIFI", "name": "Сеть / Wi‑Fi", "description": "Беспроводная сеть и точки доступа.", "color": "#5db3ff", "sort_order": 10},
    {"code": "PROCUREMENT", "name": "Закупка / Новый ноутбук", "description": "Заявки на новый ноутбук и обновление парка.", "color": "#91ffd0", "sort_order": 11},
    {"code": "SECURITY_PHISHING", "name": "Безопасность / Фишинг", "description": "Подозрительные письма и инциденты ИБ.", "color": "#ff7777", "sort_order": 12},
]

PRIORITY_DEFS = [
    {"code": "LOW", "name": "Низкий", "description": "Может ждать без заметного влияния на работу.", "color": "#91ffd0", "sort_order": 1},
    {"code": "MEDIUM", "name": "Средний", "description": "Стандартная заявка без критического простоя.", "color": "#c7e6ff", "sort_order": 2},
    {"code": "HIGH", "name": "Высокий", "description": "Существенно влияет на пользователей или сервис.", "color": "#ffb56e", "sort_order": 3},
    {"code": "CRITICAL", "name": "Критический", "description": "Блокирует работу подразделения или несёт риск безопасности.", "color": "#ff7777", "sort_order": 4},
]

STATUS_DEFS = [
    {"code": "NEW", "name": "Новая", "description": "Только что создана и ждёт первичного триажа.", "color": "#8fa6bb", "sort_order": 1, "is_closed": False},
    {"code": "TRIAGE", "name": "Разбор", "description": "Классифицирована и готова к назначению.", "color": "#5db3ff", "sort_order": 2, "is_closed": False},
    {"code": "TRIAGED", "name": "Оттриажена", "description": "Legacy статус: оттриажена.", "color": "#5db3ff", "sort_order": 3, "is_closed": False},
    {"code": "ASSIGNED", "name": "Назначена", "description": "Передана исполнителю.", "color": "#7ad7ff", "sort_order": 3, "is_closed": False},
    {"code": "IN_PROGRESS", "name": "В работе", "description": "Исполнитель работает над заявкой.", "color": "#40a8ff", "sort_order": 4, "is_closed": False},
    {"code": "WAITING_USER", "name": "Ожидаем пользователя", "description": "Требуются уточнения или действия от пользователя.", "color": "#ffb56e", "sort_order": 5, "is_closed": False},
    {"code": "WAITING_VENDOR", "name": "Ожидает поставщика", "description": "Ожидаются действия внешнего поставщика.", "color": "#d9a56f", "sort_order": 6, "is_closed": False},
    {"code": "RESOLVED", "name": "Решена", "description": "Проблема устранена, ждёт подтверждения.", "color": "#33c391", "sort_order": 6, "is_closed": True},
    {"code": "CLOSED", "name": "Закрыта", "description": "Заявка завершена и закрыта.", "color": "#2f8f66", "sort_order": 7, "is_closed": True},
    {"code": "REOPENED", "name": "Переоткрыта", "description": "Пользователь вернул заявку в работу.", "color": "#ff7777", "sort_order": 8, "is_closed": False},
    {"code": "CANCELLED", "name": "Отменена", "description": "Заявка отменена.", "color": "#8e8f99", "sort_order": 9, "is_closed": True},
]

DEMO_TICKETS: list[DemoTicketSeed] = [
    DemoTicketSeed("SD-1001", "Не работает интернет в кабинете 1113", "У сотрудников пропал доступ к внешним ресурсам, интернета нет только в одном кабинете.", "Ирина Соколова", "irina.sokolova@sbs.local", "Учебный центр", "Корпус A / Кабинет 1113", "NETWORK_INTERNET", "HIGH", "IN_PROGRESS", "Сетевой инженер", 220, 18, 180, "Проверяем DHCP, коммутатор и точку доступа на этаже."),
    DemoTicketSeed("SD-1002", "Не включается компьютер на рабочем месте", "ПК не реагирует на кнопку питания, индикаторы не загораются.", "Антон Павлов", "anton.pavlov@sbs.local", "Бухгалтерия", "Офис / Этаж 3 / Рабочее место 3-08", "HARDWARE_WORKSTATION", "MEDIUM", "TRIAGED", "Инженер поддержки", 510, 12, 300, "Запланировали проверку БП и кабеля питания на месте."),
    DemoTicketSeed("SD-1003", "Проблема с принтером в отделе кадров", "Принтер зажёвывает бумагу и не печатает задания из очереди.", "Мария Ковалева", "maria.kovaleva@sbs.local", "HR", "Офис / Этаж 2 / Копировальный узел", "PRINTING", "MEDIUM", "ASSIGNED", "Специалист по печати", 430, 24, 360, "Проверим ролики подачи и очередь печати."),
    DemoTicketSeed("SD-1004", "Нет доступа к Platonus", "Пользователь не проходит авторизацию в учебную систему.", "Данияр Садыков", "daniyar.sadykov@sbs.local", "Студенческий офис", "Филиал / Приёмная", "ACCESS_PLATONUS", "HIGH", "WAITING_USER", "Специалист по доступам", 960, 35, 240, "Ожидаем корректный логин от пользователя для сверки учётной записи."),
    DemoTicketSeed("SD-1005", "Не работает Moodle", "Страница обучения открывается, но курсы не загружаются.", "Алия Нургалиева", "aliya.nurgalieva@sbs.local", "Учебный отдел", "Удалённо / Домашний офис", "ACCESS_MOODLE", "HIGH", "RESOLVED", "Системный администратор", 1440, 20, 180, "Кеш и права на курс обновлены, доступ восстановлен."),
    DemoTicketSeed("SD-1006", "Нужна установка ПО для подготовки отчёта", "Пользователю требуется установка PDF-редактора и корпоративного клиента.", "Сергей Ильин", "sergey.ilyin@sbs.local", "Финансы", "Офис / Этаж 4 / Рабочее место 4-14", "SOFTWARE_INSTALL", "LOW", "CLOSED", "Инженер поддержки", 2100, 40, 720, "ПО установлено, доступ подтверждён пользователем."),
    DemoTicketSeed("SD-1007", "Забыли пароль от учётной записи", "Сотрудник не может войти после смены устройства.", "Ольга Смирнова", "olga.smirnova@sbs.local", "Продажи", "Офис / Этаж 1 / Ресепшен", "ACCOUNT_PASSWORD", "CRITICAL", "REOPENED", "Service Desk Lead", 300, 9, 90, "Пользователь подтвердил личность, ожидаем завершения повторного выпуска доступа."),
    DemoTicketSeed("SD-1008", "Не открывается почта на ноутбуке", "Outlook показывает ошибку подключения к серверу и не синхронизирует письма.", "Ерлан Бек", "erlan.bek@sbs.local", "Маркетинг", "Удалённо / Алматы", "MAIL", "MEDIUM", "NEW", None, 85, 0, 420, "Ожидает первичного триажа."),
    DemoTicketSeed("SD-1009", "Проблема с проектором в переговорной", "Сигнал с ноутбука есть, но изображение на проекторе не выводится.", "Айгерим Тлеуберген", "aigerim.tleubergen@sbs.local", "Операционный блок", "Офис / Переговорная 2", "AV_PROJECTOR", "LOW", "TRIAGED", "AV-инженер", 720, 16, 480, "Проверим HDMI, переключатель источника и батареи пульта."),
    DemoTicketSeed("SD-1010", "Нет доступа к Wi‑Fi в зоне коворкинга", "Устройства видят сеть, но не получают IP-адрес.", "Руслан Ахметов", "ruslan.akhmetov@sbs.local", "ИТ", "Офис / Коворкинг / 5 этаж", "NETWORK_WIFI", "HIGH", "ASSIGNED", "Сетевой инженер", 265, 11, 150, "Проверяем точку доступа и диапазон DHCP для зоны."),
    DemoTicketSeed("SD-1011", "Заявка на новый ноутбук для аналитика", "Нужен новый ноутбук для сотрудника, текущий вышел из строя.", "Жанна Алиева", "zhanna.alieva@sbs.local", "Аналитика", "Офис / Этаж 6 / Рабочее место 6-21", "PROCUREMENT", "LOW", "NEW", None, 35, 0, 960, "Передано на согласование и инвентарный подбор."),
    DemoTicketSeed("SD-1012", "Подозрение на фишинговое письмо", "Пользователь получил письмо с подозрительной ссылкой и просьбой срочно сменить пароль.", "Никита Егоров", "nikita.egorov@sbs.local", "Безопасность", "Удалённо / Домашний офис", "SECURITY_PHISHING", "CRITICAL", "IN_PROGRESS", "Специалист ИБ", 145, 7, 60, "Письмо изолировано, просим не переходить по ссылке и не вводить пароль."),
]


def _build_lookup(definitions: Iterable[dict[str, object]]) -> dict[str, dict[str, object]]:
    return {str(item["code"]): item for item in definitions}


def ensure_service_desk_schema(engine: Engine) -> None:
    inspector = inspect(engine)
    existing_columns = {column["name"] for column in inspector.get_columns("tickets")}
    existing_comment_columns = {column["name"] for column in inspector.get_columns("ticket_comments")}
    ddl_map = {
        "ticket_number": "ALTER TABLE tickets ADD COLUMN ticket_number VARCHAR(32)",
        "title": "ALTER TABLE tickets ADD COLUMN title VARCHAR(255)",
        "requester_email": "ALTER TABLE tickets ADD COLUMN requester_email VARCHAR(255)",
        "department": "ALTER TABLE tickets ADD COLUMN department VARCHAR(200)",
        "location": "ALTER TABLE tickets ADD COLUMN location VARCHAR(200)",
        "sla_due_at": "ALTER TABLE tickets ADD COLUMN sla_due_at TIMESTAMP",
        "asset_id": "ALTER TABLE tickets ADD COLUMN asset_id VARCHAR(36)",
        "sla_policy_id": "ALTER TABLE tickets ADD COLUMN sla_policy_id VARCHAR(36)",
        "response_due_at": "ALTER TABLE tickets ADD COLUMN response_due_at TIMESTAMP",
        "resolution_due_at": "ALTER TABLE tickets ADD COLUMN resolution_due_at TIMESTAMP",
        "sla_status": "ALTER TABLE tickets ADD COLUMN sla_status VARCHAR(32)",
        "resolved_at": "ALTER TABLE tickets ADD COLUMN resolved_at TIMESTAMP",
        "closed_at": "ALTER TABLE tickets ADD COLUMN closed_at TIMESTAMP",
        "reopened_at": "ALTER TABLE tickets ADD COLUMN reopened_at TIMESTAMP",
        "satisfaction_score": "ALTER TABLE tickets ADD COLUMN satisfaction_score INTEGER",
        "reopen_reason": "ALTER TABLE tickets ADD COLUMN reopen_reason TEXT",
        "requester_id": "ALTER TABLE tickets ADD COLUMN requester_id VARCHAR(36)",
        "assignee_id": "ALTER TABLE tickets ADD COLUMN assignee_id VARCHAR(36)",
    }
    comment_ddl_map = {
        "author_id": "ALTER TABLE ticket_comments ADD COLUMN author_id VARCHAR(36)",
        "is_internal": "ALTER TABLE ticket_comments ADD COLUMN is_internal BOOLEAN DEFAULT FALSE",
    }

    with engine.begin() as connection:
        for column_name, ddl in ddl_map.items():
            if column_name not in existing_columns:
                connection.exec_driver_sql(ddl)
        for column_name, ddl in comment_ddl_map.items():
            if column_name not in existing_comment_columns:
                connection.exec_driver_sql(ddl)

        if "subject" in existing_columns:
            connection.exec_driver_sql(
                """
                UPDATE tickets
                SET
                    ticket_number = COALESCE(ticket_number, 'LEG-' || id),
                    title = COALESCE(title, subject),
                    requester_email = COALESCE(requester_email, 'unknown@sbs.local'),
                    department = COALESCE(department, 'Legacy'),
                    location = COALESCE(location, 'Legacy Office'),
                    sla_due_at = COALESCE(sla_due_at, created_at)
                WHERE ticket_number IS NULL OR title IS NULL OR requester_email IS NULL OR department IS NULL OR location IS NULL OR sla_due_at IS NULL
                """
            )


def seed_service_desk_demo_data(db: Session) -> None:
    tenant = db.scalar(select(Tenant).where(Tenant.slug == "demo-tenant"))
    if tenant is None:
        return

    if db.scalar(select(TicketCategory.id)) is None:
        db.add_all([TicketCategory(id=_uuid(), **definition) for definition in CATEGORY_DEFS])

    if db.scalar(select(TicketPriority.id)) is None:
        db.add_all([TicketPriority(id=_uuid(), **definition) for definition in PRIORITY_DEFS])

    if db.scalar(select(TicketStatus.id)) is None:
        db.add_all([TicketStatus(id=_uuid(), **definition) for definition in STATUS_DEFS])

    existing_numbers = set(db.scalars(select(Ticket.ticket_number)).all())
    base_time = _now()

    for seed in DEMO_TICKETS:
        if seed.ticket_number in existing_numbers:
            continue

        created_at = base_time - _minutes(seed.created_minutes_ago)
        response_at = created_at + _minutes(seed.response_minutes) if seed.response_minutes else created_at
        sla_due_at = created_at + _minutes(seed.sla_due_delta_minutes)

        ticket = Ticket(
            id=_uuid(),
            tenant_id=tenant.id,
            ticket_number=seed.ticket_number,
            title=seed.title,
            description=seed.description,
            requester_name=seed.requester_name,
            requester_email=seed.requester_email,
            department=seed.department,
            location=seed.location,
            category=seed.category,
            priority=seed.priority,
            status=seed.status,
            assignee_name=seed.assignee_name,
            sla_due_at=sla_due_at,
            created_at=created_at,
            updated_at=response_at,
        )
        db.add(ticket)
        db.flush()
        db.add_all(
            [
                TicketHistory(
                    id=_uuid(),
                    ticket_id=ticket.id,
                    actor_name="SBS Desk Bot",
                    event_type="created",
                    field_name=None,
                    old_value=None,
                    new_value=seed.title,
                    message=f"Заявка {seed.ticket_number} создана в системе.",
                    created_at=created_at,
                ),
                TicketHistory(
                    id=_uuid(),
                    ticket_id=ticket.id,
                    actor_name=seed.assignee_name or "SBS Desk Bot",
                    event_type="status_changed",
                    field_name="status",
                    old_value="NEW",
                    new_value=seed.status,
                    message=f"Статус изменён на {seed.status}.",
                    created_at=response_at,
                ),
                TicketComment(
                    id=_uuid(),
                    ticket_id=ticket.id,
                    author_name=seed.assignee_name or "SBS Desk Bot",
                    author_role="service_desk",
                    body=seed.initial_comment,
                    created_at=response_at + _minutes(10),
                ),
            ]
        )

    db.commit()


def calculate_response_minutes(ticket: Ticket, history: list[TicketHistory]) -> int | None:
    status_events = [entry for entry in history if entry.event_type == "status_changed" and entry.old_value == "NEW"]
    if not status_events:
        return None
    first_event = min(status_events, key=lambda item: _as_utc(item.created_at) or datetime.now(UTC))
    first_event_at = _as_utc(first_event.created_at)
    ticket_created_at = _as_utc(ticket.created_at)
    if first_event_at is None or ticket_created_at is None:
        return None
    return max(0, int((first_event_at - ticket_created_at).total_seconds() // 60))


def build_ticket_summary(ticket: Ticket, category_label: str | None = None, priority_label: str | None = None, status_label: str | None = None, response_minutes: int | None = None) -> dict[str, object]:
    return {
        "id": ticket.id,
        "ticket_number": ticket.ticket_number,
        "title": ticket.title,
        "description": ticket.description,
        "requester_name": ticket.requester_name,
        "requester_email": ticket.requester_email,
        "department": ticket.department,
        "location": ticket.location,
        "category": ticket.category,
        "category_label": category_label or ticket.category,
        "priority": ticket.priority,
        "priority_label": priority_label or ticket.priority,
        "status": ticket.status,
        "status_label": status_label or ticket.status,
        "assignee_name": ticket.assignee_name,
        "asset_id": ticket.asset_id,
        "sla_due_at": ticket.sla_due_at,
        "sla_policy_id": ticket.sla_policy_id,
        "response_due_at": ticket.response_due_at,
        "resolution_due_at": ticket.resolution_due_at,
        "sla_status": ticket.sla_status,
        "resolved_at": ticket.resolved_at,
        "satisfaction_score": ticket.satisfaction_score,
        "reopen_reason": ticket.reopen_reason,
        "created_at": ticket.created_at,
        "updated_at": ticket.updated_at,
        "response_minutes": response_minutes,
    }


def next_ticket_number(db: Session) -> str:
    numbers = [str(number) for number in db.scalars(select(Ticket.ticket_number)).all() if number]
    max_value = 1000
    for number in numbers:
        match = re.search(r"(\d+)$", number)
        if match:
            max_value = max(max_value, int(match.group(1)))
    return f"SD-{max_value + 1:04d}"
