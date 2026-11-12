"""Detector interface, results and shared helpers.

Score conventions
-----------------
* ``score(data)`` returns a raw anomaly score per row (higher = more anomalous).
* Every fitted detector has a ``threshold_``; a row is anomalous when its raw
  score is strictly greater than the threshold.
* ``normalized = raw / threshold`` puts all detectors on one scale where
  values above 1.0 are anomalies. Ensembles and reports use this scale.
* Univariate detectors score each column independently, so every finding can
  name the offending column. Multivariate detectors score whole rows and name
  the most unusual column (by robust z-score) as an explanation.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pandas as pd

from anomalyguard.schema.coercion import _clean_numeric_strings


class NotFittedError(RuntimeError):
    """Raised when ``score``/``predict`` is called before ``fit``."""


ArrayLike = pd.DataFrame | pd.Series | np.ndarray


def _is_id_like(name: str) -> bool:
    n = str(name).lower()
    return n in {"id", "index", "row", "row_id"} or n.endswith("_id")


def numeric_columns(df: pd.DataFrame, exclude: list[str] | None = None) -> list[str]:
    """Columns that are numeric or mostly-numeric strings, excluding ids/bools."""
    exclude = set(exclude or [])
    out = []
    for col in df.columns:
        if col in exclude or _is_id_like(col):
            continue
        s = df[col]
        if pd.api.types.is_bool_dtype(s) or pd.api.types.is_datetime64_any_dtype(s):
            continue
        if pd.api.types.is_numeric_dtype(s):
            out.append(col)
            continue
        present = s.dropna()
        if len(present) == 0:
            continue
        parsed = pd.to_numeric(_clean_numeric_strings(present.astype(str)), errors="coerce")
        if parsed.notna().mean() >= 0.9:
            out.append(col)
    return out


def to_matrix(data: ArrayLike, columns: list[str] | None = None) -> tuple[np.ndarray, list[str]]:
    """Convert input to a float matrix (NaN for missing/unparseable values)."""
    if isinstance(data, pd.Series):
        data = data.to_frame(name=data.name if data.name is not None else "value")
    if isinstance(data, pd.DataFrame):
        cols = list(columns) if columns else numeric_columns(data)
        missing = [c for c in cols if c not in data.columns]
        if missing:
            raise KeyError(f"Columns not found: {missing}")
        if not cols:
            raise ValueError("No numeric columns to analyse")
        mats = []
        for c in cols:
            s = data[c]
            if not pd.api.types.is_numeric_dtype(s) or pd.api.types.is_bool_dtype(s):
                s = pd.to_numeric(_clean_numeric_strings(s), errors="coerce")
            mats.append(s.astype(float).to_numpy())
        return np.column_stack(mats) if mats else np.empty((len(data), 0)), cols
    arr = np.asarray(data, dtype=float)
    if arr.ndim == 1:
        arr = arr.reshape(-1, 1)
    cols = list(columns) if columns else [f"x{i}" for i in range(arr.shape[1])]
    return arr, cols


def robust_center_scale(X: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Per-column median and a robust scale (IQR/1.349, falling back to std, then 1)."""
    med = np.nanmedian(X, axis=0)
    q75, q25 = np.nanpercentile(X, [75, 25], axis=0)
    scale = (q75 - q25) / 1.349
    std = np.nanstd(X, axis=0)
    scale = np.where(scale > 0, scale, std)
    scale = np.where((scale > 0) & np.isfinite(scale), scale, 1.0)
    med = np.where(np.isfinite(med), med, 0.0)
    return med, scale


def fmt(v: Any) -> str:
    """Compact, ASCII-only number formatting for reasons."""
    if v is None:
        return "NA"
    try:
        f = float(v)
    except (TypeError, ValueError):
        return str(v)
    if np.isnan(f):
        return "NA"
    if f == int(f) and abs(f) < 1e12:
        return str(int(f))
    return f"{f:.4g}"


@dataclass
class Finding:
    """One anomaly: a row (and optionally a column) flagged by a detector."""

    row: int  # positional row number
    detector: str
    score: float  # normalised score, > 1 means anomalous
    column: str | None = None
    value: Any = None
    reason: str = ""
    index: Any = None  # original index label

    def to_dict(self) -> dict[str, Any]:
        v = self.value
        if isinstance(v, (np.floating, float)):
            v = None if np.isnan(v) else float(v)
        elif isinstance(v, np.integer):
            v = int(v)
        idx = self.index.item() if hasattr(self.index, "item") else self.index
        return {
            "row": int(self.row),
            "index": idx if isinstance(idx, (int, float, str, type(None))) else str(idx),
            "detector": self.detector,
            "column": self.column,
            "value": v,
            "score": round(float(self.score), 4),
            "reason": self.reason,
        }


@dataclass
class DetectionResult:
    detector: str
    raw_scores: np.ndarray
    scores: np.ndarray  # normalised
    labels: np.ndarray
    threshold: float
    columns: list[str]
    findings: list[Finding] = field(default_factory=list)
    column_scores: np.ndarray | None = None  # normalised (n, d) for univariate detectors

    @property
    def n_anomalies(self) -> int:
        return int(self.labels.sum())


class Detector(ABC):
    """Base class: ``fit`` / ``score`` / ``predict`` / ``detect``.

    Parameters
    ----------
    columns:
        Columns to analyse (default: all numeric, non-id columns).
    threshold:
        Raw-score threshold. Defaults to a detector-specific value.
    contamination:
        If set, the threshold becomes the ``1 - contamination`` quantile of the
        training scores (i.e. flag that share of the training data).
    """

    name: str = "detector"
    univariate: bool = True
    default_threshold: float = 3.0
    description: str = ""

    def __init__(
        self,
        columns: list[str] | None = None,
        threshold: float | None = None,
        contamination: float | None = None,
    ):
        self.columns = list(columns) if columns else None
        self.threshold = threshold
        self.contamination = contamination
        self.columns_: list[str] | None = None
        self.threshold_: float | None = None
        self.threshold_multiplier = 1.0  # adjusted by the feedback loop

    # -- subclass hooks -------------------------------------------------
    @abstractmethod
    def _fit(self, X: np.ndarray) -> None: ...

    @abstractmethod
    def _score_matrix(self, X: np.ndarray) -> np.ndarray:
        """Raw scores: shape (n, d) for univariate detectors, (n,) otherwise."""

    def _explain(self, X: np.ndarray, row: int, col: int | None, raw: float) -> str:
        return f"score {fmt(raw)} > threshold {fmt(self.threshold_)}"

    def _auto_threshold(self, train_scores: np.ndarray) -> float:
        return self.default_threshold

    # -- public API -----------------------------------------------------
    @property
    def is_fitted(self) -> bool:
        return self.threshold_ is not None

    def _matrix(self, data: ArrayLike) -> np.ndarray:
        if self.columns_ is None:
            raise NotFittedError(f"{self.name} is not fitted")
        X, _ = to_matrix(
            data, self.columns_ if isinstance(data, (pd.DataFrame, pd.Series)) else None
        )
        if X.shape[1] != len(self.columns_):
            raise ValueError(f"Expected {len(self.columns_)} columns, got {X.shape[1]}")
        return X

    def fit(self, data: ArrayLike) -> Detector:
        X, cols = to_matrix(data, self.columns)
        self.columns_ = cols
        self._fit(X)
        if self.contamination is not None or self.threshold is None:
            train = self._row_scores(self._score_matrix(X))
            train = train[np.isfinite(train)]
        if self.contamination is not None:
            if not 0 < self.contamination < 0.5:
                raise ValueError("contamination must be in (0, 0.5)")
            thr = (
                float(np.quantile(train, 1 - self.contamination))
                if len(train)
                else self.default_threshold
            )
        elif self.threshold is not None:
            thr = float(self.threshold)
        else:
            thr = float(self._auto_threshold(train))
        self.threshold_ = max(thr, 1e-12)
        return self

    def _row_scores(self, S: np.ndarray) -> np.ndarray:
        if S.ndim == 2:
            if S.shape[1] == 0:
                return np.zeros(S.shape[0])
            S = np.where(np.isnan(S), -np.inf, S)
            out = S.max(axis=1)
            return np.where(np.isfinite(out), out, 0.0)
        return np.nan_to_num(S, nan=0.0)

    @property
    def effective_threshold(self) -> float:
        if self.threshold_ is None:
            raise NotFittedError(f"{self.name} is not fitted")
        return self.threshold_ * self.threshold_multiplier

    def score(self, data: ArrayLike) -> np.ndarray:
        return self._row_scores(self._score_matrix(self._matrix(data)))

    def normalized_score(self, data: ArrayLike) -> np.ndarray:
        return self.score(data) / self.effective_threshold

    def predict(self, data: ArrayLike) -> np.ndarray:
        return self.score(data) > self.effective_threshold

    def detect(self, data: ArrayLike) -> DetectionResult:
        """Score ``data`` and return labels plus per-row findings with reasons."""
        X = self._matrix(data)
        S = self._score_matrix(X)
        thr = self.effective_threshold
        raw = self._row_scores(S)
        labels = raw > thr
        index = data.index if isinstance(data, (pd.DataFrame, pd.Series)) else None
        findings: list[Finding] = []
        col_scores = None
        if S.ndim == 2:
            col_scores = np.nan_to_num(S, nan=0.0) / thr
            rows, cols = np.nonzero(col_scores > 1.0)
            for r, c in zip(rows.tolist(), cols.tolist(), strict=False):
                findings.append(
                    Finding(
                        row=r,
                        detector=self.name,
                        score=float(col_scores[r, c]),
                        column=self.columns_[c],
                        value=X[r, c],
                        reason=self._explain(X, r, c, float(S[r, c])),
                        index=index[r] if index is not None else r,
                    )
                )
        else:
            contrib = self._contributions(X)
            for r in np.flatnonzero(labels).tolist():
                c = int(np.nanargmax(contrib[r])) if np.isfinite(contrib[r]).any() else None
                top = c if c is not None and contrib[r, c] >= 3.0 else None
                findings.append(
                    Finding(
                        row=r,
                        detector=self.name,
                        score=float(raw[r] / thr),
                        column=self.columns_[top] if top is not None else None,
                        value=X[r, top] if top is not None else None,
                        reason=self._explain(X, r, c, float(raw[r])),
                        index=index[r] if index is not None else r,
                    )
                )
        return DetectionResult(
            detector=self.name,
            raw_scores=raw,
            scores=raw / thr,
            labels=labels,
            threshold=thr,
            columns=list(self.columns_ or []),
            findings=findings,
            column_scores=col_scores,
        )

    def fit_detect(self, data: ArrayLike) -> DetectionResult:
        return self.fit(data).detect(data)

    # -- helpers for multivariate explanations ---------------------------
    def _contributions(self, X: np.ndarray) -> np.ndarray:
        center = getattr(self, "center_", None)
        scale = getattr(self, "scale_", None)
        if center is None or scale is None:
            center, scale = robust_center_scale(X)
        return np.abs((X - center) / scale)

    def _top_columns_text(self, X: np.ndarray, row: int, k: int = 2) -> str:
        contrib = self._contributions(X[row : row + 1])[0]
        order = [i for i in np.argsort(-np.nan_to_num(contrib, nan=-1)) if np.isfinite(contrib[i])][
            :k
        ]
        parts = [f"{self.columns_[i]}={fmt(X[row, i])} (robust z {contrib[i]:.1f})" for i in order]
        return ", ".join(parts)

    def get_params(self) -> dict[str, Any]:
        return {
            "columns": self.columns,
            "threshold": self.threshold,
            "contamination": self.contamination,
        }

    def __repr__(self) -> str:
        params = ", ".join(f"{k}={v!r}" for k, v in self.get_params().items() if v is not None)
        return f"{type(self).__name__}({params})"
