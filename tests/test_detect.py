from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from anomalyguard.detect import (
    DETECTORS,
    CUSUMDetector,
    EnsembleDetector,
    EWMADetector,
    GroupedDetector,
    GrubbsDetector,
    IQRDetector,
    IsolationForestDetector,
    KNNDetector,
    LOFDetector,
    MADDetector,
    NotFittedError,
    RollingZScoreDetector,
    SeasonalResidualDetector,
    ZScoreDetector,
    build_detector,
    canonical_name,
    describe_detectors,
    evaluate,
    numeric_columns,
    precision_recall_f1,
    roc_auc,
    run_detectors,
)
from anomalyguard.detect.ml import average_path_length


def recall_on(labels: pd.DataFrame, pred: np.ndarray, kinds: set[str]) -> float:
    mask = labels["anomaly_type"].isin(kinds).to_numpy()
    return float(pred[mask].mean())


@pytest.mark.parametrize("cls", [ZScoreDetector, MADDetector, IQRDetector, GrubbsDetector])
def test_statistical_detectors_find_point_anomalies(tabular, cls):
    df, labels = tabular
    res = cls().fit_detect(df)
    assert recall_on(labels, res.labels, {"point"}) >= 0.95
    m = precision_recall_f1(labels["anomaly_type"].eq("point"), res.labels)
    assert m["precision"] >= 0.4
    # every univariate finding names the column that caused it
    assert all(f.column is not None and f.column in res.columns for f in res.findings)
    assert all(f.reason for f in res.findings)


@pytest.mark.parametrize(
    ("cls", "kinds", "min_recall", "min_auc"),
    [
        (LOFDetector, {"point", "correlation"}, 0.7, 0.9),
        (KNNDetector, {"point", "correlation"}, 0.5, 0.9),
        # axis-parallel isolation trees struggle with correlation anomalies
        (IsolationForestDetector, {"point"}, 0.25, 0.75),
    ],
)
def test_ml_detectors_recall(tabular, cls, kinds, min_recall, min_auc):
    df, labels = tabular
    res = cls().fit_detect(df)
    y = labels["is_anomaly"].to_numpy()
    assert recall_on(labels, res.labels, kinds) >= min_recall
    assert roc_auc(y, res.scores) >= min_auc


def test_ml_beats_univariate_on_correlation_anomalies(tabular):
    df, labels = tabular
    uni = MADDetector().fit_detect(df)
    lof = LOFDetector().fit_detect(df)
    assert (
        recall_on(labels, lof.labels, {"correlation"})
        > recall_on(labels, uni.labels, {"correlation"}) + 0.4
    )


def test_isolation_forest_simple_case():
    rng = np.random.default_rng(0)
    X = np.vstack([rng.normal(0, 1, (300, 2)), [[9, 9], [-9, 8]]])
    det = IsolationForestDetector(random_state=1).fit(X)
    scores = det.score(X)
    assert scores[-2:].min() > 0.65
    assert np.median(scores[:-2]) < 0.5
    assert set(np.flatnonzero(det.predict(X))) >= {300, 301}
    assert average_path_length(np.array([0, 1, 2]))[2] == 1.0


def test_isolation_forest_reproducible(tabular):
    df, _ = tabular
    a = IsolationForestDetector(random_state=3).fit(df).score(df)
    b = IsolationForestDetector(random_state=3).fit(df).score(df)
    assert np.allclose(a, b)


def test_multivariate_explanations_name_top_column(tabular):
    df, labels = tabular
    res = KNNDetector().fit_detect(df)
    point_rows = set(np.flatnonzero(labels["anomaly_type"].eq("point").to_numpy()))
    attributed = [f for f in res.findings if f.row in point_rows]
    assert attributed
    for f in attributed:
        assert f.column == labels.loc[f.row, "column"]
        assert "most unusual" in f.reason


def test_lof_scores_new_data():
    rng = np.random.default_rng(1)
    train = rng.normal(0, 1, (200, 2))
    det = LOFDetector(n_neighbors=10).fit(train)
    s = det.score(np.array([[0.0, 0.0], [8.0, 8.0]]))
    assert s[1] > 3 * s[0]


def test_seasonal_detector_contextual_and_point(sensor):
    df, labels = sensor
    res = SeasonalResidualDetector(columns=["temperature"], period=24).fit_detect(df)
    assert recall_on(labels, res.labels, {"point", "contextual"}) >= 0.9
    assert precision_recall_f1(labels["is_anomaly"], res.labels)["precision"] >= 0.8


def test_cusum_detects_drift_and_level_shifts(sensor):
    df, labels = sensor
    res = CUSUMDetector(columns=["temperature"], period=24).fit_detect(df)
    assert recall_on(labels, res.labels, {"drift"}) >= 0.9
    assert recall_on(labels, res.labels, {"collective"}) >= 0.7
    assert precision_recall_f1(labels["is_anomaly"], res.labels)["precision"] >= 0.7


@pytest.mark.parametrize("cls", [RollingZScoreDetector, EWMADetector])
def test_streaming_style_detectors_catch_spikes(cls):
    rng = np.random.default_rng(2)
    x = 50 + np.cumsum(rng.normal(0, 0.1, 500))  # slow random walk
    x[[200, 350]] += [8, -8]
    df = pd.DataFrame({"v": x})
    res = (
        cls(window=20).fit_detect(df)
        if cls is RollingZScoreDetector
        else cls(span=10).fit_detect(df)
    )
    assert {200, 350} <= set(np.flatnonzero(res.labels))
    assert res.labels.sum() <= 25


def test_grouped_detector_finds_contextual_anomalies(orders):
    df, labels = orders
    cols = ["quantity", "unit_price", "delivery_days"]
    glob = MADDetector(columns=cols).fit_detect(df)
    grouped = GroupedDetector(MADDetector(columns=cols), group_by="region").fit_detect(df)
    assert recall_on(labels, glob.labels, {"contextual"}) <= 0.2
    assert recall_on(labels, grouped.labels, {"contextual", "point"}) >= 0.95
    assert any(f.reason.startswith("[region=") for f in grouped.findings)
    assert grouped.detector == "grouped(mad by region)"


def test_grouped_small_groups_fall_back_to_global():
    df = pd.DataFrame(
        {
            "g": ["a"] * 50 + ["b"] * 3,
            "v": [*list(np.random.default_rng(0).normal(10, 1, 50)), 10, 11, 50],
        }
    )
    det = GroupedDetector(MADDetector(), group_by="g", min_group_size=20).fit(df)
    assert "b" not in det.detectors_
    res = det.detect(df)
    assert res.labels[-1]
    assert "global baseline" in next(f for f in res.findings if f.row == 52).reason
    with pytest.raises(TypeError):
        det.fit(np.zeros((3, 2)))


def test_ensemble_methods(tabular):
    df, labels = tabular
    members = lambda: [MADDetector(), LOFDetector(), KNNDetector()]  # noqa: E731
    vote = EnsembleDetector(members(), method="vote", min_votes=2).fit_detect(df)
    mean = EnsembleDetector(members(), method="mean").fit_detect(df)
    mx = EnsembleDetector(members(), method="max").fit_detect(df)
    w = EnsembleDetector(members(), method="weighted", weights=[1, 2, 1]).fit_detect(df)
    y = labels["is_anomaly"].to_numpy()
    assert precision_recall_f1(y, vote.labels)["precision"] >= 0.8
    assert mx.labels.sum() >= vote.labels.sum()
    assert roc_auc(y, mean.scores) > 0.9
    assert w.labels.dtype == bool
    with pytest.raises(ValueError):
        EnsembleDetector([])


def test_contamination_threshold(tabular):
    df, _ = tabular
    res = MADDetector(contamination=0.1).fit_detect(df)
    assert 0.08 <= res.labels.mean() <= 0.12
    with pytest.raises(ValueError):
        MADDetector(contamination=0.7).fit(df)


def test_threshold_multiplier_reduces_detections(tabular):
    df, _ = tabular
    det = ZScoreDetector().fit(df)
    n1 = det.predict(df).sum()
    det.threshold_multiplier = 2.0
    assert det.predict(df).sum() < n1


def test_not_fitted_and_bad_input():
    with pytest.raises(NotFittedError):
        ZScoreDetector().score(np.zeros((3, 1)))
    with pytest.raises(ValueError):
        ZScoreDetector().fit(pd.DataFrame({"s": ["a", "b"]}))
    with pytest.raises(KeyError):
        ZScoreDetector(columns=["nope"]).fit(pd.DataFrame({"a": [1.0]}))


def test_numeric_columns_skip_ids_and_bools():
    df = pd.DataFrame(
        {
            "order_id": [1, 2],
            "flag": [True, False],
            "v": [1.0, 2.0],
            "s": ["1", "x"],
            "n": ["1", "2"],
        }
    )
    assert numeric_columns(df) == ["v", "n"]


def test_registry_and_build(tabular):
    assert canonical_name("Isolation-Forest") == "iforest"
    assert canonical_name("modified_zscore") == "mad"
    with pytest.raises(KeyError):
        canonical_name("magic")
    det = build_detector({"method": "iforest", "n_estimators": 10, "columns": ["f0", "f1"]})
    assert isinstance(det, IsolationForestDetector) and det.n_estimators == 10
    assert isinstance(build_detector({"method": "mad", "group_by": "g"}), GroupedDetector)
    ens = build_detector(
        {"method": "ensemble", "detectors": ["mad", "iqr"], "combine": "vote", "min_votes": 2}
    )
    assert isinstance(ens, EnsembleDetector) and ens.min_votes == 2
    with pytest.raises(ValueError):
        build_detector({"method": "mad", "nonsense": 1})
    names = {d["name"] for d in describe_detectors()}
    assert set(DETECTORS) <= names and {"grouped", "ensemble"} <= names


def test_run_detectors_report(orders):
    df, _ = orders
    df = df.copy()
    df["unit_price"] = pd.to_numeric(df["unit_price"], errors="coerce")
    report = run_detectors(df, "mad,iforest", columns=["quantity", "unit_price", "delivery_days"])
    assert report.detectors == ["mad", "iforest"]
    assert report.n_anomalies == int(report.flagged.sum())
    recs = report.records(limit=5)
    assert len(recs) == 5 and recs[0]["score"] >= recs[-1]["score"]
    assert recs[0]["reasons"]
    vote = run_detectors(
        df, ["mad", "iforest"], columns=["quantity", "unit_price"], combine="vote", min_votes=2
    )
    assert vote.n_anomalies <= report.n_anomalies
    mask = report.column_mask(["quantity", "unit_price"])
    assert mask.to_numpy().any()
    d = report.to_dict(limit=3)
    assert d["summary"]["n_rows"] == len(df) and len(d["anomalies"]) == 3
    assert not report.to_frame().empty


def test_run_detectors_time_column_restores_order():
    rng = np.random.default_rng(0)
    n = 300
    ts = pd.date_range("2026-01-01", periods=n, freq="h")
    v = 10 + rng.normal(0, 0.2, n)
    v[150] = 20
    df = pd.DataFrame({"ts": ts.astype(str), "v": v}).sample(frac=1, random_state=1)  # shuffled
    report = run_detectors(
        df, [{"method": "rolling_zscore", "window": 24}], columns=["v"], time_column="ts"
    )
    flagged_labels = [df.index[r] for r in report.anomalous_rows]
    assert 150 in flagged_labels
    assert all(f.index == df.index[f.row] for f in report.findings)


def test_evaluation_helpers():
    y = np.array([1, 1, 0, 0, 0])
    p = np.array([1, 0, 1, 0, 0])
    m = evaluate(y, p, scores=np.array([0.9, 0.8, 0.7, 0.1, 0.2]))
    assert m["precision"] == 0.5 and m["recall"] == 0.5 and m["tp"] == 1
    assert m["roc_auc"] == pytest.approx(1.0)
    assert np.isnan(roc_auc(np.zeros(3), np.arange(3)))
