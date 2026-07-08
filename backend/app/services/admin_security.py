from __future__ import annotations

from sqlalchemy import inspect
from sqlalchemy.engine import Engine


def ensure_admin_security_schema(engine: Engine) -> None:
    inspector = inspect(engine)
    existing_tables = set(inspector.get_table_names())

    user_columns = set()
    role_columns = set()
    permission_columns = set()
    tenant_columns = set()

    if "users" in existing_tables:
        user_columns = {column["name"] for column in inspector.get_columns("users")}
    if "roles" in existing_tables:
        role_columns = {column["name"] for column in inspector.get_columns("roles")}
    if "permissions" in existing_tables:
        permission_columns = {column["name"] for column in inspector.get_columns("permissions")}
    if "tenants" in existing_tables:
        tenant_columns = {column["name"] for column in inspector.get_columns("tenants")}

    with engine.begin() as connection:
        user_ddls = {
            "position": "ALTER TABLE users ADD COLUMN position VARCHAR(200)",
            "department": "ALTER TABLE users ADD COLUMN department VARCHAR(200)",
            "phone": "ALTER TABLE users ADD COLUMN phone VARCHAR(64)",
            "is_superuser": "ALTER TABLE users ADD COLUMN is_superuser BOOLEAN DEFAULT 0",
            "last_login_at": "ALTER TABLE users ADD COLUMN last_login_at TIMESTAMP",
            "updated_at": "ALTER TABLE users ADD COLUMN updated_at TIMESTAMP",
        }
        role_ddls = {
            "code": "ALTER TABLE roles ADD COLUMN code VARCHAR(120)",
            "is_system": "ALTER TABLE roles ADD COLUMN is_system BOOLEAN DEFAULT 0",
            "updated_at": "ALTER TABLE roles ADD COLUMN updated_at TIMESTAMP",
        }
        permission_ddls = {
            "name": "ALTER TABLE permissions ADD COLUMN name VARCHAR(200)",
            "module": "ALTER TABLE permissions ADD COLUMN module VARCHAR(64)",
        }
        tenant_ddls = {
            "updated_at": "ALTER TABLE tenants ADD COLUMN updated_at TIMESTAMP",
        }

        for column_name, ddl in user_ddls.items():
            if column_name not in user_columns:
                connection.exec_driver_sql(ddl)
        for column_name, ddl in role_ddls.items():
            if column_name not in role_columns:
                connection.exec_driver_sql(ddl)
        for column_name, ddl in permission_ddls.items():
            if column_name not in permission_columns:
                connection.exec_driver_sql(ddl)
        for column_name, ddl in tenant_ddls.items():
            if column_name not in tenant_columns:
                connection.exec_driver_sql(ddl)

        if "code" not in role_columns:
            connection.exec_driver_sql("UPDATE roles SET code = name WHERE code IS NULL")
        if "updated_at" not in user_columns:
            connection.exec_driver_sql("UPDATE users SET updated_at = created_at WHERE updated_at IS NULL")
        if "updated_at" not in tenant_columns:
            connection.exec_driver_sql("UPDATE tenants SET updated_at = created_at WHERE updated_at IS NULL")
        if "updated_at" not in role_columns:
            connection.exec_driver_sql("UPDATE roles SET updated_at = created_at WHERE updated_at IS NULL")
