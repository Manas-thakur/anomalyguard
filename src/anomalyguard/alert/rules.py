"""Alert rules evaluated against a run's metrics dictionary.

Metrics produced by the pipeline include ``anomaly_rate``, ``n_anomalies``,
``quality_score``, ``completeness``, ``validity``, ``uniqueness``,
``freshness``, ``invalid_rows``, ``duplicate_rows``, ``rows``,
``flagged_for_review`` and ``rows_dropped``.
"""

from __future__ import annotations

import operator
from dataclasses import dataclass
from typing import Any

from anomalyguard.alert.base import AlertMessage, Severity

OPS = {
    ">": operator.gt,
    ">=": operator.ge,
    "<": operator.lt,
    "<=": operator.le,
    "==": operator.eq,
    "!=": operator.ne,
}


@dataclass
class AlertRule:
    """Fire when ``metrics[metric] <op> value``.

    ``change`` rules compare against the previous run instead:
    ``metrics[metric] - previous[metric] <op> value``.
    """

    metric: str
    op: str = ">"
    value: float = 0.0
    severity: Severity = Severity.WARNING
    name: str | None = None
    kind: str = "threshold"  # threshold | change
    message: str | None = None

    def __post_init__(self) -> None:
        if self.op not in OPS:
            raise ValueError(f"Unknown operator '{self.op}'")
        self.severity = Severity(self.severity)
        if self.kind not in ("threshold", "change"):
            raise ValueError("rule kind must be 'threshold' or 'change'")
        self.name = (
            self.name
            or f"{self.metric} {'change ' if self.kind == 'change' else ''}{self.op} {self.value}"
        )

    def evaluate(self, metrics: dict[str, Any], source: str | None = None) -> AlertMessage | None:
        current = metrics.get(self.metric)
        if current is None:
            return None
        observed = current
        if self.kind == "change":
            prev = (metrics.get("previous") or {}).get(self.metric)
            if prev is None:
                return None
            observed = current - prev
        if not OPS[self.op](observed, self.value):
            return None
        title = (
            self.message.format(**metrics, observed=observed)
            if self.message
            else (
                f"{self.metric} {'changed by ' if self.kind == 'change' else '= '}{_fmt(observed)} ({self.op} {_fmt(self.value)})"
            )
        )
        body = ", ".join(
            f"{k}={_fmt(metrics[k])}"
            for k in ("rows", "n_anomalies", "anomaly_rate", "quality_score", "flagged_for_review")
            if k in metrics
        )
        return AlertMessage(
            title=title,
            body=body,
            severity=self.severity,
            source=source,
            rule=self.name,
            metadata={"metric": self.metric, "observed": observed, "threshold": self.value},
        )

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> AlertRule:
        d = dict(data)
        if "type" in d:
            d["kind"] = d.pop("type")
        if "threshold" in d and "value" not in d:
            d["value"] = d.pop("threshold")
        return cls(**d)


def _fmt(v: Any) -> str:
    if isinstance(v, float):
        return f"{v:.4g}"
    return str(v)


DEFAULT_RULES = [
    AlertRule("anomaly_rate", ">", 0.05, Severity.WARNING),
    AlertRule("quality_score", "<", 0.9, Severity.ERROR),
]
