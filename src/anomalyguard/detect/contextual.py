"""Contextual (group-wise) detection: "normal globally, anomalous for its group"."""

from __future__ import annotations

import copy
from typing import Any

import numpy as np
import pandas as pd

from anomalyguard.detect.base import DetectionResult, Detector, Finding, numeric_columns


class GroupedDetector(Detector):
    """Fit a copy of ``base`` per value of ``group_by`` (e.g. per region or per
    customer). Groups smaller than ``min_group_size`` fall back to a detector
    fitted on all data. Scores are normalised, so the threshold is 1.0.

    Example: an order of 900 is ordinary in the ``west`` region but extreme in
    ``north`` where orders are ~100; a global detector misses it, this one does not.
    """

    name = "grouped"
    univariate = True
    default_threshold = 1.0
    description = "Runs a base detector separately within each group (contextual anomalies)."

    def __init__(
        self, base: Detector, group_by: str | list[str], min_group_size: int = 20, **kw: Any
    ):
        super().__init__(**kw)
        self.base = base
        self.group_by = [group_by] if isinstance(group_by, str) else list(group_by)
        self.min_group_size = min_group_size
        self.name = f"grouped({base.name} by {','.join(self.group_by)})"

    def _fit(self, X: np.ndarray) -> None:  # pragma: no cover - fit() is overridden
        raise NotImplementedError

    def _score_matrix(self, X: np.ndarray) -> np.ndarray:  # pragma: no cover
        raise NotImplementedError

    def _check(self, data: Any) -> pd.DataFrame:
        if not isinstance(data, pd.DataFrame):
            raise TypeError("GroupedDetector needs a DataFrame containing the group column(s)")
        missing = [g for g in self.group_by if g not in data.columns]
        if missing:
            raise KeyError(f"Group column(s) not found: {missing}")
        return data

    def _keys(self, df: pd.DataFrame) -> pd.Series:
        if len(self.group_by) == 1:
            return df[self.group_by[0]].astype(str)
        return df[self.group_by].astype(str).agg("|".join, axis=1)

    def fit(self, data: Any) -> GroupedDetector:
        df = self._check(data)
        cols = self.columns or self.base.columns or numeric_columns(df, exclude=self.group_by)
        self.columns_ = list(cols)
        template = copy.deepcopy(self.base)
        template.columns = self.columns_
        self.global_ = copy.deepcopy(template).fit(df)
        self.detectors_: dict[str, Detector] = {}
        keys = self._keys(df)
        for key, idx in keys.groupby(keys).groups.items():
            if len(idx) >= self.min_group_size:
                self.detectors_[str(key)] = copy.deepcopy(template).fit(df.loc[idx])
        self.threshold_ = 1.0
        return self

    def _for_key(self, key: str) -> Detector:
        return self.detectors_.get(key, self.global_)

    def _set_multiplier(self) -> None:
        for d in [self.global_, *self.detectors_.values()]:
            d.threshold_multiplier = self.threshold_multiplier

    def score(self, data: Any) -> np.ndarray:
        return self.detect(data).scores

    def normalized_score(self, data: Any) -> np.ndarray:
        return self.score(data)

    def predict(self, data: Any) -> np.ndarray:
        return self.detect(data).labels

    def detect(self, data: Any) -> DetectionResult:
        df = self._check(data)
        self._set_multiplier()
        n = len(df)
        scores = np.zeros(n)
        col_scores = np.zeros((n, len(self.columns_)))
        findings: list[Finding] = []
        keys = self._keys(df).reset_index(drop=True)
        positions = pd.Series(np.arange(n))
        for key, pos in positions.groupby(keys).groups.items():
            pos = np.asarray(pos)
            det = self._for_key(str(key))
            res = det.detect(df.iloc[pos])
            scores[pos] = res.scores
            if res.column_scores is not None:
                col_scores[pos] = res.column_scores
            label = "/".join(self.group_by)
            ctx = f"[{label}={key}{'' if str(key) in self.detectors_ else ', global baseline'}] "
            for f in res.findings:
                f.row = int(pos[f.row])
                f.detector = self.name
                f.reason = ctx + f.reason
                findings.append(f)
        findings.sort(key=lambda f: (f.row, f.column or ""))
        return DetectionResult(
            detector=self.name,
            raw_scores=scores,
            scores=scores,
            labels=scores > 1.0,
            threshold=1.0,
            columns=list(self.columns_),
            findings=findings,
            column_scores=col_scores if self.base.univariate else None,
        )

    def get_params(self):
        return {
            "base": self.base.name,
            "group_by": self.group_by,
            "min_group_size": self.min_group_size,
        }
