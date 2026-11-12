"""FastAPI backend for the web app (install with ``anomalyguard[server]``).

The UI is plain HTML/CSS/JS in ``monitor/static`` (no build step). Everything
it does goes through the JSON API below; OpenAPI docs are at ``/api/docs``.
"""

from __future__ import annotations

import hmac
import os
from collections.abc import Iterator
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from fastapi import Body, FastAPI, File, HTTPException, Query, Request, Response, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from anomalyguard import __version__
from anomalyguard.monitor import doctor
from anomalyguard.monitor.catalog import PipelineCatalog, templates
from anomalyguard.monitor.feedback import FeedbackLoop
from anomalyguard.monitor.jobs import JobManager
from anomalyguard.monitor.settings import ServerSettings
from anomalyguard.monitor.store import ANALYSIS_PREFIX, DEFAULT_DB, MetricsStore
from anomalyguard.monitor.workspace import (
    NotFound,
    UploadTooLarge,
    Workspace,
    WorkspaceError,
    detector_catalog,
    jsonable,
)
from anomalyguard.remediate.review import ReviewQueue

STATIC_DIR = Path(__file__).resolve().parent / "static"
OPEN_API_PATHS = {"/api/auth"}
NON_DETECTOR_SOURCES = {"missing", "type", "schema"}
BULK_ACTIONS = {"approve", "reject", "apply", "false_positive"}
MAX_BULK = 10_000
CHUNK = 1024 * 1024


class _StaticFiles(StaticFiles):
    """Static assets that the browser revalidates, so an upgrade is never half-cached."""

    async def get_response(self, path: str, scope):  # type: ignore[override]
        response = await super().get_response(path, scope)
        response.headers["Cache-Control"] = "no-cache"
        return response


def dashboard_html() -> str:
    return (STATIC_DIR / "index.html").read_text(encoding="utf-8")


def _total(response: Response, total: int) -> None:
    response.headers["X-Total-Count"] = str(total)


def _key_from(request: Request) -> str | None:
    key = request.headers.get("x-api-key")
    if key:
        return key.strip()
    auth = request.headers.get("authorization", "")
    if auth.lower().startswith("bearer "):
        return auth[7:].strip()
    return None


def _key_ok(given: str | None, expected: str | None) -> bool:
    if not expected:
        return True
    return bool(given) and hmac.compare_digest(given.encode("utf-8"), expected.encode("utf-8"))


def _within(path: Path, roots: list[Path]) -> bool:
    rp = path.resolve()
    for root in roots:
        try:
            rp.relative_to(root.resolve())
            return True
        except ValueError:
            continue
    return False


def create_app(db_path: str | Path = DEFAULT_DB, settings: ServerSettings | None = None) -> FastAPI:
    settings = settings or ServerSettings.from_env()
    db_path = Path(db_path)
    state_dir = db_path.parent
    store = MetricsStore(db_path)
    queue = ReviewQueue(db_path)
    loop = FeedbackLoop(store)
    jobs = JobManager(db_path, workers=settings.workers)
    workspace = Workspace(state_dir, store, queue)
    catalog = PipelineCatalog(settings.pipeline_dirs, store, state_dir)

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        yield
        jobs.shutdown(wait=False)

    app = FastAPI(
        lifespan=lifespan,
        title="AnomalyGuard",
        version=__version__,
        docs_url="/api/docs",
        openapi_url="/api/openapi.json",
        redoc_url=None,
    )
    app.state.store = store
    app.state.queue = queue
    app.state.jobs = jobs
    app.state.workspace = workspace
    app.state.catalog = catalog
    app.state.settings = settings

    # -- middleware: API key + security headers (CORS is added last = outermost)
    @app.middleware("http")
    async def guard(request: Request, call_next):
        path = request.url.path
        if (
            settings.api_key
            and path.startswith("/api/")
            and path not in OPEN_API_PATHS
            and request.method != "OPTIONS"
            and not _key_ok(_key_from(request), settings.api_key)
        ):
            return JSONResponse(
                {"detail": "Missing or invalid API key (send it in the X-API-Key header)"},
                status_code=401,
                headers={"WWW-Authenticate": "ApiKey"},
            )
        response = await call_next(request)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("Referrer-Policy", "same-origin")
        response.headers.setdefault("X-Frame-Options", "DENY")
        return response

    if settings.cors_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=settings.cors_origins,
            allow_methods=["GET", "POST", "PUT", "DELETE"],
            allow_headers=["X-API-Key", "Authorization", "Content-Type"],
            expose_headers=["X-Total-Count", "Content-Disposition"],
        )

    @app.exception_handler(NotFound)
    async def _not_found(_request: Request, exc: NotFound) -> JSONResponse:
        return JSONResponse({"detail": str(exc.args[0] if exc.args else exc)}, status_code=404)

    @app.exception_handler(WorkspaceError)
    async def _bad_input(_request: Request, exc: WorkspaceError) -> JSONResponse:
        code = 413 if isinstance(exc, UploadTooLarge) else 422
        return JSONResponse({"detail": str(exc)}, status_code=code)

    # -- pages ----------------------------------------------------------------
    if STATIC_DIR.is_dir():
        app.mount("/static", _StaticFiles(directory=STATIC_DIR), name="static")

    @app.get("/", response_class=HTMLResponse, include_in_schema=False)
    def index() -> HTMLResponse:
        return HTMLResponse(dashboard_html(), headers={"Cache-Control": "no-cache"})

    @app.get("/health")
    def health() -> dict[str, Any]:
        return {"status": "ok", "version": __version__, "db": str(store.path)}

    @app.get("/api/auth")
    def auth_status(request: Request) -> dict[str, Any]:
        """Whether an API key is required and whether this request carries a valid one."""
        return {
            "auth_enabled": settings.auth_enabled,
            "authenticated": _key_ok(_key_from(request), settings.api_key),
        }

    # -- overview -----------------------------------------------------------
    @app.get("/api/summary")
    def summary() -> dict[str, Any]:
        active = [j for j in jobs.list(limit=20) if j["status"] in ("queued", "running")]
        return {
            **store.summary(),
            "review": queue.counts(),
            "thresholds": store.thresholds(),
            "analyses": store.count_runs(kind="analysis"),
            "datasets": len(workspace.list_datasets()),
            "jobs_active": len(active),
        }

    @app.get("/api/metrics/series")
    def series(
        pipeline: str | None = None,
        days: float | None = Query(None, gt=0, le=3650),
        kind: str | None = Query(None, pattern="^(analysis|pipeline)$"),
    ) -> dict[str, Any]:
        """Run metrics over time, grouped per pipeline (for the overview charts)."""
        since = None
        if days:
            since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat(
                timespec="seconds"
            )
        grouped: dict[str, list[dict[str, Any]]] = {}
        for r in store.series(pipeline=pipeline, since=since):
            is_analysis = r["pipeline"].startswith(ANALYSIS_PREFIX)
            if (kind == "analysis" and not is_analysis) or (kind == "pipeline" and is_analysis):
                continue
            grouped.setdefault(r["pipeline"], []).append(r)
        return {
            "since": since,
            "series": [{"pipeline": k, "points": v} for k, v in sorted(grouped.items())],
        }

    # -- runs -------------------------------------------------------------------
    @app.get("/api/runs")
    def runs(
        response: Response,
        limit: int = Query(100, ge=1, le=1000),
        offset: int = Query(0, ge=0),
        pipeline: str | None = None,
        status: str | None = None,
        kind: str | None = Query(None, pattern="^(analysis|pipeline)$"),
        q: str | None = None,
    ) -> list[dict[str, Any]]:
        """Run history, newest first. The total match count is in ``X-Total-Count``."""
        _total(response, store.count_runs(pipeline, status, kind, q))
        return store.runs(limit, pipeline, status, kind, q, offset)

    def _run_or_404(run_id: int) -> dict[str, Any]:
        r = store.get_run(run_id)
        if r is None:
            raise HTTPException(404, "run not found")
        return r

    def _run_artifacts(run: dict[str, Any]) -> dict[str, Path]:
        metrics = run.get("metrics") or {}
        out: dict[str, Path] = {}
        analysis_id = metrics.get("analysis_id")
        if analysis_id:
            try:
                for name in workspace.available_artifacts(analysis_id):
                    out[name] = workspace.artifact(analysis_id, name)[0]
            except NotFound:
                pass
        roots = [Path.cwd(), state_dir, *[d.resolve().parent for d in settings.pipeline_dirs]]
        for key, value in (metrics.get("outputs") or {}).items():
            p = Path(str(value))
            if p.is_file() and _within(p, roots):
                out[f"{key}{p.suffix}"] = p
        return out

    @app.get("/api/runs/{run_id}")
    def run(run_id: int) -> dict[str, Any]:
        r = _run_or_404(run_id)
        r["breakdown"] = store.anomaly_breakdown(run_id)
        r["alerts"] = store.alerts(limit=100, run_id=run_id)
        r["artifacts"] = sorted(_run_artifacts(r))
        r["kind"] = "analysis" if r["pipeline"].startswith(ANALYSIS_PREFIX) else "pipeline"
        r["review"] = queue.query(status=None, run_id=run_id, limit=1)[1]
        return r

    @app.get("/api/runs/{run_id}/anomalies")
    def anomalies(
        run_id: int,
        response: Response,
        limit: int = Query(200, ge=1, le=5000),
        offset: int = Query(0, ge=0),
        column: str | None = None,
        detector: str | None = None,
        severity: str | None = None,
        q: str | None = None,
        sort: str = Query("score", pattern="^(score|row|column|detector|id)$"),
        order: str = Query("desc", pattern="^(asc|desc)$"),
    ) -> list[dict[str, Any]]:
        _total(response, store.count_anomalies(run_id, column, detector, severity, q))
        return store.anomalies(
            run_id,
            limit,
            offset,
            column,
            detector,
            severity,
            q=q,
            sort=sort,
            descending=order == "desc",
        )

    @app.get("/api/runs/{run_id}/artifacts/{name}")
    def run_artifact(run_id: int, name: str) -> FileResponse:
        arts = _run_artifacts(_run_or_404(run_id))
        if name not in arts:
            raise HTTPException(404, f"artifact '{name}' not found for run {run_id}")
        path = arts[name]
        return FileResponse(path, filename=f"run{run_id}_{path.name}")

    @app.get("/api/alerts")
    def alerts(
        limit: int = Query(100, ge=1, le=1000), run_id: int | None = None
    ) -> list[dict[str, Any]]:
        return store.alerts(limit, run_id=run_id)

    # -- review queue -----------------------------------------------------------
    @app.get("/api/review")
    def review(
        response: Response,
        status: str | None = "pending",
        limit: int = Query(100, ge=1, le=1000),
        offset: int = Query(0, ge=0),
        pipeline: str | None = None,
        column: str | None = None,
        detector: str | None = None,
        run_id: int | None = None,
        q: str | None = None,
        sort: str = Query("id", pattern="^(id|created_at|column|pipeline|status|detector)$"),
        order: str = Query("desc", pattern="^(asc|desc)$"),
    ) -> list[dict[str, Any]]:
        """Review items (``status=all`` for every status); total in ``X-Total-Count``."""
        items, total = queue.query(
            status=None if status in (None, "", "all") else status,
            pipeline=pipeline,
            column=column,
            detector=detector,
            run_id=run_id,
            q=q,
            offset=offset,
            limit=limit,
            sort=sort,
            descending=order == "desc",
        )
        _total(response, total)
        return items

    @app.get("/api/review/facets")
    def review_facets(status: str | None = None) -> dict[str, Any]:
        return queue.facets(None if status in (None, "", "all") else status)

    def _false_positive(item: dict[str, Any], note: str | None) -> list[int]:
        dets = [d for d in str(item.get("detector") or "").split(",") if d]
        ids = []
        for det in dets:
            if det in NON_DETECTOR_SOURCES:
                continue
            ids.append(
                loop.mark(
                    "false_positive",
                    detector=det,
                    run_id=item.get("run_id"),
                    row_index=item.get("row_index"),
                    column=item.get("column"),
                    note=note or f"review item {item['id']}",
                )
            )
        return ids

    def _apply(items: list[dict[str, Any]]) -> tuple[int, int]:
        """Write approved items into their analysis's cleaned file."""
        by_run: dict[int | None, list[int]] = {}
        for it in items:
            by_run.setdefault(it.get("run_id"), []).append(it["id"])
        applied = not_applicable = 0
        for run_id, ids in by_run.items():
            r = store.get_run(run_id) if run_id is not None else None
            analysis_id = ((r or {}).get("metrics") or {}).get("analysis_id")
            if not analysis_id:
                not_applicable += len(ids)
                continue
            try:
                n = workspace.apply_review(analysis_id, ids)
            except NotFound:
                n = 0
            applied += n
            not_applicable += len(ids) - n
        return applied, not_applicable

    @app.post("/api/review/bulk")
    def review_bulk(payload: dict[str, Any] = Body(...)) -> dict[str, Any]:
        """Approve, reject, apply or mark as false positive many items at once.

        Body: ``{"action": ..., "ids": [...]}`` or ``{"action": ..., "all_matching": true,
        "filter": {"status": "pending", "pipeline": ..., "column": ..., "detector": ..., "q": ...}}``.
        ``value`` (approve/apply) overrides the suggested value for every item.
        """
        action = payload.get("action")
        if action not in BULK_ACTIONS:
            raise HTTPException(422, f"action must be one of {sorted(BULK_ACTIONS)}")
        if payload.get("all_matching"):
            f = dict(payload.get("filter") or {})
            status = f.get("status", "pending")
            ids = queue.ids(
                status=None if status in (None, "", "all") else status,
                pipeline=f.get("pipeline") or None,
                column=f.get("column") or None,
                detector=f.get("detector") or None,
                run_id=f.get("run_id"),
                q=f.get("q") or None,
            )
        else:
            try:
                ids = [int(i) for i in payload.get("ids") or []]
            except (TypeError, ValueError) as exc:
                raise HTTPException(422, "ids must be integers") from exc
        if not ids:
            raise HTTPException(422, "no items selected")
        if len(ids) > MAX_BULK:
            raise HTTPException(422, f"at most {MAX_BULK} items per request")
        note = payload.get("note")
        value = payload.get("value")
        counts = {
            "matched": len(ids),
            "updated": 0,
            "skipped": 0,
            "applied": 0,
            "not_applicable": 0,
        }
        items = [i for i in (queue.get(x) for x in ids) if i is not None]
        counts["skipped"] += len(ids) - len(items)
        to_apply = []
        for it in items:
            if action == "approve":
                if it["status"] != "pending":
                    counts["skipped"] += 1
                    continue
                queue.approve(it["id"], value=value, note=note)
                counts["updated"] += 1
            elif action == "reject":
                if it["status"] != "pending":
                    counts["skipped"] += 1
                    continue
                queue.reject(it["id"], note=note)
                counts["updated"] += 1
            elif action == "false_positive":
                if it["status"] != "pending":
                    counts["skipped"] += 1
                    continue
                _false_positive(it, note)
                queue.reject(it["id"], note=note or "false positive")
                counts["updated"] += 1
            else:  # apply
                if it["status"] == "pending":
                    it = queue.approve(it["id"], value=value, note=note)
                    counts["updated"] += 1
                if it["status"] != "approved":
                    counts["skipped"] += 1
                    continue
                to_apply.append(it)
        if to_apply:
            counts["applied"], counts["not_applicable"] = _apply(to_apply)
        return {"action": action, **counts, "review": queue.counts()}

    @app.get("/api/review/{item_id}")
    def review_item(item_id: int) -> dict[str, Any]:
        """One item plus context: the full data row and every finding on it (when known)."""
        item = queue.get(item_id)
        if item is None:
            raise HTTPException(404, f"Review item {item_id} not found")
        out: dict[str, Any] = {"item": item, "row": None, "findings": [], "run": None}
        if item.get("run_id"):
            r = store.get_run(item["run_id"])
            if r:
                out["run"] = {k: r.get(k) for k in ("id", "pipeline", "started_at", "status")}
                out["findings"] = store.anomalies(
                    item["run_id"], limit=50, row_indexes=[item["row_index"]]
                )
                dataset_id = (r.get("metrics") or {}).get("dataset_id")
                if dataset_id:
                    try:
                        df = workspace.load(dataset_id)
                        if item["row_index"] in df.index:
                            out["row"] = jsonable(df.loc[item["row_index"]].to_dict())
                    except (NotFound, KeyError, TypeError):
                        pass
        return out

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

    @app.post("/api/review/{item_id}/false-positive")
    def review_false_positive(
        item_id: int, payload: dict[str, Any] | None = Body(None)
    ) -> dict[str, Any]:
        """Reject the item (keep the original value) and record false-positive feedback."""
        item = queue.get(item_id)
        if item is None:
            raise HTTPException(404, f"Review item {item_id} not found")
        note = (payload or {}).get("note")
        feedback_ids = _false_positive(item, note)
        return {
            "item": queue.reject(item_id, note=note or "false positive"),
            "feedback": feedback_ids,
        }

    # -- feedback & thresholds --------------------------------------------------
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

    @app.put("/api/thresholds/{detector}")
    def set_threshold(detector: str, payload: dict[str, Any] = Body(...)) -> dict[str, Any]:
        try:
            mult = float(payload.get("multiplier"))
        except (TypeError, ValueError) as exc:
            raise HTTPException(422, "multiplier must be a number") from exc
        if not 0.1 <= mult <= 10:
            raise HTTPException(422, "multiplier must be between 0.1 and 10")
        store.set_threshold(detector, round(mult, 4), payload.get("reason") or "set in the UI")
        return {"detector": detector, "multiplier": round(mult, 4)}

    @app.delete("/api/thresholds/{detector}")
    def reset_threshold(detector: str) -> dict[str, Any]:
        return {"detector": detector, "removed": store.delete_threshold(detector)}

    @app.get("/api/detectors")
    def detectors() -> list[dict[str, str]]:
        return detector_catalog()

    # -- datasets -----------------------------------------------------------------
    @app.post("/api/datasets", status_code=201)
    def upload(request: Request, file: UploadFile = File(...)) -> dict[str, Any]:
        """Upload CSV/TSV/JSON/JSONL/Parquet (multipart field ``file``)."""
        length = request.headers.get("content-length")
        if length and length.isdigit() and int(length) > settings.max_upload_bytes + 64 * 1024:
            raise UploadTooLarge(
                f"File is larger than the {settings.max_upload_mb:g} MB upload limit"
            )

        def chunks() -> Iterator[bytes]:
            while True:
                block = file.file.read(CHUNK)
                if not block:
                    return
                yield block

        return workspace.save_upload(file.filename or "", chunks(), settings.max_upload_bytes)

    @app.post("/api/datasets/sample", status_code=201)
    def sample_dataset(body: dict[str, Any] = Body(default_factory=dict)) -> dict[str, Any]:
        """Generate a labelled demo dataset (``{"kind": "orders" | "sensor"}``)."""
        return workspace.create_sample(str(body.get("kind", "orders")))

    @app.get("/api/datasets")
    def datasets() -> list[dict[str, Any]]:
        return workspace.list_datasets()

    @app.get("/api/datasets/{dataset_id}")
    def dataset(dataset_id: str) -> dict[str, Any]:
        return {
            **workspace.get_dataset(dataset_id),
            "analyses": workspace.list_analyses(dataset_id, limit=20),
        }

    @app.delete("/api/datasets/{dataset_id}")
    def delete_dataset(dataset_id: str) -> dict[str, Any]:
        workspace.delete_dataset(dataset_id)
        return {"deleted": dataset_id}

    @app.get("/api/datasets/{dataset_id}/profile")
    def dataset_profile(dataset_id: str) -> dict[str, Any]:
        return workspace.profile(dataset_id)

    @app.get("/api/datasets/{dataset_id}/rows")
    def dataset_rows(
        dataset_id: str,
        offset: int = Query(0, ge=0),
        limit: int = Query(50, ge=1, le=500),
    ) -> dict[str, Any]:
        return workspace.rows(dataset_id, offset, limit)

    # -- analyses ------------------------------------------------------------------
    @app.post("/api/analyses", status_code=202)
    def create_analysis(payload: dict[str, Any] = Body(...), wait: bool = False) -> dict[str, Any]:
        """Start an analysis of an uploaded dataset as a background job.

        Body: ``{"dataset_id": ..., "detectors": ["mad", "iforest"], "group_by": "region",
        "columns": [...], "sensitivity": "low|medium|high", "combine": "any"}``.
        Poll ``/api/jobs/{job.id}``; with ``?wait=true`` the call returns when done.
        """
        dataset_id = payload.get("dataset_id")
        if not dataset_id:
            raise HTTPException(422, "dataset_id is required")
        meta = workspace.create_analysis(str(dataset_id), payload)

        def work(ctx) -> dict[str, Any]:
            return workspace.run_analysis(meta["id"], ctx.progress)

        params = {"analysis_id": meta["id"], "dataset_id": dataset_id}
        label = f"Analyze {meta['dataset']}"
        job = (
            jobs.run_inline("analysis", work, label, params)
            if wait
            else jobs.submit("analysis", work, label, params)
        )
        return {"analysis": workspace.get_analysis(meta["id"]), "job": job}

    @app.get("/api/analyses")
    def analyses(
        dataset_id: str | None = None, limit: int = Query(50, ge=1, le=500)
    ) -> list[dict[str, Any]]:
        return workspace.list_analyses(dataset_id, limit)

    @app.get("/api/analyses/{analysis_id}")
    def analysis(analysis_id: str) -> dict[str, Any]:
        meta = workspace.get_analysis(analysis_id)
        meta["artifacts"] = workspace.available_artifacts(analysis_id)
        if meta.get("run_id"):
            meta["breakdown"] = store.anomaly_breakdown(meta["run_id"])
        return meta

    @app.get("/api/analyses/{analysis_id}/rows")
    def analysis_rows(
        analysis_id: str,
        offset: int = Query(0, ge=0),
        limit: int = Query(50, ge=1, le=500),
        only_anomalous: bool = True,
        column: str | None = None,
        detector: str | None = None,
        severity: str | None = None,
        sort: str = Query("score", pattern="^(score|row)$"),
    ) -> dict[str, Any]:
        """Data rows with findings per cell (``only_anomalous=false`` for every row)."""
        return workspace.analysis_rows(
            analysis_id, offset, limit, only_anomalous, column, detector, severity, sort
        )

    @app.post("/api/analyses/{analysis_id}/remediate")
    def remediate(analysis_id: str, payload: dict[str, Any] | None = Body(None)) -> dict[str, Any]:
        """Preview a remediation policy and write the cleaned file and reports.

        Body: ``{"default": {"missing": "auto", "outlier": "cap", "invalid": "coerce"},
        "columns": {"unit_price": {"outlier": "flag"}}, "dedupe": true}``.
        """
        return workspace.remediate(analysis_id, payload)

    @app.get("/api/analyses/{analysis_id}/changes")
    def changes(
        analysis_id: str,
        offset: int = Query(0, ge=0),
        limit: int = Query(50, ge=1, le=1000),
        column: str | None = None,
        strategy: str | None = None,
    ) -> dict[str, Any]:
        return workspace.changes(analysis_id, offset, limit, column, strategy)

    @app.get("/api/analyses/{analysis_id}/flagged")
    def flagged(analysis_id: str) -> list[dict[str, Any]]:
        return workspace.flagged(analysis_id)

    @app.post("/api/analyses/{analysis_id}/review")
    def queue_flagged(analysis_id: str) -> dict[str, Any]:
        """Send the flagged values of the latest remediation to the review queue."""
        return workspace.queue_flagged(analysis_id)

    @app.get("/api/analyses/{analysis_id}/download/{name}")
    def download(analysis_id: str, name: str) -> FileResponse:
        """``cleaned.csv``, ``remediation.md``, ``remediation.json``, ``anomalies.json``
        or ``schema.yaml``."""
        path, media, filename = workspace.artifact(analysis_id, name)
        return FileResponse(path, media_type=media, filename=filename)

    # -- jobs -----------------------------------------------------------------------
    @app.get("/api/jobs")
    def list_jobs(
        limit: int = Query(50, ge=1, le=500), kind: str | None = None, status: str | None = None
    ) -> list[dict[str, Any]]:
        return jobs.list(limit, kind, status)

    @app.get("/api/jobs/{job_id}")
    def get_job(job_id: str) -> dict[str, Any]:
        job = jobs.get(job_id)
        if job is None:
            raise HTTPException(404, f"Job {job_id} not found")
        return job

    # -- pipelines ------------------------------------------------------------------
    @app.get("/api/pipelines")
    def pipelines() -> dict[str, Any]:
        return {
            "dirs": [{"path": str(d), "exists": d.is_dir()} for d in settings.pipeline_dirs],
            "write_dir": str(catalog.write_dir),
            "pipelines": catalog.list(),
        }

    @app.get("/api/pipelines/templates")
    def pipeline_templates() -> list[dict[str, Any]]:
        return templates()

    @app.post("/api/pipelines/validate")
    def validate_pipeline(payload: dict[str, Any] = Body(...)) -> dict[str, Any]:
        text = payload.get("yaml")
        if not isinstance(text, str):
            raise HTTPException(422, "yaml (string) is required")
        return catalog.validate_text(text, base_dir=catalog.write_dir.resolve())

    def _resolve_source(source: str | None) -> str | None:
        if source and source.startswith("dataset:"):
            return str(workspace.dataset_path(source.split(":", 1)[1]).resolve())
        return source

    @app.post("/api/pipelines", status_code=201)
    def create_pipeline(payload: dict[str, Any] = Body(...)) -> dict[str, Any]:
        """Create ``<name>.yaml`` in the first pipeline folder from a template.

        Body: ``{"name": ..., "template": "csv_quality", "source": "data.csv" | "dataset:<id>",
        "group_by": ..., "value_column": ..., "table": ..., "cursor": ...}``.
        """
        try:
            path = catalog.create(
                str(payload.get("name") or ""),
                template=str(payload.get("template") or "csv_quality"),
                source=_resolve_source(payload.get("source")),
                overwrite=bool(payload.get("overwrite")),
                yaml_text=payload.get("yaml"),
                group_by=payload.get("group_by"),
                value_column=payload.get("value_column"),
                table=payload.get("table"),
                cursor=payload.get("cursor"),
            )
        except FileExistsError as exc:
            raise HTTPException(409, str(exc)) from exc
        except (ValueError, KeyError) as exc:
            raise HTTPException(422, str(exc.args[0] if exc.args else exc)) from exc
        return catalog.describe(path, with_yaml=True)

    def _pipeline_path(pid: str) -> Path:
        try:
            return catalog.find(pid)
        except KeyError as exc:
            raise HTTPException(404, str(exc.args[0])) from exc

    @app.get("/api/pipelines/{pid}")
    def pipeline(pid: str) -> dict[str, Any]:
        path = _pipeline_path(pid)
        info = catalog.describe(path, with_yaml=True)
        info["recent_runs"] = (
            store.runs(limit=10, pipeline=info["name"]) if info.get("name") else []
        )
        info["jobs"] = [
            j for j in jobs.list(limit=50, kind="pipeline") if j["params"].get("id") == pid
        ][:5]
        return info

    @app.put("/api/pipelines/{pid}")
    def save_pipeline(pid: str, payload: dict[str, Any] = Body(...)) -> dict[str, Any]:
        text = payload.get("yaml")
        if not isinstance(text, str):
            raise HTTPException(422, "yaml (string) is required")
        _pipeline_path(pid)
        try:
            path = catalog.update(pid, text)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        return catalog.describe(path, with_yaml=True)

    @app.post("/api/pipelines/{pid}/validate")
    def validate_existing(pid: str) -> dict[str, Any]:
        path = _pipeline_path(pid)
        return catalog.validate_text(path.read_text(encoding="utf-8"), path.resolve().parent)

    @app.post("/api/pipelines/{pid}/run", status_code=202)
    def run_pipeline_now(pid: str, wait: bool = False) -> dict[str, Any]:
        """Run a pipeline once as a background job (``?wait=true`` to block)."""
        from anomalyguard.pipeline import ConfigError, PipelineExecutor

        path = _pipeline_path(pid)
        try:
            cfg = catalog.load_for_server(path, db_path)
        except ConfigError as exc:
            raise HTTPException(422, str(exc)) from exc

        def work(ctx) -> dict[str, Any]:
            ctx.progress(0.1, "Running")
            result = PipelineExecutor(cfg, console=False).run()
            if result.status == "failed":
                raise RuntimeError(f"run #{result.run_id} failed: {result.error}")
            return result.to_dict()

        params = {"id": pid, "pipeline": cfg.name, "file": str(path)}
        label = f"Run {cfg.name}"
        if wait:
            return {"job": jobs.run_inline("pipeline", work, label, params)}
        return {"job": jobs.submit("pipeline", work, label, params)}

    # -- settings ---------------------------------------------------------------------
    @app.get("/api/settings")
    def server_settings() -> dict[str, Any]:
        info = doctor.collect(db_path, settings.pipeline_dirs)
        return {
            "version": __version__,
            "server": settings.describe(),
            "state": info["state"],
            "extras": info["extras"],
            "env": info["env"],
            "notifiers": info["notifiers"],
            "thresholds": store.threshold_details(),
            "precision": loop.precision(),
            "cwd": os.getcwd(),
        }

    return app
