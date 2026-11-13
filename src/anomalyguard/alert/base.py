"""Alert messages, severities and the Notifier interface."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any


class Severity(str, Enum):
    DEBUG = "debug"
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"

    @property
    def rank(self) -> int:
        return list(Severity).index(self)

    def __ge__(self, other: object) -> bool:  # type: ignore[override]
        if not isinstance(other, Severity):
            return NotImplemented
        return self.rank >= other.rank

    def __gt__(self, other: object) -> bool:  # type: ignore[override]
        if not isinstance(other, Severity):
            return NotImplemented
        return self.rank > other.rank

    def __le__(self, other: object) -> bool:  # type: ignore[override]
        if not isinstance(other, Severity):
            return NotImplemented
        return self.rank <= other.rank

    def __lt__(self, other: object) -> bool:  # type: ignore[override]
        if not isinstance(other, Severity):
            return NotImplemented
        return self.rank < other.rank


@dataclass
class AlertMessage:
    title: str
    body: str = ""
    severity: Severity = Severity.WARNING
    source: str | None = None
    rule: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    timestamp: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat(timespec="seconds")
    )

    @property
    def dedup_key(self) -> str:
        return f"{self.source}|{self.rule or self.title}|{self.severity.value}"

    def to_dict(self) -> dict[str, Any]:
        return {
            "title": self.title,
            "body": self.body,
            "severity": self.severity.value,
            "source": self.source,
            "rule": self.rule,
            "metadata": self.metadata,
            "timestamp": self.timestamp,
        }


class Notifier(ABC):
    """A delivery channel. Messages below ``min_severity`` are skipped."""

    kind = "notifier"

    def __init__(self, min_severity: Severity | str = Severity.INFO):
        self.min_severity = Severity(min_severity)
        #: why the last ``send`` failed (set by notifiers that can fail)
        self.last_error: str | None = None

    def accepts(self, message: AlertMessage) -> bool:
        return message.severity >= self.min_severity

    @abstractmethod
    def send(self, message: AlertMessage) -> bool:
        """Deliver one message; return True on success."""

    def send_batch(self, messages: list[AlertMessage]) -> list[bool]:
        return [self.send(m) for m in messages]
