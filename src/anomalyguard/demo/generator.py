"""Synthetic datasets with injected anomalies and ground-truth labels.

Every generator returns ``(data, labels)`` where ``labels`` has one row per
data row with ``is_anomaly`` (bool), ``anomaly_type`` and ``column``.

Anomaly types:

========== ====================================================== ==========
type       example                                                datasets
========== ====================================================== ==========
point      unit price x20, quantity 300, a +10 degree spike        all
contextual a west-region price in the north; daytime temp at 3am   orders, sensor
collective a run of 12 consecutive readings shifted by +3.5        sensor
drift      gradual upward drift over the last 10% of the series    sensor
correlation features individually normal but jointly implausible    tabular
missing    nulls in required columns / a gap of readings           orders, sensor
type_error ``"unknown"`` in a numeric column                        orders
duplicate  an exact copy of another row                            orders
========== ====================================================== ==========
"""

from __future__ import annotations

import numpy as np
import pandas as pd

REGION_PRICE = {"north": 20.0, "south": 45.0, "east": 90.0, "west": 150.0}
REGION_P = [0.3, 0.3, 0.25, 0.15]
STATUSES = ["completed", "pending", "cancelled", "returned"]
STATUS_P = [0.8, 0.1, 0.05, 0.05]
TYPE_ERRORS = ["unknown", "#VALUE!", "ten", "n/a?", "error"]


def _labels(n: int) -> pd.DataFrame:
    return pd.DataFrame(
        {"is_anomaly": np.zeros(n, dtype=bool), "anomaly_type": [""] * n, "column": [""] * n}
    )


def _mark(labels: pd.DataFrame, rows, kind: str, column: str) -> None:
    rows = list(rows)
    labels.loc[rows, "is_anomaly"] = True
    labels.loc[rows, "anomaly_type"] = kind
    labels.loc[rows, "column"] = column


def generate_orders(
    n_rows: int = 1000,
    seed: int = 42,
    point_rate: float = 0.02,
    contextual_rate: float = 0.015,
    missing_rate: float = 0.01,
    type_error_rate: float = 0.005,
    duplicate_rate: float = 0.01,
    start: str = "2026-01-01",
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """E-commerce orders with point, contextual, missing, type-error and
    duplicate anomalies. Unit prices depend on the region, which makes
    contextual anomalies (a west-level price in the north) invisible to global
    detectors but visible to ``GroupedDetector`` (``group_by=region``)."""
    rng = np.random.default_rng(seed)
    n_dup = round(n_rows * duplicate_rate)
    n_base = n_rows - n_dup
    regions = rng.choice(list(REGION_PRICE), size=n_base, p=REGION_P)
    base_price = np.array([REGION_PRICE[r] for r in regions])
    unit_price = np.round(base_price * rng.lognormal(0, 0.1, n_base), 2)
    quantity = rng.poisson(3, n_base) + 1
    df = pd.DataFrame(
        {
            "order_id": np.arange(100001, 100001 + n_base),
            "timestamp": pd.date_range(start, periods=n_base, freq="30min").strftime(
                "%Y-%m-%d %H:%M:%S"
            ),
            "customer_id": [f"C{v:04d}" for v in rng.integers(1, 400, n_base)],
            "region": regions,
            "quantity": quantity.astype(float),
            "unit_price": unit_price,
            "delivery_days": (rng.poisson(3, n_base) + 1).astype(float),
            "status": rng.choice(STATUSES, size=n_base, p=STATUS_P),
        }
    )
    labels = _labels(n_base)
    free = list(rng.permutation(n_base))

    def take(k: int) -> list[int]:
        out = [int(free.pop()) for _ in range(min(k, len(free)))]
        return sorted(out)

    # point anomalies: extreme price / quantity / delivery time
    rows = take(round(n_rows * point_rate))
    for i, r in enumerate(rows):
        kind = i % 3
        if kind == 0:
            df.loc[r, "unit_price"] = round(df.loc[r, "unit_price"] * rng.uniform(15, 40), 2)
            col = "unit_price"
        elif kind == 1:
            df.loc[r, "quantity"] = float(rng.integers(150, 500))
            col = "quantity"
        else:
            df.loc[r, "delivery_days"] = float(rng.integers(40, 90))
            col = "delivery_days"
        _mark(labels, [r], "point", col)

    # contextual anomalies: a west-level price in a cheap region
    cheap = [r for r in free if df.loc[r, "region"] in ("north", "south")]
    k = round(n_rows * contextual_rate)
    rows = sorted(int(r) for r in rng.choice(cheap, size=min(k, len(cheap)), replace=False))
    for r in rows:
        free.remove(r)
        df.loc[r, "unit_price"] = round(REGION_PRICE["west"] * rng.lognormal(0, 0.08), 2)
    _mark(labels, rows, "contextual", "unit_price")

    # missing values
    rows = take(round(n_rows * missing_rate))
    for i, r in enumerate(rows):
        col = ["quantity", "region", "delivery_days"][i % 3]
        df.loc[r, col] = np.nan
        _mark(labels, [r], "missing", col)

    # type errors (strings in a numeric column)
    df["unit_price"] = df["unit_price"].astype(object)
    rows = take(round(n_rows * type_error_rate))
    for i, r in enumerate(rows):
        df.loc[r, "unit_price"] = TYPE_ERRORS[i % len(TYPE_ERRORS)]
        _mark(labels, [r], "type_error", "unit_price")

    # duplicates: exact copies of normal rows inserted right after the original
    if n_dup:
        src = sorted(int(r) for r in rng.choice(free, size=min(n_dup, len(free)), replace=False))
        dup_rows = df.loc[src]
        dup_labels = _labels(len(src))
        dup_labels["is_anomaly"] = True
        dup_labels["anomaly_type"] = "duplicate"
        dup_labels["column"] = "order_id"
        dup_rows.index = [s + 0.5 for s in src]
        dup_labels.index = dup_rows.index
        df = pd.concat([df, dup_rows]).sort_index().reset_index(drop=True)
        labels = pd.concat([labels, dup_labels]).sort_index().reset_index(drop=True)

    return df, labels


def generate_sensor(
    n_points: int = 24 * 60,
    seed: int = 42,
    period: int = 24,
    noise: float = 0.5,
    amplitude: float = 5.0,
    n_point: int = 10,
    n_contextual: int = 8,
    n_collective: int = 2,
    collective_length: int = 12,
    drift_fraction: float = 0.1,
    drift_size: float = 6.0,
    gap_length: int = 6,
    trend_per_step: float = 0.0002,
    start: str = "2026-01-01",
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Hourly temperature with daily seasonality, a slow trend and point,
    contextual, collective, drift and missing-gap anomalies."""
    rng = np.random.default_rng(seed)
    t = np.arange(n_points)
    hour = t % period
    seasonal = amplitude * np.sin(2 * np.pi * (hour - period / 4 - 3) / period)
    value = 20.0 + trend_per_step * t + seasonal + rng.normal(0, noise, n_points)
    labels = _labels(n_points)

    drift_start = int(n_points * (1 - drift_fraction))
    usable = np.arange(period * 2, drift_start - period)
    taken: set[int] = set()

    def pick_rows(candidates: np.ndarray, k: int, width: int = 1) -> list[int]:
        out: list[int] = []
        cands = list(rng.permutation(candidates))
        while cands and len(out) < k:
            c = int(cands.pop())
            span = set(range(c - 2, c + width + 2))
            if span & taken:
                continue
            taken.update(span)
            out.append(c)
        return sorted(out)

    for r in pick_rows(usable, n_point):
        value[r] += rng.choice([-1, 1]) * rng.uniform(6, 10) * noise * 2
        _mark(labels, [r], "point", "temperature")

    # contextual: night-time hours get a daytime-peak reading
    night = usable[(hour[usable] >= 0) & (hour[usable] <= 4)]
    peak = 20.0 + amplitude
    for r in pick_rows(night, n_contextual):
        value[r] = peak + trend_per_step * r + rng.normal(0, noise)
        _mark(labels, [r], "contextual", "temperature")

    starts = pick_rows(
        usable[usable < drift_start - collective_length - period], n_collective, collective_length
    )
    for s in starts:
        seg = list(range(s, s + collective_length))
        value[seg] += 3.5
        _mark(labels, seg, "collective", "temperature")

    ramp = np.linspace(0, drift_size, n_points - drift_start)
    value[drift_start:] += ramp
    drift_rows = [drift_start + i for i, v in enumerate(ramp) if v > 1.5]
    _mark(labels, drift_rows, "drift", "temperature")

    gap = pick_rows(usable, 1, gap_length)
    if gap:
        rows = list(range(gap[0], gap[0] + gap_length))
        value[rows] = np.nan
        _mark(labels, rows, "missing", "temperature")

    df = pd.DataFrame(
        {
            "timestamp": pd.date_range(start, periods=n_points, freq="h").strftime(
                "%Y-%m-%d %H:%M:%S"
            ),
            "sensor_id": "S-01",
            "temperature": np.round(value, 3),
            "humidity": np.round(55 - 0.8 * seasonal + rng.normal(0, 1.5, n_points), 2),
        }
    )
    return df, labels


def generate_tabular(
    n_rows: int = 2000,
    n_features: int = 6,
    anomaly_rate: float = 0.05,
    seed: int = 42,
    n_factors: int = 2,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Correlated multivariate Gaussian data (a low-rank factor model).

    Half the anomalies are ``point`` (one feature 6-10 std devs out). The other
    half are ``correlation`` anomalies: every feature stays within its normal
    range but the joint structure is broken - univariate detectors cannot see
    them, multivariate ones can.
    """
    rng = np.random.default_rng(seed)
    W = rng.normal(0, 1, (n_factors, n_features))
    Z = rng.normal(0, 1, (n_rows, n_factors))
    X = Z @ W + rng.normal(0, 0.3, (n_rows, n_features))
    std = X.std(axis=0)
    labels = _labels(n_rows)
    n_anom = round(n_rows * anomaly_rate)
    rows = rng.choice(n_rows, size=n_anom, replace=False)
    half = n_anom // 2
    for r in rows[:half]:
        j = int(rng.integers(n_features))
        X[r, j] = rng.choice([-1, 1]) * rng.uniform(6, 10) * std[j]
        _mark(labels, [int(r)], "point", f"f{j}")
    for r in rows[half:]:
        X[r] = rng.normal(0, 1, n_features) * std * 0.9
        _mark(labels, [int(r)], "correlation", "")
    df = pd.DataFrame(np.round(X, 4), columns=[f"f{j}" for j in range(n_features)])
    return df, labels


DATASETS = {
    "orders": generate_orders,
    "sensor": generate_sensor,
    "tabular": generate_tabular,
}


def generate(
    kind: str = "orders", rows: int | None = None, seed: int = 42
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Generate a named dataset (``orders``, ``sensor`` or ``tabular``)."""
    if kind not in DATASETS:
        raise KeyError(f"Unknown dataset '{kind}'. Available: {', '.join(DATASETS)}")
    if kind == "sensor":
        return generate_sensor(n_points=rows or 24 * 60, seed=seed)
    if kind == "tabular":
        return generate_tabular(n_rows=rows or 2000, seed=seed)
    return generate_orders(n_rows=rows or 1000, seed=seed)
