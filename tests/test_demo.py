from __future__ import annotations

import numpy as np
import pytest

from anomalyguard.demo import (
    generate,
    generate_orders,
    generate_sensor,
    generate_tabular,
    run_benchmark,
)


def test_orders_generator_injects_every_type():
    df, labels = generate_orders(n_rows=1000, seed=1)
    assert len(df) == len(labels) == 1000
    counts = labels[labels["is_anomaly"]]["anomaly_type"].value_counts().to_dict()
    assert counts == {
        "point": 20,
        "contextual": 15,
        "missing": 10,
        "duplicate": 10,
        "type_error": 5,
    }
    dup_rows = labels.index[labels["anomaly_type"] == "duplicate"]
    assert df.duplicated(keep="first").iloc[dup_rows].all()
    assert df["unit_price"].map(lambda v: isinstance(v, str)).sum() == 5
    # determinism
    df2, _ = generate_orders(n_rows=1000, seed=1)
    assert df.equals(df2)


def test_sensor_generator():
    df, labels = generate_sensor(n_points=24 * 30, seed=3)
    kinds = set(labels["anomaly_type"]) - {""}
    assert kinds == {"point", "contextual", "collective", "drift", "missing"}
    assert df["temperature"].isna().sum() == (labels["anomaly_type"] == "missing").sum()
    assert list(df.columns) == ["timestamp", "sensor_id", "temperature", "humidity"]


def test_tabular_generator():
    df, labels = generate_tabular(n_rows=500, n_features=4, anomaly_rate=0.1, seed=2)
    assert df.shape == (500, 4)
    assert labels["is_anomaly"].sum() == 50
    corr = np.corrcoef(df[~labels["is_anomaly"]].to_numpy().T)
    assert np.abs(corr[np.triu_indices(4, 1)]).max() > 0.5  # features are correlated


def test_generate_dispatch():
    assert len(generate("tabular", rows=100)[0]) == 100
    with pytest.raises(KeyError):
        generate("nope")


def test_benchmark_small():
    rep = run_benchmark(["orders", "sensor"], rows={"orders": 600, "sensor": 24 * 30})
    df = rep.to_frame()
    assert set(df["dataset"]) == {"orders", "sensor"}
    assert df[["precision", "recall", "f1"]].apply(lambda c: c.between(0, 1).all()).all()
    grouped = df[df["detector"] == "mad by region"].iloc[0]
    assert grouped["recall"] >= 0.9
    assert {q["type"] for q in rep.quality} == {"missing", "type_error", "duplicate"}
    assert all(q["recall"] == 1.0 for q in rep.quality)
    md = rep.to_markdown()
    assert "### orders" in md and "| Detector |" in md
    assert rep.best()["sensor"]
