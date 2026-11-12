"""Ensembles over normalised detector scores."""

from __future__ import annotations

from typing import Any, Literal

import numpy as np

from anomalyguard.detect.base import DetectionResult, Detector


class EnsembleDetector(Detector):
    """Combine detectors.

    * ``mean``  - average of normalised scores (each capped at ``cap``); anomalous when > 1
    * ``max``   - maximum normalised score (equivalent to "any detector fires")
    * ``vote``  - share of detectors that flag the row; anomalous when at least
      ``min_votes`` detectors agree
    * ``weighted`` - weighted mean of normalised scores (``weights``)
    """

    name = "ensemble"
    univariate = False
    default_threshold = 1.0
    description = "Combines detectors by score averaging or majority vote."

    def __init__(
        self,
        detectors: list[Detector],
        method: Literal["mean", "max", "vote", "weighted"] = "mean",
        min_votes: int | None = None,
        weights: list[float] | None = None,
        cap: float = 5.0,
        **kw: Any,
    ):
        super().__init__(**kw)
        if not detectors:
            raise ValueError("EnsembleDetector needs at least one detector")
        self.detectors = detectors
        self.method = method
        self.min_votes = min_votes or (len(detectors) // 2 + 1)
        self.weights = weights
        self.cap = cap
        self.name = f"ensemble[{method}]({','.join(d.name for d in detectors)})"

    def _fit(self, X: np.ndarray) -> None:  # pragma: no cover - fit() is overridden
        raise NotImplementedError

    def _score_matrix(self, X: np.ndarray) -> np.ndarray:  # pragma: no cover
        raise NotImplementedError

    def fit(self, data: Any) -> EnsembleDetector:
        for d in self.detectors:
            d.fit(data)
        cols: list[str] = []
        for d in self.detectors:
            cols.extend(c for c in (d.columns_ or []) if c not in cols)
        self.columns_ = cols
        self.threshold_ = 1.0
        return self

    def _combine(self, results: list[DetectionResult]) -> np.ndarray:
        S = np.vstack([np.minimum(r.scores, self.cap) for r in results])
        if self.method == "max":
            return S.max(axis=0)
        if self.method == "vote":
            votes = np.vstack([r.labels for r in results]).sum(axis=0)
            # normalised so that reaching min_votes gives a score just above 1
            return votes / self.min_votes * (1 + 1e-9) if self.min_votes else votes
        if self.method == "weighted":
            w = np.asarray(self.weights or [1.0] * len(results), dtype=float)
            return (S * w[:, None]).sum(axis=0) / w.sum()
        return S.mean(axis=0)

    def detect(self, data: Any) -> DetectionResult:
        results = [d.detect(data) for d in self.detectors]
        scores = self._combine(results)
        if self.method == "vote":
            labels = np.vstack([r.labels for r in results]).sum(axis=0) >= self.min_votes
        else:
            labels = scores > self.threshold_multiplier
        flagged = set(np.flatnonzero(labels).tolist())
        findings = [f for r in results for f in r.findings if f.row in flagged]
        findings.sort(key=lambda f: (f.row, f.detector))
        return DetectionResult(
            detector=self.name,
            raw_scores=scores,
            scores=scores,
            labels=labels,
            threshold=1.0,
            columns=list(self.columns_ or []),
            findings=findings,
        )

    def score(self, data: Any) -> np.ndarray:
        return self.detect(data).scores

    def normalized_score(self, data: Any) -> np.ndarray:
        return self.score(data)

    def predict(self, data: Any) -> np.ndarray:
        return self.detect(data).labels

    def get_params(self):
        return {"method": self.method, "detectors": [d.name for d in self.detectors]}
