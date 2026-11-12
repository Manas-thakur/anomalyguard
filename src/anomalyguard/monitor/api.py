"""FastAPI backend for the dashboard (install with ``anomalyguard[server]``)."""

from __future__ import annotations

from importlib import resources
from pathlib import Path
from typing import Any

from fastapi import Body, FastAPI, HTTPException, Query
from fastapi.responses import HTMLResponse

from anomalyguard import __version__
from anomalyguard.monitor.feedback import FeedbackLoop
from anomalyguard.monitor.store import DEFAULT_DB, MetricsStore
from anomalyguard.remediate.review import ReviewQueue


def dashboard_html() -> str:
    return (
        resources.files("anomalyguard.monitor")
        .joinpath("static/dashboard.html")
        .read_text(encoding="utf-8")
    )


def create_app(db_path: str | Path = DEFAULT_DB) -> FastAPI:
    store = MetricsStore(db_path)
    queue = ReviewQueue(db_path)
    loop = FeedbackLoop(store)
    app = FastAPI(
        title="AnomalyGuard",
        version=__version__,
        docs_url="/api/docs",
        openapi_url="/api/openapi.json",
    )
    app.state.store = store
    app.state.queue = queue

    @app.get("/", response_class=HTMLResponse, include_in_schema=False)
    def index() -> str:
        return dashboard_html()

    @app.get("/health")
    def health() -> dict[str, Any]:
        return {"status": "ok", "version": __version__, "db": str(store.path)}

    @app.get("/api/summary")
    def summary() -> dict[str, Any]:
        return {**store.summary(), "review": queue.counts(), "thresholds": store.thresholds()}

    @app.get("/api/runs")
    def runs(
        limit: int = Query(100, ge=1, le=1000), pipeline: str | None = None
    ) -> list[dict[str, Any]]:
        return store.runs(limit=limit, pipeline=pipeline)

    @app.get("/api/runs/{run_id}")
    def run(run_id: int) -> dict[str, Any]:
        r = store.get_run(run_id)
        if r is None:
            raise HTTPException(404, "run not found")
        return r

    @app.get("/api/runs/{run_id}/anomalies")
    def anomalies(run_id: int, limit: int = Query(200, ge=1, le=5000)) -> list[dict[str, Any]]:
        return store.anomalies(run_id, limit)

    @app.get("/api/alerts")
    def alerts(limit: int = Query(100, ge=1, le=1000)) -> list[dict[str, Any]]:
        return store.alerts(limit)

    @app.get("/api/review")
    def review(
        status: str | None = "pending", limit: int = Query(100, ge=1, le=1000)
    ) -> list[dict[str, Any]]:
        return queue.list(status=status or None, limit=limit)

    @app.post("/api/review/{item_id}/approve")
    def approve(item_id: int, payload: dict[str, Any] | None = Body(None)) -> dict[str, Any]:
        payload = payload or {}
        try:
            return queue.approve(item_id, value=payload.get("value"), note=payload.get("note"))
        except KeyError as exc:
            raise HTTPException(404, str(exc)) from exc

    @app.post("/api/review/{item_id}/reject")
    def reject(item_id: int, payload: dict[str, Any] | None = Body(None)) -> dict[str, Any]:
        payload = payload or {}
        try:
            return queue.reject(item_id, note=payload.get("note"))
        except KeyError as exc:
            raise HTTPException(404, str(exc)) from exc

    @app.post("/api/feedback")
    def feedback(payload: dict[str, Any] = Body(...)) -> dict[str, Any]:
        label = payload.get("label", "false_positive")
        try:
            fid = loop.mark(
                label,
                anomaly_id=payload.get("anomaly_id"),
                detector=payload.get("detector"),
                run_id=payload.get("run_id"),
                row_index=payload.get("row_index"),
                column=payload.get("column"),
                note=payload.get("note"),
            )
        except KeyError as exc:
            raise HTTPException(404, str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        return {"id": fid, "label": label}

    @app.get("/api/feedback")
    def feedback_stats() -> dict[str, Any]:
        return {"precision": loop.precision(), "recent": store.feedback(50)}

    @app.post("/api/feedback/tune")
    def tune() -> dict[str, Any]:
        return {"changes": [c.to_dict() for c in loop.tune()], "thresholds": store.thresholds()}

    @app.get("/api/thresholds")
    def thresholds() -> list[dict[str, Any]]:
        return store.threshold_details()

    return app
