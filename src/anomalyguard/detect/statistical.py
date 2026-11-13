"""Univariate statistical detectors: z-score, modified z-score (MAD), IQR, Grubbs.

Skewed positive columns
-----------------------
Amounts, latencies and sizes are usually right-skewed (roughly log-normal):
on their original scale the long upper tail is full of ordinary values that
a symmetric rule flags. With ``log_scale="auto"`` (the default) a column whose
values are positive and clearly right-skewed is scored on a log scale
instead; reasons then quote the typical value and limits on the original
scale. Pass ``log_scale=False`` to always use the original scale (or ``True``
to force the log scale for positive columns).
"""

from __future__ import annotations

from typing import Any

import numpy as np
from scipy import stats

from anomalyguard.detect.base import Detector, fmt

_EPS = 1e-12
#: a column goes to the log scale when (q95-q50)/(q50-q5) is at least SKEWED on
#: the original scale and within 1/LOG_SYMMETRY..LOG_SYMMETRY on the log scale
SKEWED = 1.5
LOG_SYMMETRY = 1.15


def quantile_skew(x: np.ndarray) -> float:
    """Upper vs lower spread of the central 90%: ``(q95 - q50) / (q50 - q5)``.

    1 for symmetric data, about 2 for a log-normal with sigma 0.45. Unlike the
    moment skewness it is not driven by a handful of outliers.
    """
    q05, q50, q95 = np.percentile(x, [5, 50, 95])
    low = q50 - q05
    if low <= 0:
        return np.inf if q95 > q50 else 1.0
    return float((q95 - q50) / low)


def prefers_log_scale(x: np.ndarray, min_values: int = 30) -> bool:
    """True for a positive, clearly right-skewed column that is close to
    symmetric on a log scale (log-normal-like). Small whole-number counts stay
    on the original scale.

    Up to 1% of the values may be zero or negative (they are scored as far
    below the range, since they do not fit such a column).
    """
    x = x[np.isfinite(x)]
    if len(x) < min_values:
        return False
    pos = x[x > 0]
    if len(pos) < 0.99 * len(x) or len(pos) < min_values:
        return False
    if len(np.unique(pos)) < 10:  # a few repeated levels (counts, ratings): keep linear
        return False
    if np.all(np.mod(pos, 1) == 0) and np.median(pos) < 20:
        return False  # small counts (days, items): discrete, not log-normal

    raw = quantile_skew(pos)
    if raw < SKEWED:
        return False
    # The log must make the column close to symmetric (log-normal-like). A
    # mixture of differently scaled groups (prices in several currencies) stays
    # lopsided on the log scale too, and there a log scale would hide x20 typos.
    logged = quantile_skew(np.log(pos))
    return bool(1 / LOG_SYMMETRY <= logged <= LOG_SYMMETRY)


class _LogScale:
    """Mixin: optionally score some columns on a log scale (see module docs)."""

    log_scale: bool | str = "auto"
    log_cols_: np.ndarray

    def _fit_scale(self, X: np.ndarray) -> np.ndarray:
        d = X.shape[1]
        mode = self.log_scale
        if isinstance(mode, str):
            mode = mode.strip().lower()
            mode = {"true": True, "false": False, "yes": True, "no": False}.get(mode, mode)
        use = np.zeros(d, dtype=bool)
        self.log_floor_ = np.zeros(d)
        for j in range(d):
            x = X[:, j]
            finite = x[np.isfinite(x)]
            if mode is True:
                use[j] = len(finite) > 0 and (finite > 0).mean() >= 0.99
            elif mode == "auto":
                use[j] = prefers_log_scale(x)
            if use[j]:
                logs = np.log(finite[finite > 0])
                spread = float(np.percentile(logs, 95) - np.percentile(logs, 5)) or 1.0
                # zero/negative values sit far below everything else
                self.log_floor_[j] = float(logs.min()) - 3.0 * spread
        self.log_cols_ = use
        return self._to_scale(X)

    def _to_scale(self, X: np.ndarray) -> np.ndarray:
        if not getattr(self, "log_cols_", np.zeros(0, dtype=bool)).any():
            return X
        Y = np.array(X, dtype=float, copy=True)
        for j in np.flatnonzero(self.log_cols_):
            col = Y[:, j]
            finite = np.isfinite(col)
            pos = finite & (col > 0)
            col[pos] = np.log(col[pos])
            col[finite & ~pos] = self.log_floor_[j]
        return Y

    def _from_scale(self, value: float, col: int) -> float:
        return float(np.exp(value)) if self.log_cols_[col] else value

    def _scale_note(self, col: int) -> str:
        return ", log scale" if self.log_cols_[col] else ""

    def _log_params(self) -> dict[str, Any]:
        return {"log_scale": self.log_scale}


class ZScoreDetector(_LogScale, Detector):
    """``|x - mean| / std``. Fast, but mean/std are inflated by the outliers
    themselves, so it under-detects on dirty data."""

    name = "zscore"
    default_threshold = 3.0
    description = "Distance from the mean in standard deviations (assumes roughly normal data)."

    def __init__(self, log_scale: bool | str = "auto", **kw: Any):
        super().__init__(**kw)
        self.log_scale = log_scale

    def _fit(self, X: np.ndarray) -> None:
        X = self._fit_scale(X)
        self.mean_ = np.nanmean(X, axis=0)
        std = np.nanstd(X, axis=0)
        self.std_ = np.where(std > 0, std, _EPS)

    def _score_matrix(self, X: np.ndarray) -> np.ndarray:
        return np.abs(self._to_scale(X) - self.mean_) / self.std_

    def _explain(self, X, row, col, raw):
        return (
            f"{self.columns_[col]}={fmt(X[row, col])} is {raw:.1f} std devs from mean "
            f"{fmt(self._from_scale(self.mean_[col], col))} "
            f"(threshold {fmt(self.effective_threshold)}{self._scale_note(col)})"
        )

    def get_params(self):
        return {**super().get_params(), **self._log_params()}


class MADDetector(_LogScale, Detector):
    """Modified z-score ``0.6745 * |x - median| / MAD`` (Iglewicz & Hoaglin).
    Robust to up to ~50% contamination; threshold 3.5 is the textbook value."""

    name = "mad"
    default_threshold = 3.5
    description = "Modified z-score using median and median absolute deviation (robust)."

    def __init__(self, log_scale: bool | str = "auto", **kw: Any):
        super().__init__(**kw)
        self.log_scale = log_scale

    def _fit(self, X: np.ndarray) -> None:
        X = self._fit_scale(X)
        self.median_ = np.nanmedian(X, axis=0)
        mad = np.nanmedian(np.abs(X - self.median_), axis=0)
        # When more than half the values are identical MAD is 0; fall back to the
        # mean absolute deviation (scaled to be comparable).
        meanad = np.nanmean(np.abs(X - self.median_), axis=0) * 1.2533 * 0.6745
        mad = np.where(mad > 0, mad, meanad)
        self.mad_ = np.where(mad > 0, mad, _EPS)

    def _score_matrix(self, X: np.ndarray) -> np.ndarray:
        return 0.6745 * np.abs(self._to_scale(X) - self.median_) / self.mad_

    def bounds(self) -> tuple[np.ndarray, np.ndarray]:
        """Values inside these bounds are not flagged (original scale)."""
        width = self.effective_threshold * self.mad_ / 0.6745
        lo, hi = self.median_ - width, self.median_ + width
        return (
            np.where(self.log_cols_, np.exp(lo), lo),
            np.where(self.log_cols_, np.exp(hi), hi),
        )

    def _explain(self, X, row, col, raw):
        return (
            f"{self.columns_[col]}={fmt(X[row, col])} has modified z-score {raw:.1f} vs median "
            f"{fmt(self._from_scale(self.median_[col], col))} "
            f"(threshold {fmt(self.effective_threshold)}{self._scale_note(col)})"
        )

    def get_params(self):
        return {**super().get_params(), **self._log_params()}


class IQRDetector(_LogScale, Detector):
    """Tukey fences. Score = distance outside ``[Q1, Q3]`` in IQR units, so the
    default threshold 1.5 reproduces ``Q1 - 1.5*IQR`` / ``Q3 + 1.5*IQR``."""

    name = "iqr"
    default_threshold = 1.5
    description = "Tukey fences: outside Q1 - k*IQR or Q3 + k*IQR (k=1.5)."

    def __init__(self, log_scale: bool | str = "auto", **kw: Any):
        super().__init__(**kw)
        self.log_scale = log_scale

    def _fit(self, X: np.ndarray) -> None:
        X = self._fit_scale(X)
        self.q1_, self.q3_ = np.nanpercentile(X, [25, 75], axis=0)
        iqr = self.q3_ - self.q1_
        self.iqr_ = np.where(iqr > 0, iqr, _EPS)

    def _score_matrix(self, X: np.ndarray) -> np.ndarray:
        X = self._to_scale(X)
        below = (self.q1_ - X) / self.iqr_
        above = (X - self.q3_) / self.iqr_
        out = np.maximum(np.maximum(below, above), 0.0)
        return np.where(np.isnan(X), np.nan, out)

    def bounds(self) -> tuple[np.ndarray, np.ndarray]:
        """Tukey fences on the original scale."""
        k = self.effective_threshold
        lo, hi = self.q1_ - k * self.iqr_, self.q3_ + k * self.iqr_
        return (
            np.where(self.log_cols_, np.exp(lo), lo),
            np.where(self.log_cols_, np.exp(hi), hi),
        )

    def _explain(self, X, row, col, raw):
        lo, hi = self.bounds()
        return (
            f"{self.columns_[col]}={fmt(X[row, col])} outside IQR fences "
            f"[{fmt(lo[col])}, {fmt(hi[col])}]{' (log scale)' if self.log_cols_[col] else ''}"
        )

    def get_params(self):
        return {**super().get_params(), **self._log_params()}


def grubbs_critical(n: int, alpha: float) -> float:
    """Two-sided Grubbs critical value."""
    if n < 3:
        return np.inf
    t = stats.t.ppf(1 - alpha / (2 * n), n - 2)
    return (n - 1) / np.sqrt(n) * np.sqrt(t**2 / (n - 2 + t**2))


class GrubbsDetector(_LogScale, Detector):
    """Iterative two-sided Grubbs test (assumes normality).

    ``fit`` repeatedly removes the most extreme value while ``G > G_crit``
    (up to ``max_outlier_fraction`` of the data), then scores values against the
    cleaned mean/std. Raw score is ``G / G_crit`` so the threshold is 1.0.
    """

    name = "grubbs"
    default_threshold = 1.0
    description = "Iterative Grubbs test for outliers in normally distributed data."

    def __init__(
        self,
        alpha: float = 0.05,
        max_outlier_fraction: float = 0.1,
        log_scale: bool | str = "auto",
        **kw: Any,
    ):
        super().__init__(**kw)
        self.alpha = alpha
        self.max_outlier_fraction = max_outlier_fraction
        self.log_scale = log_scale

    def _fit(self, X: np.ndarray) -> None:
        X = self._fit_scale(X)
        d = X.shape[1]
        self.mean_ = np.zeros(d)
        self.std_ = np.ones(d)
        self.gcrit_ = np.full(d, np.inf)
        for j in range(d):
            x = X[:, j]
            x = x[np.isfinite(x)]
            keep = np.ones(len(x), dtype=bool)
            max_out = int(self.max_outlier_fraction * len(x))
            for _ in range(max_out):
                vals = x[keep]
                n = len(vals)
                if n < 3:
                    break
                mean, std = vals.mean(), vals.std(ddof=1)
                if std <= 0:
                    break
                dev = np.abs(x - mean)
                dev[~keep] = -1
                idx = int(np.argmax(dev))
                if dev[idx] / std > grubbs_critical(n, self.alpha):
                    keep[idx] = False
                else:
                    break
            vals = x[keep]
            if len(vals) >= 3:
                self.mean_[j] = vals.mean()
                self.std_[j] = max(vals.std(ddof=1), _EPS)
                self.gcrit_[j] = grubbs_critical(len(vals), self.alpha)

    def _score_matrix(self, X: np.ndarray) -> np.ndarray:
        g = np.abs(self._to_scale(X) - self.mean_) / self.std_
        return g / self.gcrit_

    def _explain(self, X, row, col, raw):
        g = raw * self.gcrit_[col]
        return (
            f"{self.columns_[col]}={fmt(X[row, col])} fails Grubbs test "
            f"(G={g:.2f} > critical {self.gcrit_[col]:.2f}, alpha={self.alpha}"
            f"{self._scale_note(col)})"
        )

    def get_params(self):
        return {**super().get_params(), "alpha": self.alpha, **self._log_params()}
