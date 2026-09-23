"""Typed errors raised by V2 persistence services."""

from __future__ import annotations

import logging
import sys
from typing import Any

from sqlalchemy.exc import SQLAlchemyError

_persistence_logger = logging.getLogger(__name__)


class V2PersistenceError(RuntimeError):
    """Represents a structured V2 persistence failure."""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        stage: str | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.stage = stage
        self.details = details or {}
        self._log_underlying_database_cause()

    def _log_underlying_database_cause(self) -> None:
        """Log the SQLAlchemy failure being wrapped, exactly once per wrap.

        Wrapping sites use `raise _error(...) from error`, which keeps the root
        cause on the exception object but out of the logs.  During the
        2026-09-19 canvas E2E run that cost most of the diagnosis time: missing
        tables, drifted columns, and dangling FK targets all surfaced only as
        opaque codes.  Construction inside an `except SQLAlchemyError` handler
        is the reliable signal that a database failure is being converted.
        """

        active = sys.exc_info()[1]
        if not isinstance(active, SQLAlchemyError):
            return
        _persistence_logger.error(
            "persistence failure [%s] wrapping %s: %s",
            self.code,
            type(active).__name__,
            active,
        )

    def safe_details(self) -> dict[str, str]:
        """Return bounded details suitable for controlled diagnostics."""

        details = {"code": self.code, "message": str(self)}
        if self.stage:
            details["stage"] = self.stage
        return {**details, **self.details}
