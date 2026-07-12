from __future__ import annotations

import contextvars


_correlation_id: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "sbs_correlation_id", default=None
)


def set_correlation_id(value: str | None) -> None:
    _correlation_id.set(value)


def get_correlation_id() -> str | None:
    return _correlation_id.get()
