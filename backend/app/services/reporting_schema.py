from __future__ import annotations

from sqlalchemy import Engine, inspect, text


def ensure_reporting_schema(engine: Engine) -> None:
    if engine.dialect.name != 'sqlite':
        return

    with engine.begin() as connection:
        inspector = inspect(connection)
        table_names = set(inspector.get_table_names())
        if 'saved_reports' not in table_names:
            connection.execute(
                text(
                    'CREATE TABLE saved_reports ('
                    'id VARCHAR(36) PRIMARY KEY, '
                    'tenant_id VARCHAR(36) NULL, '
                    'name VARCHAR(255) NOT NULL, '
                    'report_type VARCHAR(120) NOT NULL, '
                    'filters_json TEXT NOT NULL, '
                    'created_by VARCHAR(255) NOT NULL, '
                    'created_at TIMESTAMP NOT NULL, '
                    'updated_at TIMESTAMP NOT NULL'
                    ')'
                )
            )
        if 'report_snapshots' not in table_names:
            connection.execute(
                text(
                    'CREATE TABLE report_snapshots ('
                    'id VARCHAR(36) PRIMARY KEY, '
                    'tenant_id VARCHAR(36) NULL, '
                    'report_type VARCHAR(120) NOT NULL, '
                    'period_from TIMESTAMP NULL, '
                    'period_to TIMESTAMP NULL, '
                    'payload_json TEXT NOT NULL, '
                    'created_at TIMESTAMP NOT NULL, '
                    'created_by VARCHAR(255) NOT NULL'
                    ')'
                )
            )
