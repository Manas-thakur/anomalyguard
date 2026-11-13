"""Feedback loop: false-positive reports raise a detector's threshold.

Each piece of feedback marks a reported anomaly as a true or false positive.
``tune()`` computes per-detector precision from that feedback and nudges the
threshold multiplier (stored in the metrics DB and applied by the pipeline on
its next run): precision below ``target_precision`` raises the threshold by
``step``; very high precision slowly relaxes it back towards 1.0. Only feedback
received since a detector's last adjustment is considered.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from anomalyguard.monitor.store import MetricsStore

_GROUPED = re.compile(r"^grouped\((?P<base>.+?) by .+\)$")
_ENSEMBLE = re.compile(r"^ensemble\[(?:mean|max|vote|weighted)\]\((?P<members>.*)\)$")


def resolve_detector(name: str, store: MetricsStore | None = None) -> str:
    """Normalise a detector name given for feedback or a threshold.

    Accepts registry names and aliases (``tukey`` -> ``iqr``), ``grouped`` /
    ``ensemble`` and the composite names runs record, such as
    ``grouped(mad by region)``, plus any name already stored in ``store``.
    Raises ``KeyError`` with the list of known names otherwise.
    """
    from anomalyguard.detect.registry import DETECTORS, canonical_name

    raw = str(name or "").strip()
    if not raw:
        raise KeyError("detector name is empty")
    try:
        return canonical_name(raw)
    except KeyError:
        pass
    if raw in ("grouped", "ensemble"):
        return raw
    if store is not None and raw in store.detector_names():
        return raw
    m = _GROUPED.match(raw)
    if m:
        try:
            canonical_name(m.group("base"))
            return raw
        except KeyError:
            pass
    m = _ENSEMBLE.match(raw)
    if m:
        return raw
    raise KeyError(
        f"Unknown detector '{raw}'. Use one of: {', '.join(sorted(DETECTORS))}, "
        "a grouped/ensemble name such as 'grouped(mad by region)', or a name shown in a run"
    )


@dataclass
class ThresholdChange:
    detector: str
    old: float
    new: float
    precision: float
    n_feedback: int

    def to_dict(self) -> dict[str, Any]:
        return self.__dict__.copy()


class FeedbackLoop:
    def __init__(
        self,
        store: MetricsStore,
        target_precision: float = 0.8,
        step: float = 0.15,
        min_feedback: int = 3,
        max_multiplier: float = 4.0,
    ):
        self.store = store
        self.target_precision = target_precision
        self.step = step
        self.min_feedback = min_feedback
        self.max_multiplier = max_multiplier

    def mark(
        self,
        label: str,
        anomaly_id: int | None = None,
        detector: str | None = None,
        run_id: int | None = None,
        row_index: Any = None,
        column: str | None = None,
        note: str | None = None,
    ) -> int:
        """Record feedback, either for a stored anomaly (``anomaly_id``) or by detector name."""
        if anomaly_id is not None:
            a = self.store.get_anomaly(anomaly_id)
            if a is None:
                raise KeyError(f"Anomaly {anomaly_id} not found")
            detector, run_id, column = a["detector"], a["run_id"], a["column"]
            row_index = a["row_index"]
        if not detector:
            raise ValueError("feedback needs a detector or an anomaly_id")
        if anomaly_id is None:
            detector = resolve_detector(detector, self.store)
        return self.store.add_feedback(detector, label, run_id, anomaly_id, row_index, column, note)

    def mark_false_positive(self, **kw: Any) -> int:
        return self.mark("false_positive", **kw)

    def mark_true_positive(self, **kw: Any) -> int:
        return self.mark("true_positive", **kw)

    def precision(self, since_last_tune: bool = False) -> dict[str, dict[str, float]]:
        out = {}
        for det, c in self.store.feedback_counts(since_last_tune).items():
            n = c["true_positive"] + c["false_positive"]
            out[det] = {**c, "n": n, "precision": c["true_positive"] / n if n else 1.0}
        return out

    def tune(self) -> list[ThresholdChange]:
        current = self.store.thresholds()
        changes = []
        # only feedback received since a detector was last tuned counts, so a
        # batch of reviews moves each threshold by at most one step
        for det, stats in self.precision(since_last_tune=True).items():
            if stats["n"] < self.min_feedback:
                continue
            old = current.get(det, 1.0)
            new = old
            if stats["precision"] < self.target_precision:
                new = min(old * (1 + self.step), self.max_multiplier)
            elif stats["precision"] >= 0.95 and old > 1.0:
                new = max(old / (1 + self.step), 1.0)
            if abs(new - old) > 1e-9:
                self.store.set_threshold(
                    det,
                    round(new, 4),
                    f"precision {stats['precision']:.2f} over {stats['n']} reviews",
                )
                changes.append(
                    ThresholdChange(det, old, round(new, 4), stats["precision"], int(stats["n"]))
                )
        return changes
