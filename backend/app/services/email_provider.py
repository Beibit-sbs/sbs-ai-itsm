from __future__ import annotations

import uuid
from abc import ABC, abstractmethod
from datetime import UTC, datetime

from sqlalchemy.orm import Session

from app.models.email_message_log import EmailMessageLog


class BaseEmailProvider(ABC):
    provider_name = "base"

    @abstractmethod
    def send_email(self, db: Session, *, to_email: str, subject: str, body: str, related_ticket_id: str | None = None) -> EmailMessageLog:
        raise NotImplementedError


class MockEmailProvider(BaseEmailProvider):
    provider_name = "mock"

    def send_email(self, db: Session, *, to_email: str, subject: str, body: str, related_ticket_id: str | None = None) -> EmailMessageLog:
        now = datetime.now(UTC)
        log = EmailMessageLog(
            id=str(uuid.uuid4()),
            provider=self.provider_name,
            to_email=to_email,
            subject=subject,
            body=body,
            status="SENT",
            error_message=None,
            related_ticket_id=related_ticket_id,
            created_at=now,
            sent_at=now,
        )
        db.add(log)
        return log


class FutureSmtpProvider(BaseEmailProvider):
    provider_name = "future_smtp"

    def send_email(self, db: Session, *, to_email: str, subject: str, body: str, related_ticket_id: str | None = None) -> EmailMessageLog:
        now = datetime.now(UTC)
        log = EmailMessageLog(
            id=str(uuid.uuid4()),
            provider=self.provider_name,
            to_email=to_email,
            subject=subject,
            body=body,
            status="PENDING",
            error_message="SMTP provider is not configured in this stage",
            related_ticket_id=related_ticket_id,
            created_at=now,
            sent_at=None,
        )
        db.add(log)
        return log


class FutureZimbraProvider(BaseEmailProvider):
    provider_name = "future_zimbra"

    def send_email(self, db: Session, *, to_email: str, subject: str, body: str, related_ticket_id: str | None = None) -> EmailMessageLog:
        now = datetime.now(UTC)
        log = EmailMessageLog(
            id=str(uuid.uuid4()),
            provider=self.provider_name,
            to_email=to_email,
            subject=subject,
            body=body,
            status="PENDING",
            error_message="Zimbra provider is not configured in this stage",
            related_ticket_id=related_ticket_id,
            created_at=now,
            sent_at=None,
        )
        db.add(log)
        return log
