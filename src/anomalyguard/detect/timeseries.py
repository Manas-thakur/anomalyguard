"""Time-series detectors. Rows are assumed to be in time order and evenly
spaced: pass ``time_column`` via the runner, which sorts by time and puts the
series on a regular grid (missing points become empty values). These
detectors score each value relative to its own history, so they are fit and
scored on the same series."""

from __future__ import annotations

import numpy as np
import pandas as pd

from anomalyguard.detect.base import Detector, fmt

_EPS = 1e-12
#: rolling windows whose scale is below this share of the typical window scale
#: have collapsed (e.g. a stuck sensor) and are scored with the typical scale
COLLAPSED = 0.5


def _robust_z(x: np.ndarray) -> tuple[np.ndarray, float, float]:
    med = np.nanmedian(x)
    mad = np.nanmedian(np.abs(x - med)) * 1.4826
    if not mad or not np.isfinite(mad):
        mad = np.nanstd(x) or 1.0
    return (x - med) / mad, float(med), float(mad)


class RollingZScoreDetector(Detector):
    """Deviation from a trailing window (the current point is excluded).

    With ``robust=True`` (default) the window centre is the rolling median and
    the scale is the rolling IQR / 1.349, so earlier spikes do not mask later ones.
    A window whose scale collapses below half the series' typical window
    scale (e.g. a stuck sensor repeating one value) is given the typical scale,
    so the readings after a stuck period are not flagged just because the window
    had no spread; use the ``flatline`` detector to catch the stuck run itself.
    """

    name = "rolling_zscore"
    temporal = True
    default_threshold = 4.0
    description = "Deviation from a trailing rolling window (median/IQR or mean/std)."

    def __init__(self, window: int = 24, min_periods: int | None = None, robust: bool = True, **kw):
        super().__init__(**kw)
        self.window = window
        self.min_periods = min_periods or max(3, window // 2)
        self.robust = robust

    def _fit(self, X: np.ndarray) -> None:
        self.global_scale_ = np.nanstd(X, axis=0)

    def _score_matrix(self, X: np.ndarray) -> np.ndarray:
        out = np.zeros_like(X, dtype=float)
        self.expected_ = np.full_like(X, np.nan, dtype=float)
        for j in range(X.shape[1]):
            s = pd.Series(X[:, j])
            hist = s.shift(1).rolling(self.window, min_periods=self.min_periods)
            if self.robust:
                center = hist.median()
                scale = (hist.quantile(0.75) - hist.quantile(0.25)) / 1.349
            else:
                center = hist.mean()
                scale = hist.std()
            positive = scale[scale > 0]
            typical = float(positive.median()) if len(positive) else 0.0
            floor = max(0.01 * float(self.global_scale_[j] or 0.0), _EPS)
            # A window whose spread collapsed (e.g. a stuck sensor repeating one
            # value) says nothing about normal variation: use the typical scale.
            collapsed = scale < max(COLLAPSED * typical, floor)
            scale = scale.where(~collapsed, max(typical, floor))
            z = ((s - center).abs() / scale).to_numpy()
            out[:, j] = np.where(np.isfinite(z), z, 0.0)
            out[np.isnan(X[:, j]), j] = np.nan
            self.expected_[:, j] = center.to_numpy()
        return out

    def _explain(self, X, row, col, raw):
        return (
            f"{self.columns_[col]}={fmt(X[row, col])} deviates {raw:.1f} scaled units from "
            f"rolling {'median' if self.robust else 'mean'} {fmt(self.expected_[row, col])} "
            f"(window {self.window})"
        )

    def get_params(self):
        return {**super().get_params(), "window": self.window, "robust": self.robust}


class EWMADetector(Detector):
    """Exponentially weighted moving average/variance forecast. Each value is
    compared to the forecast made before it; large residuals are clipped before
    updating the state so a spike does not poison the baseline."""

    name = "ewma"
    temporal = True
    default_threshold = 4.0
    description = "Residual from an exponentially weighted moving average forecast."

    def __init__(self, span: int = 24, warmup: int | None = None, **kw):
        super().__init__(**kw)
        self.span = span
        self.alpha = 2.0 / (span + 1.0)
        self.warmup = warmup or span

    def _fit(self, X: np.ndarray) -> None:
        pass

    def _score_matrix(self, X: np.ndarray) -> np.ndarray:
        n, d = X.shape
        out = np.zeros((n, d))
        self.expected_ = np.full((n, d), np.nan)
        clip = self.threshold or self.default_threshold
        for j in range(d):
            x = X[:, j]
            finite = x[np.isfinite(x)]
            if len(finite) < 3:
                continue
            head = finite[: self.warmup]
            mean = float(np.median(head))
            var = (
                float((np.median(np.abs(head - mean)) * 1.4826) ** 2)
                or float(np.var(finite))
                or 1.0
            )
            floor = max(1e-6 * float(np.var(finite)), _EPS)
            for i in range(n):
                v = x[i]
                if not np.isfinite(v):
                    out[i, j] = np.nan
                    continue
                sd = np.sqrt(max(var, floor))
                resid = v - mean
                z = abs(resid) / sd
                self.expected_[i, j] = mean
                out[i, j] = z if i >= min(self.warmup, n // 4) else 0.0
                resid = float(np.clip(resid, -clip * sd, clip * sd))
                mean += self.alpha * resid
                var = (1 - self.alpha) * (var + self.alpha * resid * resid)
        return out

    def _explain(self, X, row, col, raw):
        return (
            f"{self.columns_[col]}={fmt(X[row, col])} is {raw:.1f} std devs from EWMA "
            f"forecast {fmt(self.expected_[row, col])} (span {self.span})"
        )

    def get_params(self):
        return {**super().get_params(), "span": self.span}


def seasonal_decompose(
    x: np.ndarray, period: int, trend_window: int | None = None
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Robust additive decomposition ``x = trend + seasonal + residual``.

    Trend: centred rolling median over ``trend_window`` points (default three
    periods, so short level shifts stay in the residual). Seasonal: per-phase median of
    the detrended series (centred to sum to zero). Missing values are
    interpolated for the decomposition only.
    """
    s = pd.Series(x).interpolate(limit_direction="both")
    window = trend_window or 3 * period
    trend = s.rolling(window, center=True, min_periods=max(1, window // 4)).median()
    trend = trend.bfill().ffill()
    detrended = (s - trend).to_numpy()
    phase = np.arange(len(x)) % period
    profile = np.array(
        [np.nanmedian(detrended[phase == p]) if np.any(phase == p) else 0.0 for p in range(period)]
    )
    profile = profile - np.nanmean(profile)
    seasonal = profile[phase]
    resid = s.to_numpy() - trend.to_numpy() - seasonal
    return trend.to_numpy(), seasonal, resid


class SeasonalResidualDetector(Detector):
    """Seasonal decomposition residuals scored with a robust z-score. Catches
    contextual anomalies: values that are normal overall but wrong for their
    position in the cycle (e.g. a daytime peak value at 3am)."""

    name = "seasonal"
    temporal = True
    default_threshold = 4.0
    description = "Robust z-score of residuals after removing trend and seasonality."

    def __init__(self, period: int = 24, trend_window: int | None = None, **kw):
        super().__init__(**kw)
        self.period = period
        self.trend_window = trend_window

    def _fit(self, X: np.ndarray) -> None:
        pass

    def _score_matrix(self, X: np.ndarray) -> np.ndarray:
        out = np.zeros_like(X, dtype=float)
        self.expected_ = np.full_like(X, np.nan, dtype=float)
        for j in range(X.shape[1]):
            x = X[:, j]
            if np.isfinite(x).sum() < 2 * self.period:
                z, _, _ = _robust_z(x)
                out[:, j] = np.abs(z)
                self.expected_[:, j] = np.nanmedian(x)
                continue
            trend, seasonal, resid = seasonal_decompose(x, self.period, self.trend_window)
            z, _, _ = _robust_z(resid)
            out[:, j] = np.abs(z)
            self.expected_[:, j] = trend + seasonal
        out[np.isnan(X)] = np.nan
        return out

    def _explain(self, X, row, col, raw):
        return (
            f"{self.columns_[col]}={fmt(X[row, col])} vs expected {fmt(self.expected_[row, col])} "
            f"from trend+seasonality (residual robust z {raw:.1f}, period {self.period})"
        )

    def get_params(self):
        return {**super().get_params(), "period": self.period}


class CUSUMDetector(Detector):
    """Two-sided tabular CUSUM change-point detector.

    Values are standardised with a robust baseline (median/MAD of the first
    ``baseline`` points, or of all fit data) and clipped to +-4 so isolated
    spikes do not trigger alarms. ``S+ = max(0, S+ + z - k)`` and
    ``S- = max(0, S- - z - k)``; points where ``max(S+, S-) > h`` are flagged.
    ``k`` is half the shift (in robust std devs) the chart is tuned to catch.
    With ``period`` set, the seasonal profile is removed first.
    The statistic is capped at ``1.5 h`` so alarms clear soon after the shift ends.
    """

    name = "cusum"
    temporal = True
    default_threshold = 5.0
    description = "CUSUM change-point detection for sustained level shifts and drift."

    def __init__(
        self, k: float = 1.0, baseline: int | None = None, period: int | None = None, **kw
    ):
        super().__init__(**kw)
        self.k = k
        self.baseline = baseline
        self.period = period

    def _standardise_input(self, x: np.ndarray) -> np.ndarray:
        if self.period and np.isfinite(x).sum() >= 2 * self.period:
            s = pd.Series(x).interpolate(limit_direction="both").to_numpy()
            ref = s[: self.baseline] if self.baseline else s
            phase = np.arange(len(s)) % self.period
            ref_phase = phase[: len(ref)]
            profile = np.array(
                [
                    np.median(ref[ref_phase == p]) if np.any(ref_phase == p) else 0.0
                    for p in range(self.period)
                ]
            )
            return x - profile[phase]
        return x

    def _fit(self, X: np.ndarray) -> None:
        d = X.shape[1]
        self.mu_ = np.zeros(d)
        self.sigma_ = np.ones(d)
        for j in range(d):
            x = self._standardise_input(X[:, j])
            ref = x[: self.baseline] if self.baseline else x
            ref = ref[np.isfinite(ref)]
            if len(ref):
                _, med, mad = _robust_z(ref)
                self.mu_[j], self.sigma_[j] = med, mad or 1.0

    def _score_matrix(self, X: np.ndarray) -> np.ndarray:
        h = self.threshold or self.default_threshold
        out = np.zeros_like(X, dtype=float)
        for j in range(X.shape[1]):
            x = self._standardise_input(X[:, j])
            z = np.clip((x - self.mu_[j]) / self.sigma_[j], -4, 4)
            hi = lo = 0.0
            cap = 1.5 * h
            for i, v in enumerate(z):
                if not np.isfinite(v):
                    out[i, j] = max(hi, lo)
                    continue
                hi = min(max(0.0, hi + v - self.k), cap)
                lo = min(max(0.0, lo - v - self.k), cap)
                out[i, j] = max(hi, lo)
        return out

    def _explain(self, X, row, col, raw):
        return (
            f"{self.columns_[col]} level shift: CUSUM {raw:.1f} > {fmt(self.effective_threshold)} "
            f"(value {fmt(X[row, col])}, baseline {fmt(self.mu_[col])} +- {fmt(self.sigma_[col])})"
        )

    def get_params(self):
        return {**super().get_params(), "k": self.k, "period": self.period}


def runs(x: np.ndarray, tolerance: float = 0.0) -> list[tuple[int, int]]:
    """``(start, length)`` of every run of equal consecutive values (missing
    values break runs; values within ``tolerance`` of the run's first value
    count as equal)."""
    out = []
    n = len(x)
    i = 0
    while i < n:
        if not np.isfinite(x[i]):
            i += 1
            continue
        j = i + 1
        while j < n and np.isfinite(x[j]) and abs(x[j] - x[i]) <= tolerance:
            j += 1
        out.append((i, j - i))
        i = j
    return out


def run_lengths(x: np.ndarray, tolerance: float = 0.0) -> np.ndarray:
    """Length of the run of equal consecutive values each point belongs to
    (0 for missing values)."""
    out = np.zeros(len(x), dtype=float)
    for start, length in runs(x, tolerance):
        out[start : start + length] = length
    return out


class FlatlineDetector(Detector):
    """Stuck-at / flat-line detection: runs of identical consecutive values.

    The raw score of a point is the length of the run of equal values it
    belongs to; a run is flagged when it is longer than the threshold. By
    default the threshold is learned from the series: three times the 95th
    percentile of its run lengths, and at least ``min_run`` (5) points, so
    columns that legitimately repeat values (counts, rounded readings) are not
    flagged. Set ``threshold`` to a fixed run length (in points) to override.
    """

    name = "flatline"
    temporal = True
    default_threshold = 5.0
    description = "Runs of identical consecutive values (stuck sensor, frozen feed)."

    def __init__(self, min_run: int = 5, tolerance: float = 0.0, **kw):
        super().__init__(**kw)
        self.min_run = int(min_run)
        self.tolerance = float(tolerance)

    def _fit(self, X: np.ndarray) -> None:
        typical = []
        for j in range(X.shape[1]):
            lengths = [length for _, length in runs(X[:, j], self.tolerance)]
            if lengths:
                typical.append(float(np.percentile(lengths, 95)))
        self.auto_threshold_ = max(float(self.min_run), 3.0 * max(typical, default=1.0))

    def _auto_threshold(self, train_scores: np.ndarray) -> float:
        return self.auto_threshold_

    def _score_matrix(self, X: np.ndarray) -> np.ndarray:
        out = np.zeros_like(X, dtype=float)
        for j in range(X.shape[1]):
            out[:, j] = run_lengths(X[:, j], self.tolerance)
        out[np.isnan(X)] = np.nan
        return out

    def _explain(self, X, row, col, raw):
        return (
            f"{self.columns_[col]}={fmt(X[row, col])} repeated for {int(raw)} consecutive points "
            f"(flat line; runs longer than {fmt(self.effective_threshold)} are flagged)"
        )

    def get_params(self):
        return {**super().get_params(), "min_run": self.min_run, "tolerance": self.tolerance}
