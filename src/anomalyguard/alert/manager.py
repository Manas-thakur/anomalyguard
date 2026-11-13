"""Rate limiting/deduplication and the AlertManager that ties rules to notifiers."""

from __future__ import annotations

import json
import logging
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from anomalyguard.alert.base import AlertMessage, Notifier
from anomalyguard.alert.rules import AlertRule

log = logging.getLogger("anomalyguard.alert")


class RateLimiter:
    """Suppress duplicates (same ``dedup_key`` within ``dedup_seconds``) and cap
    the total number of alerts per ``window_seconds``. With ``state_path`` the
    history survives between separate pipeline processes."""

    def __init__(
        self,
        max_per_window: int = 20,
        window_seconds: float = 3600.0,
        dedup_seconds: float = 3600.0,
        state_path: str | Path | None = None,
        clock: Callable[[], float] = time.time,
    ):
        self.max_per_window = max_per_window
        self.window_seconds = window_seconds
        self.dedup_seconds = dedup_seconds
        self.state_path = Path(state_path) if state_path else None
        self.clock = clock
        self.sent: list[tuple[float, str]] = []
        self._load()

    def _load(self) -> None:
        if self.state_path and self.state_path.exists():
            try:
                self.sent = [
                    tuple(x) for x in json.loads(self.state_path.read_text(encoding="utf-8"))
                ]  # type: ignore[misc]
            except (json.JSONDecodeError, TypeError, ValueError):
                self.sent = []

    def _save(self) -> None:
        if self.state_path:
            self.state_path.parent.mkdir(parents=True, exist_ok=True)
            self.state_path.write_text(json.dumps(self.sent), encoding="utf-8")

    def allow(self, message: AlertMessage) -> tuple[bool, str]:
        now = self.clock()
        horizon = max(self.window_seconds, self.dedup_seconds)
        self.sent = [(t, k) for t, k in self.sent if now - t < horizon]
        if any(k == message.dedup_key and now - t < self.dedup_seconds for t, k in self.sent):
            return False, "duplicate"
        if sum(1 for t, _ in self.sent if now - t < self.window_seconds) >= self.max_per_window:
            return False, "rate_limited"
        self.sent.append((now, message.dedup_key))
        self._save()
        return True, "ok"


@dataclass
class DispatchRecord:
    """What happened to one alert.

    ``status``: ``sent`` (every channel delivered), ``partial`` (some did),
    ``failed`` (none did), or ``duplicate`` / ``rate_limited`` / ``filtered``
    (not attempted). ``channels`` lists the channels that delivered it;
    ``deliveries`` has one ``{channel, ok, error}`` entry per attempted channel.
    """

    message: AlertMessage
    status: str  # sent | partial | failed | duplicate | rate_limited | filtered
    channels: list[str] = field(default_factory=list)
    deliveries: list[dict[str, Any]] = field(default_factory=list)

    @property
    def delivered(self) -> bool:
        return self.status in ("sent", "partial")

    def to_dict(self) -> dict[str, Any]:
        return {
            **self.message.to_dict(),
            "status": self.status,
            "channels": self.channels,
            "deliveries": self.deliveries,
        }


class AlertManager:
    def __init__(
        self,
        notifiers: list[Notifier] | None = None,
        rules: list[AlertRule] | None = None,
        rate_limiter: RateLimiter | None = None,
    ):
        self.notifiers = notifiers or []
        self.rules = rules or []
        self.rate_limiter = rate_limiter

    def evaluate(self, metrics: dict[str, Any], source: str | None = None) -> list[AlertMessage]:
        out = []
        for rule in self.rules:
            msg = rule.evaluate(metrics, source)
            if msg is not None:
                out.append(msg)
        return out

    def dispatch(self, messages: list[AlertMessage]) -> list[DispatchRecord]:
        records = []
        for msg in messages:
            targets = [n for n in self.notifiers if n.accepts(msg)]
            if not targets:
                records.append(DispatchRecord(msg, "filtered"))
                continue
            if self.rate_limiter is not None:
                ok, why = self.rate_limiter.allow(msg)
                if not ok:
                    records.append(DispatchRecord(msg, why))
                    continue
            deliveries = [_deliver(n, msg) for n in targets]
            delivered = [d["channel"] for d in deliveries if d["ok"]]
            if len(delivered) == len(deliveries):
                status = "sent"
            elif delivered:
                status = "partial"
            else:
                status = "failed"
            records.append(DispatchRecord(msg, status, delivered, deliveries))
        return records

    def process(self, metrics: dict[str, Any], source: str | None = None) -> list[DispatchRecord]:
        return self.dispatch(self.evaluate(metrics, source))


def _deliver(notifier: Notifier, message: AlertMessage) -> dict[str, Any]:
    """Send through one channel; a notifier that raises counts as a failed delivery."""
    try:
        ok = bool(notifier.send(message))
        error = None if ok else getattr(notifier, "last_error", None)
        if not ok and not error:  # built-in notifiers log their own failures with details
            error = "delivery failed"
            log.warning("%s alert delivery failed (alert: %s)", notifier.kind, message.title)
    except Exception as exc:  # one broken channel must not stop the others
        ok, error = False, f"{type(exc).__name__}: {exc}"
        log.warning("%s alert delivery failed: %s (alert: %s)", notifier.kind, error, message.title)
    return {"channel": notifier.kind, "ok": ok, "error": error}
