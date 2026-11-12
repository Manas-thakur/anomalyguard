from __future__ import annotations

import pytest

from anomalyguard.monitor import FeedbackLoop, MetricsStore
from anomalyguard.remediate import ReviewQueue


def seed_store(path) -> tuple[MetricsStore, int]:
    store = MetricsStore(path)
    run_id = store.start_run("orders")
    store.finish_run(
        run_id,
        {
            "rows": 100,
            "n_anomalies": 5,
            "anomaly_rate": 0.05,
            "quality_score": 0.97,
            "alerts_sent": 1,
        },
        detectors={"mad": 5},
    )
    store.add_anomalies(
        run_id,
        [
            {
                "index": i,
                "column": "price",
                "detector": "mad",
                "score": 2.0 + i,
                "value": 100.0 * i,
                "reason": f"r{i}",
            }
            for i in range(5)
        ],
    )
    store.add_alerts(
        run_id,
        [{"severity": "warning", "title": "rate high", "status": "sent", "channels": ["console"]}],
    )
    return store, run_id


def test_store_runs_and_summary(tmp_path):
    store, run_id = seed_store(tmp_path / "m.db")
    store.record_run("orders", {"rows": 10}, status="failed", error="boom")
    runs = store.runs()
    assert [r["status"] for r in runs] == ["failed", "success"]
    assert store.get_run(run_id)["metrics"]["quality_score"] == 0.97
    assert store.get_run(999) is None
    assert store.last_run("orders")["id"] == run_id
    anomalies = store.anomalies(run_id)
    assert anomalies[0]["score"] == 6.0 and anomalies[0]["row_index"] == 4
    s = store.summary()
    assert (
        s["runs"] == 1
        and s["failed_runs"] == 1
        and s["rows_processed"] == 100
        and s["pipelines"] == ["orders"]
    )
    assert store.alerts()[0]["title"] == "rate high"


def test_feedback_loop_tunes_thresholds(tmp_path):
    store, run_id = seed_store(tmp_path / "m.db")
    loop = FeedbackLoop(store, target_precision=0.8, step=0.25, min_feedback=3)
    ids = [a["id"] for a in store.anomalies(run_id)]
    for aid in ids[:3]:
        loop.mark_false_positive(anomaly_id=aid)
    loop.mark_true_positive(anomaly_id=ids[3])
    assert loop.precision()["mad"]["precision"] == pytest.approx(0.25)
    changes = loop.tune()
    assert len(changes) == 1 and changes[0].new == pytest.approx(1.25)
    assert store.thresholds() == {"mad": 1.25}
    # the same feedback does not move the threshold twice
    assert loop.tune() == []
    # new, positive feedback relaxes it again
    for _ in range(3):
        loop.mark_true_positive(detector="mad")
    assert loop.tune()[0].new == pytest.approx(1.0)
    with pytest.raises(KeyError):
        loop.mark_false_positive(anomaly_id=12345)
    with pytest.raises(ValueError):
        loop.mark("false_positive")
    with pytest.raises(ValueError):
        store.add_feedback("mad", "maybe")


def test_api_endpoints(tmp_path):
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    from anomalyguard.monitor.api import create_app

    db = tmp_path / "m.db"
    _store, run_id = seed_store(db)
    q = ReviewQueue(db)
    item = q.add("price", 900, "outlier", row_index=2, pipeline="orders", suggestion=90)
    client = TestClient(create_app(db))

    assert client.get("/health").json()["status"] == "ok"
    page = client.get("/")
    assert page.status_code == 200 and "<title>AnomalyGuard</title>" in page.text
    summary = client.get("/api/summary").json()
    assert summary["runs"] == 1 and summary["review"]["pending"] == 1
    assert client.get("/api/runs").json()[0]["id"] == run_id
    assert client.get(f"/api/runs/{run_id}").json()["rows"] == 100
    assert client.get("/api/runs/999").status_code == 404
    anomalies = client.get(f"/api/runs/{run_id}/anomalies").json()
    assert len(anomalies) == 5
    assert client.get("/api/alerts").json()[0]["severity"] == "warning"

    assert client.get("/api/review").json()[0]["id"] == item
    assert (
        client.post(f"/api/review/{item}/approve", json={"value": 95}).json()["resolved_value"]
        == 95
    )
    assert client.post("/api/review/999/reject").status_code == 404

    for a in anomalies[:3]:
        assert (
            client.post(
                "/api/feedback", json={"anomaly_id": a["id"], "label": "false_positive"}
            ).status_code
            == 200
        )
    assert client.post("/api/feedback", json={"label": "false_positive"}).status_code == 422
    assert client.get("/api/feedback").json()["precision"]["mad"]["false_positive"] == 3
    tuned = client.post("/api/feedback/tune").json()
    assert tuned["thresholds"]["mad"] > 1.0
    assert client.get("/api/thresholds").json()[0]["detector"] == "mad"
