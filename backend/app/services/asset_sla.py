from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import inspect, select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from app.models.asset import Asset
from app.models.asset_assignment import AssetAssignment
from app.models.asset_type import AssetType
from app.models.sla import SlaPolicy
from app.models.sla_event import SlaEvent
from app.models.ticket import Ticket
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


ASSET_TYPE_DEFS = [
    {"code": "LAPTOP", "name": "Ноутбуки"},
    {"code": "DESKTOP", "name": "Компьютеры"},
    {"code": "PRINTER", "name": "Принтеры"},
    {"code": "PROJECTOR", "name": "Проекторы"},
    {"code": "SERVER", "name": "Серверы"},
    {"code": "WIFI_AP", "name": "Wi‑Fi точки"},
    {"code": "SWITCH", "name": "Коммутаторы"},
    {"code": "INTERACTIVE_PANEL", "name": "Интерактивные панели"},
]

SLA_POLICY_DEFS = [
    {
        "priority": "LOW",
        "name": "Low SLA",
        "target_response_minutes": 480,
        "target_resolution_minutes": 4320,
        "response_minutes": 480,
        "resolution_minutes": 4320,
        "is_active": True,
        "status": "active",
        "breach_count": 0,
    },
    {
        "priority": "MEDIUM",
        "name": "Medium SLA",
        "target_response_minutes": 240,
        "target_resolution_minutes": 1440,
        "response_minutes": 240,
        "resolution_minutes": 1440,
        "is_active": True,
        "status": "active",
        "breach_count": 0,
    },
    {
        "priority": "HIGH",
        "name": "High SLA",
        "target_response_minutes": 60,
        "target_resolution_minutes": 480,
        "response_minutes": 60,
        "resolution_minutes": 480,
        "is_active": True,
        "status": "active",
        "breach_count": 0,
    },
    {
        "priority": "CRITICAL",
        "name": "Critical SLA",
        "target_response_minutes": 15,
        "target_resolution_minutes": 120,
        "response_minutes": 15,
        "resolution_minutes": 120,
        "is_active": True,
        "status": "active",
        "breach_count": 0,
    },
]


ASSET_SEEDS = [
    {"asset_tag": "AST-3001", "name": "Lenovo ThinkPad T14", "asset_type": "LAPTOP", "status": "in_use", "serial_number": "LTP-3001", "inventory_number": "INV-3001", "manufacturer": "Lenovo", "model": "ThinkPad T14 Gen 4", "location": "Moscow / HQ / Floor 4", "assigned_to_name": "Ирина Соколова", "assigned_to_email": "irina.sokolova@sbs.local", "department": "Учебный центр", "purchase_date": datetime(2024, 2, 14, tzinfo=UTC), "warranty_until": datetime(2027, 2, 14, tzinfo=UTC)},
    {"asset_tag": "AST-3002", "name": "HP EliteBook 840", "asset_type": "LAPTOP", "status": "in_use", "serial_number": "LTP-3002", "inventory_number": "INV-3002", "manufacturer": "HP", "model": "EliteBook 840 G10", "location": "Moscow / HQ / Floor 3", "assigned_to_name": "Антон Павлов", "assigned_to_email": "anton.pavlov@sbs.local", "department": "Бухгалтерия", "purchase_date": datetime(2024, 4, 12, tzinfo=UTC), "warranty_until": datetime(2027, 4, 12, tzinfo=UTC)},
    {"asset_tag": "AST-3003", "name": "Dell OptiPlex 7010", "asset_type": "DESKTOP", "status": "in_use", "serial_number": "DTP-3003", "inventory_number": "INV-3003", "manufacturer": "Dell", "model": "OptiPlex 7010", "location": "Moscow / HQ / Floor 2", "assigned_to_name": "Мария Ковалева", "assigned_to_email": "maria.kovaleva@sbs.local", "department": "HR", "purchase_date": datetime(2023, 11, 2, tzinfo=UTC), "warranty_until": datetime(2026, 11, 2, tzinfo=UTC)},
    {"asset_tag": "AST-3004", "name": "Canon i-SENSYS", "asset_type": "PRINTER", "status": "in_repair", "serial_number": "PRT-3004", "inventory_number": "INV-3004", "manufacturer": "Canon", "model": "i-SENSYS MF752Cdw", "location": "Moscow / Vendor Repair", "assigned_to_name": "HR Printer", "assigned_to_email": None, "department": "HR", "purchase_date": datetime(2022, 8, 8, tzinfo=UTC), "warranty_until": datetime(2025, 8, 8, tzinfo=UTC)},
    {"asset_tag": "AST-3005", "name": "Epson EB-2250U", "asset_type": "PROJECTOR", "status": "in_use", "serial_number": "AV-3005", "inventory_number": "INV-3005", "manufacturer": "Epson", "model": "EB-2250U", "location": "Moscow / Meeting Room 2", "assigned_to_name": "Переговорная 2", "assigned_to_email": None, "department": "Operations", "purchase_date": datetime(2021, 6, 1, tzinfo=UTC), "warranty_until": datetime(2026, 6, 1, tzinfo=UTC)},
    {"asset_tag": "AST-3006", "name": "Dell PowerEdge R740", "asset_type": "SERVER", "status": "in_use", "serial_number": "SRV-3006", "inventory_number": "INV-3006", "manufacturer": "Dell", "model": "PowerEdge R740", "location": "Datacenter / Rack 12", "assigned_to_name": "Infrastructure", "assigned_to_email": None, "department": "ИТ", "purchase_date": datetime(2022, 1, 20, tzinfo=UTC), "warranty_until": datetime(2026, 1, 20, tzinfo=UTC)},
    {"asset_tag": "AST-3007", "name": "Ubiquiti U6-Lite", "asset_type": "WIFI_AP", "status": "in_use", "serial_number": "WIFI-3007", "inventory_number": "INV-3007", "manufacturer": "Ubiquiti", "model": "UniFi 6 Lite", "location": "Moscow / HQ / Floor 5", "assigned_to_name": "Network Team", "assigned_to_email": None, "department": "ИТ", "purchase_date": datetime(2023, 5, 15, tzinfo=UTC), "warranty_until": datetime(2026, 5, 15, tzinfo=UTC)},
    {"asset_tag": "AST-3008", "name": "Cisco Catalyst 9200", "asset_type": "SWITCH", "status": "in_use", "serial_number": "SWT-3008", "inventory_number": "INV-3008", "manufacturer": "Cisco", "model": "Catalyst 9200", "location": "Moscow / HQ / Network Closet", "assigned_to_name": "Network Team", "assigned_to_email": None, "department": "ИТ", "purchase_date": datetime(2022, 9, 10, tzinfo=UTC), "warranty_until": datetime(2027, 9, 10, tzinfo=UTC)},
    {"asset_tag": "AST-3009", "name": "Samsung Flip", "asset_type": "INTERACTIVE_PANEL", "status": "in_stock", "serial_number": "PAN-3009", "inventory_number": "INV-3009", "manufacturer": "Samsung", "model": "WM55B", "location": "Storage / Aisle 3", "assigned_to_name": None, "assigned_to_email": None, "department": "Operations", "purchase_date": datetime(2024, 1, 12, tzinfo=UTC), "warranty_until": datetime(2027, 1, 12, tzinfo=UTC)},
    {"asset_tag": "AST-3010", "name": "Lenovo ThinkCentre M70", "asset_type": "DESKTOP", "status": "in_use", "serial_number": "DTP-3010", "inventory_number": "INV-3010", "manufacturer": "Lenovo", "model": "ThinkCentre M70s", "location": "Moscow / HQ / Floor 1", "assigned_to_name": "Ольга Смирнова", "assigned_to_email": "olga.smirnova@sbs.local", "department": "Продажи", "purchase_date": datetime(2023, 3, 11, tzinfo=UTC), "warranty_until": datetime(2026, 3, 11, tzinfo=UTC)},
    {"asset_tag": "AST-3011", "name": "Brother HL-L6400", "asset_type": "PRINTER", "status": "in_use", "serial_number": "PRT-3011", "inventory_number": "INV-3011", "manufacturer": "Brother", "model": "HL-L6400DW", "location": "Moscow / HQ / Floor 2", "assigned_to_name": "Кадровый отдел", "assigned_to_email": None, "department": "HR", "purchase_date": datetime(2021, 10, 5, tzinfo=UTC), "warranty_until": datetime(2026, 10, 5, tzinfo=UTC)},
    {"asset_tag": "AST-3012", "name": "HP ProBook 450", "asset_type": "LAPTOP", "status": "broken", "serial_number": "LTP-3012", "inventory_number": "INV-3012", "manufacturer": "HP", "model": "ProBook 450 G9", "location": "Repair Shelf", "assigned_to_name": "Жанна Алиева", "assigned_to_email": "zhanna.alieva@sbs.local", "department": "Аналитика", "purchase_date": datetime(2022, 7, 17, tzinfo=UTC), "warranty_until": datetime(2025, 7, 17, tzinfo=UTC)},
    {"asset_tag": "AST-3013", "name": "Cisco Aironet 1830", "asset_type": "WIFI_AP", "status": "in_use", "serial_number": "WIFI-3013", "inventory_number": "INV-3013", "manufacturer": "Cisco", "model": "Aironet 1830", "location": "Moscow / HQ / Floor 3", "assigned_to_name": "Network Team", "assigned_to_email": None, "department": "ИТ", "purchase_date": datetime(2023, 9, 8, tzinfo=UTC), "warranty_until": datetime(2026, 9, 8, tzinfo=UTC)},
    {"asset_tag": "AST-3014", "name": "Microsoft Surface Laptop", "asset_type": "LAPTOP", "status": "in_use", "serial_number": "LTP-3014", "inventory_number": "INV-3014", "manufacturer": "Microsoft", "model": "Surface Laptop 5", "location": "Remote / Almaty", "assigned_to_name": "Ерлан Бек", "assigned_to_email": "erlan.bek@sbs.local", "department": "Маркетинг", "purchase_date": datetime(2023, 12, 18, tzinfo=UTC), "warranty_until": datetime(2026, 12, 18, tzinfo=UTC)},
    {"asset_tag": "AST-3015", "name": "HP EliteDisplay E243", "asset_type": "INTERACTIVE_PANEL", "status": "in_stock", "serial_number": "PAN-3015", "inventory_number": "INV-3015", "manufacturer": "HP", "model": "EliteDisplay E243", "location": "Storage / Display Area", "assigned_to_name": None, "assigned_to_email": None, "department": "Operations", "purchase_date": datetime(2023, 2, 20, tzinfo=UTC), "warranty_until": datetime(2026, 2, 20, tzinfo=UTC)},
    {"asset_tag": "AST-3016", "name": "Dell Latitude 5440", "asset_type": "LAPTOP", "status": "in_use", "serial_number": "LTP-3016", "inventory_number": "INV-3016", "manufacturer": "Dell", "model": "Latitude 5440", "location": "Moscow / HQ / Floor 6", "assigned_to_name": "Руслан Ахметов", "assigned_to_email": "ruslan.akhmetov@sbs.local", "department": "ИТ", "purchase_date": datetime(2024, 5, 10, tzinfo=UTC), "warranty_until": datetime(2027, 5, 10, tzinfo=UTC)},
    {"asset_tag": "AST-3017", "name": "Lenovo ThinkPad L14", "asset_type": "LAPTOP", "status": "in_use", "serial_number": "LTP-3017", "inventory_number": "INV-3017", "manufacturer": "Lenovo", "model": "ThinkPad L14", "location": "Moscow / HQ / Floor 2", "assigned_to_name": "Айгерим Тлеуберген", "assigned_to_email": "aigerim.tleubergen@sbs.local", "department": "Операционный блок", "purchase_date": datetime(2024, 6, 1, tzinfo=UTC), "warranty_until": datetime(2027, 6, 1, tzinfo=UTC)},
    {"asset_tag": "AST-3018", "name": "Intel NUC", "asset_type": "DESKTOP", "status": "in_use", "serial_number": "DTP-3018", "inventory_number": "INV-3018", "manufacturer": "Intel", "model": "NUC 12", "location": "Moscow / HQ / Reception", "assigned_to_name": "Никита Егоров", "assigned_to_email": "nikita.egorov@sbs.local", "department": "Безопасность", "purchase_date": datetime(2022, 12, 14, tzinfo=UTC), "warranty_until": datetime(2025, 12, 14, tzinfo=UTC)},
    {"asset_tag": "AST-3019", "name": "Xerox AltaLink", "asset_type": "PRINTER", "status": "maintenance", "serial_number": "PRT-3019", "inventory_number": "INV-3019", "manufacturer": "Xerox", "model": "AltaLink C8130", "location": "Service Bay", "assigned_to_name": "Printer Queue", "assigned_to_email": None, "department": "Support", "purchase_date": datetime(2021, 4, 9, tzinfo=UTC), "warranty_until": datetime(2026, 4, 9, tzinfo=UTC)},
    {"asset_tag": "AST-3020", "name": "HPE ProLiant DL380", "asset_type": "SERVER", "status": "in_use", "serial_number": "SRV-3020", "inventory_number": "INV-3020", "manufacturer": "HPE", "model": "ProLiant DL380 Gen10", "location": "Datacenter / Rack 4", "assigned_to_name": "Infrastructure", "assigned_to_email": None, "department": "ИТ", "purchase_date": datetime(2020, 8, 30, tzinfo=UTC), "warranty_until": datetime(2025, 8, 30, tzinfo=UTC)},
]


def _priority_policy_map(db: Session) -> dict[str, SlaPolicy]:
    return {policy.priority.upper(): policy for policy in db.scalars(select(SlaPolicy)).all()}


def ensure_asset_sla_schema(engine: Engine) -> None:
    inspector = inspect(engine)
    with engine.begin() as connection:
        existing_assets = {column["name"] for column in inspector.get_columns("assets")}
        existing_tickets = {column["name"] for column in inspector.get_columns("tickets")}
        existing_policies = {column["name"] for column in inspector.get_columns("sla_policies")}

        asset_columns = {
            "asset_type": "ALTER TABLE assets ADD COLUMN asset_type VARCHAR(120)",
            "owner_name": "ALTER TABLE assets ADD COLUMN owner_name VARCHAR(200)",
            "condition": "ALTER TABLE assets ADD COLUMN condition VARCHAR(32)",
            "description": "ALTER TABLE assets ADD COLUMN description TEXT",
            "status": "ALTER TABLE assets ADD COLUMN status VARCHAR(32)",
            "asset_tag": "ALTER TABLE assets ADD COLUMN asset_tag VARCHAR(32)",
            "serial_number": "ALTER TABLE assets ADD COLUMN serial_number VARCHAR(120)",
            "location": "ALTER TABLE assets ADD COLUMN location VARCHAR(200)",
            "name": "ALTER TABLE assets ADD COLUMN name VARCHAR(200)",
            "inventory_number": "ALTER TABLE assets ADD COLUMN inventory_number VARCHAR(80)",
            "manufacturer": "ALTER TABLE assets ADD COLUMN manufacturer VARCHAR(200)",
            "model": "ALTER TABLE assets ADD COLUMN model VARCHAR(200)",
            "assigned_to_name": "ALTER TABLE assets ADD COLUMN assigned_to_name VARCHAR(200)",
            "assigned_to_email": "ALTER TABLE assets ADD COLUMN assigned_to_email VARCHAR(255)",
            "department": "ALTER TABLE assets ADD COLUMN department VARCHAR(200)",
            "purchase_date": "ALTER TABLE assets ADD COLUMN purchase_date TIMESTAMP",
            "warranty_until": "ALTER TABLE assets ADD COLUMN warranty_until TIMESTAMP",
            "type": "ALTER TABLE assets ADD COLUMN type VARCHAR(120)",
        }
        ticket_columns = {
            "asset_id": "ALTER TABLE tickets ADD COLUMN asset_id VARCHAR(36)",
            "sla_policy_id": "ALTER TABLE tickets ADD COLUMN sla_policy_id VARCHAR(36)",
            "response_due_at": "ALTER TABLE tickets ADD COLUMN response_due_at TIMESTAMP",
            "resolution_due_at": "ALTER TABLE tickets ADD COLUMN resolution_due_at TIMESTAMP",
            "sla_status": "ALTER TABLE tickets ADD COLUMN sla_status VARCHAR(32)",
            "resolved_at": "ALTER TABLE tickets ADD COLUMN resolved_at TIMESTAMP",
        }
        policy_columns = {
            "response_minutes": "ALTER TABLE sla_policies ADD COLUMN response_minutes INTEGER",
            "resolution_minutes": "ALTER TABLE sla_policies ADD COLUMN resolution_minutes INTEGER",
            "is_active": "ALTER TABLE sla_policies ADD COLUMN is_active BOOLEAN",
        }

        for column_name, ddl in asset_columns.items():
            if column_name not in existing_assets:
                connection.exec_driver_sql(ddl)
        for column_name, ddl in ticket_columns.items():
            if column_name not in existing_tickets:
                connection.exec_driver_sql(ddl)
        for column_name, ddl in policy_columns.items():
            if column_name not in existing_policies:
                connection.exec_driver_sql(ddl)


def seed_asset_sla_demo_data(db: Session) -> None:
    tenant = db.scalar(select(Tenant).where(Tenant.slug == "demo-tenant"))
    if tenant is None:
        return

    if db.scalar(select(AssetType.id)) is None:
        db.add_all([AssetType(id=_uuid(), **definition) for definition in ASSET_TYPE_DEFS])

    existing_priorities = {
        policy.priority.upper()
        for policy in db.scalars(
            select(SlaPolicy).where(SlaPolicy.tenant_id == tenant.id)
        ).all()
    }
    db.add_all(
        [
            SlaPolicy(id=_uuid(), tenant_id=tenant.id, **definition)
            for definition in SLA_POLICY_DEFS
            if definition["priority"] not in existing_priorities
        ]
    )

    policy_map = _priority_policy_map(db)
    asset_map = {asset.asset_tag: asset for asset in db.scalars(select(Asset)).all()}
    if not asset_map:
        for seed in ASSET_SEEDS:
            asset = Asset(
                id=_uuid(),
                tenant_id=tenant.id,
                asset_tag=seed["asset_tag"],
                name=seed["name"],
                asset_type=seed["asset_type"],
                serial_number=seed["serial_number"],
                status=seed["status"],
                owner_name=seed["assigned_to_name"] or "Warehouse",
                location=seed["location"],
                condition="good" if seed["status"] != "broken" else "broken",
                description=f"Demo asset {seed['asset_tag']}",
            )
            db.add(asset)
            db.flush()
            db.add(
                AssetAssignment(
                    id=_uuid(),
                    asset_id=asset.id,
                    assigned_to_name=seed["assigned_to_name"] or "Warehouse",
                    assigned_to_email=seed["assigned_to_email"],
                    department=seed["department"],
                    location=seed["location"],
                    assigned_at=seed["purchase_date"],
                )
            )

    if db.scalar(select(SlaEvent.id)) is None:
        tickets = db.scalars(select(Ticket)).all()
        for ticket in tickets:
            policy = policy_map.get(ticket.priority)
            if policy is None:
                continue
            response_due_at = ticket.created_at + _minutes(policy.response_minutes)
            resolution_due_at = ticket.created_at + _minutes(policy.resolution_minutes)
            db.add(
                SlaEvent(
                    id=_uuid(),
                    ticket_id=ticket.id,
                    policy_id=policy.id,
                    response_due_at=response_due_at,
                    resolution_due_at=resolution_due_at,
                    responded_at=ticket.updated_at,
                    resolved_at=ticket.resolved_at if hasattr(ticket, "resolved_at") else None,
                    response_breached=ticket.response_due_at is not None and ticket.response_due_at < ticket.created_at,
                    resolution_breached=ticket.resolution_due_at is not None and ticket.resolution_due_at < ticket.created_at,
                )
            )

    db.commit()


def calculate_asset_health(asset: Asset) -> str:
    if asset.status in {"broken", "maintenance"}:
        return "problem"
    warranty_until = _as_utc(asset.warranty_until)
    if warranty_until and warranty_until <= _now() + _minutes(60 * 24 * 45):
        return "warranty_expiring"
    return "healthy"


def calculate_ticket_sla_status(ticket: Ticket) -> str:
    now = _now()
    response_due_at = _as_utc(ticket.response_due_at)
    resolution_due_at = _as_utc(ticket.resolution_due_at)
    if resolution_due_at and ticket.status not in {"RESOLVED", "CLOSED"} and resolution_due_at < now:
        return "BREACHED"
    if response_due_at and response_due_at < now and ticket.status in {"NEW", "TRIAGED"}:
        return "WARNING"
    return "OK"


def summarize_sla_overview(
    db: Session,
    tenant_id: str | None = None,
) -> dict[str, object]:
    ticket_statement = select(Ticket)
    asset_statement = select(Asset)
    if tenant_id is not None:
        ticket_statement = ticket_statement.where(Ticket.tenant_id == tenant_id)
        asset_statement = asset_statement.where(Asset.tenant_id == tenant_id)
    tickets = db.scalars(ticket_statement).all()
    assets = db.scalars(asset_statement).all()
    breached = [ticket for ticket in tickets if calculate_ticket_sla_status(ticket) == "BREACHED"]
    warning = [ticket for ticket in tickets if calculate_ticket_sla_status(ticket) == "WARNING"]
    problematic_assets = [asset for asset in assets if calculate_asset_health(asset) == "problem"]
    warranty_soon = [asset for asset in assets if _as_utc(asset.warranty_until) and _as_utc(asset.warranty_until) <= _now() + _minutes(60 * 24 * 45)]
    return {
        "total_tickets": len(tickets),
        "breached_tickets": len(breached),
        "warning_tickets": len(warning),
        "problematic_assets": len(problematic_assets),
        "warranty_expiring": len(warranty_soon),
    }
