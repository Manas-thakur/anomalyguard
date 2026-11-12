"""Univariate statistical detectors: z-score, modified z-score (MAD), IQR, Grubbs."""

from __future__ import annotations

import numpy as np
from scipy import stats

from anomalyguard.detect.base import Detector, fmt

_EPS = 1e-12


class ZScoreDetector(Detector):
    """``|x - mean| / std``. Fast, but mean/std are inflated by the outliers
    themselves, so it under-detects on dirty data."""

    name = "zscore"
    default_threshold = 3.0
    description = "Distance from the mean in standard deviations (assumes roughly normal data)."

    def _fit(self, X: np.ndarray) -> None:
        self.mean_ = np.nanmean(X, axis=0)
        std = np.nanstd(X, axis=0)
        self.std_ = np.where(std > 0, std, _EPS)

    def _score_matrix(self, X: np.ndarray) -> np.ndarray:
        return np.abs(X - self.mean_) / self.std_

    def _explain(self, X, row, col, raw):
        return (
            f"{self.columns_[col]}={fmt(X[row, col])} is {raw:.1f} std devs from mean "
            f"{fmt(self.mean_[col])} (threshold {fmt(self.effective_threshold)})"
        )


class MADDetector(Detector):
    """Modified z-score ``0.6745 * |x - median| / MAD`` (Iglewicz & Hoaglin).
    Robust to up to ~50% contamination; threshold 3.5 is the textbook value."""

    name = "mad"
    default_threshold = 3.5
    description = "Modified z-score using median and median absolute deviation (robust)."

    def _fit(self, X: np.ndarray) -> None:
        self.median_ = np.nanmedian(X, axis=0)
        mad = np.nanmedian(np.abs(X - self.median_), axis=0)
        # When more than half the values are identical MAD is 0; fall back to the
        # mean absolute deviation (scaled to be comparable).
        meanad = np.nanmean(np.abs(X - self.median_), axis=0) * 1.2533 * 0.6745
        mad = np.where(mad > 0, mad, meanad)
        self.mad_ = np.where(mad > 0, mad, _EPS)

    def _score_matrix(self, X: np.ndarray) -> np.ndarray:
        return 0.6745 * np.abs(X - self.median_) / self.mad_

    def bounds(self) -> tuple[np.ndarray, np.ndarray]:
        """Values inside these bounds are not flagged (used for capping)."""
        width = self.effective_threshold * self.mad_ / 0.6745
        return self.median_ - width, self.median_ + width

    def _explain(self, X, row, col, raw):
        return (
            f"{self.columns_[col]}={fmt(X[row, col])} has modified z-score {raw:.1f} vs median "
            f"{fmt(self.median_[col])} (threshold {fmt(self.effective_threshold)})"
        )


class IQRDetector(Detector):
    """Tukey fences. Score = distance outside ``[Q1, Q3]`` in IQR units, so the
    default threshold 1.5 reproduces ``Q1 - 1.5*IQR`` / ``Q3 + 1.5*IQR``."""

    name = "iqr"
    default_threshold = 1.5
    description = "Tukey fences: outside Q1 - k*IQR or Q3 + k*IQR (k=1.5)."

    def _fit(self, X: np.ndarray) -> None:
        self.q1_, self.q3_ = np.nanpercentile(X, [25, 75], axis=0)
        iqr = self.q3_ - self.q1_
        self.iqr_ = np.where(iqr > 0, iqr, _EPS)

    def _score_matrix(self, X: np.ndarray) -> np.ndarray:
        below = (self.q1_ - X) / self.iqr_
        above = (X - self.q3_) / self.iqr_
        out = np.maximum(np.maximum(below, above), 0.0)
        return np.where(np.isnan(X), np.nan, out)

    def bounds(self) -> tuple[np.ndarray, np.ndarray]:
        k = self.effective_threshold
        return self.q1_ - k * self.iqr_, self.q3_ + k * self.iqr_

    def _explain(self, X, row, col, raw):
        lo, hi = self.bounds()
        return (
            f"{self.columns_[col]}={fmt(X[row, col])} outside IQR fences "
            f"[{fmt(lo[col])}, {fmt(hi[col])}]"
        )


def grubbs_critical(n: int, alpha: float) -> float:
    """Two-sided Grubbs critical value."""
    if n < 3:
        return np.inf
    t = stats.t.ppf(1 - alpha / (2 * n), n - 2)
    return (n - 1) / np.sqrt(n) * np.sqrt(t**2 / (n - 2 + t**2))


class GrubbsDetector(Detector):
    """Iterative two-sided Grubbs test (assumes normality).

    ``fit`` repeatedly removes the most extreme value while ``G > G_crit``
    (up to ``max_outlier_fraction`` of the data), then scores values against the
    cleaned mean/std. Raw score is ``G / G_crit`` so the threshold is 1.0.
    """

    name = "grubbs"
    default_threshold = 1.0
    description = "Iterative Grubbs test for outliers in normally distributed data."

    def __init__(self, alpha: float = 0.05, max_outlier_fraction: float = 0.1, **kw):
        super().__init__(**kw)
        self.alpha = alpha
        self.max_outlier_fraction = max_outlier_fraction

    def _fit(self, X: np.ndarray) -> None:
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
        g = np.abs(X - self.mean_) / self.std_
        return g / self.gcrit_

    def _explain(self, X, row, col, raw):
        g = raw * self.gcrit_[col]
        return (
            f"{self.columns_[col]}={fmt(X[row, col])} fails Grubbs test "
            f"(G={g:.2f} > critical {self.gcrit_[col]:.2f}, alpha={self.alpha})"
        )

    def get_params(self):
        return {**super().get_params(), "alpha": self.alpha}
