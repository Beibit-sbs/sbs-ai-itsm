"""Reclassify unconfirmed legacy automation evidence.

Revision ID: 20260729_0070
Revises: 20260729_0069
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "20260729_0070"
down_revision: str | None = "20260729_0069"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _columns(inspector: sa.Inspector, table_name: str) -> set[str]:
    return {
        str(column["name"])
        for column in inspector.get_columns(table_name)
    }


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    tables = set(inspector.get_table_names())

    if "email_message_logs" in tables:
        columns = _columns(inspector, "email_message_logs")
        required = {
            "provider",
            "status",
            "accepted_at",
            "sent_at",
            "delivered_at",
            "error_message",
        }
        if required.issubset(columns):
            op.execute(
                sa.text(
                    """
                    UPDATE email_message_logs
                    SET status = 'SIMULATED',
                        accepted_at = NULL,
                        sent_at = NULL,
                        delivered_at = NULL,
                        error_message = 'No external email was sent'
                    WHERE provider = 'mock_automation'
                      AND status IN (
                          'ACCEPTED',
                          'DELIVERED',
                          'SENT',
                          'accepted',
                          'delivered',
                          'sent'
                      )
                    """
                )
            )

    action_columns: set[str] = set()
    if "automation_action_logs" in tables:
        action_columns = _columns(inspector, "automation_action_logs")
        if {"status", "action_type"}.issubset(action_columns):
            op.execute(
                sa.text(
                    """
                    UPDATE automation_action_logs
                    SET status = 'simulated'
                    WHERE status = 'success'
                      AND action_type IN (
                          'create_mock_email_log',
                          'send_mock_email',
                          'export_report_mock'
                      )
                    """
                )
            )
            op.execute(
                sa.text(
                    """
                    UPDATE automation_action_logs
                    SET status = 'skipped',
                        error_message = 'Legacy action did not confirm a side effect'
                    WHERE status = 'success'
                      AND action_type IN (
                          'assign_asset_responsible',
                          'attach_runbook',
                          'create_approval_request',
                          'create_audit_log',
                          'create_draft_article_from_ticket',
                          'create_task_note',
                          'request_asset_verification',
                          'run_saved_report'
                      )
                    """
                )
            )
        if {"status", "output_json"}.issubset(action_columns):
            op.execute(
                sa.text(
                    """
                    UPDATE automation_action_logs
                    SET status = 'simulated'
                    WHERE status = 'success'
                      AND output_json LIKE '%"result"%demo%'
                    """
                )
            )

    if "automation_runs" in tables:
        run_columns = _columns(inspector, "automation_runs")
        if {"status", "result_summary"}.issubset(run_columns):
            op.execute(
                sa.text(
                    """
                    UPDATE automation_runs
                    SET status = 'simulated',
                        error_message = NULL
                    WHERE status IN ('success', 'completed')
                      AND result_summary LIKE '%"seed"%true%'
                    """
                )
            )
        if {"status", "runbook_id", "finished_at"}.issubset(run_columns):
            op.execute(
                sa.text(
                    """
                    UPDATE automation_runs
                    SET status = 'manual_pending',
                        finished_at = NULL
                    WHERE status = 'success'
                      AND runbook_id IS NOT NULL
                    """
                )
            )
        if (
            {"id", "status"}.issubset(run_columns)
            and {
                "automation_run_id",
                "status",
            }.issubset(action_columns)
        ):
            op.execute(
                sa.text(
                    """
                    UPDATE automation_runs
                    SET status = 'simulated'
                    WHERE status = 'success'
                      AND EXISTS (
                          SELECT 1
                          FROM automation_action_logs
                          WHERE automation_action_logs.automation_run_id =
                                automation_runs.id
                            AND automation_action_logs.status = 'simulated'
                      )
                      AND NOT EXISTS (
                          SELECT 1
                          FROM automation_action_logs
                          WHERE automation_action_logs.automation_run_id =
                                automation_runs.id
                            AND automation_action_logs.status = 'success'
                      )
                    """
                )
            )
            op.execute(
                sa.text(
                    """
                    UPDATE automation_runs
                    SET status = 'skipped'
                    WHERE status = 'success'
                      AND EXISTS (
                          SELECT 1
                          FROM automation_action_logs
                          WHERE automation_action_logs.automation_run_id =
                                automation_runs.id
                            AND automation_action_logs.status = 'skipped'
                      )
                      AND NOT EXISTS (
                          SELECT 1
                          FROM automation_action_logs
                          WHERE automation_action_logs.automation_run_id =
                                automation_runs.id
                            AND automation_action_logs.status IN (
                                'success',
                                'simulated'
                            )
                      )
                    """
                )
            )
            op.execute(
                sa.text(
                    """
                    UPDATE automation_runs
                    SET status = 'partial'
                    WHERE status = 'success'
                      AND EXISTS (
                          SELECT 1
                          FROM automation_action_logs
                          WHERE automation_action_logs.automation_run_id =
                                automation_runs.id
                            AND automation_action_logs.status IN (
                                'simulated',
                                'skipped'
                            )
                      )
                    """
                )
            )

    if "runbook_executions" in tables:
        columns = _columns(inspector, "runbook_executions")
        if {
            "status",
            "result_summary",
            "completed_at",
        }.issubset(columns):
            op.execute(
                sa.text(
                    """
                    UPDATE runbook_executions
                    SET status = 'simulated',
                        completed_at = NULL
                    WHERE status = 'completed'
                      AND result_summary LIKE '%Demo%'
                    """
                )
            )


def downgrade() -> None:
    # Invalidated delivery, action, and completion evidence is not restorable.
    return
