"""Uploaded datasets and interactive analyses, stored under the state directory.

Layout (``<state>`` is the folder that holds the metrics database)::

    <state>/uploads/<dataset_id>/<file>          the uploaded file
    <state>/uploads/<dataset_id>/meta.json       name, size, rows, columns
    <state>/uploads/<dataset_id>/profile.json    cached profile
    <state>/analyses/<analysis_id>/meta.json     options, status, summary, run id
    <state>/analyses/<analysis_id>/findings.json every finding (for remediation)
    <state>/analyses/<analysis_id>/...           report, schema, cleaned data, diff

Every analysis is also recorded as a run (pipeline ``analysis:<dataset>``) in
the metrics store, with its findings, so it shows up on the Runs page and the
false-positive feedback loop works for it.
"""

from __future__ import annotations

import json
import math
import re
import shutil
import threading
import time
import uuid
from collections import OrderedDict
from collections.abc import Iterable
from datetime import date, datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from anomalyguard.detect.base import DetectionResult, Finding, numeric_columns
from anomalyguard.detect.registry import CATEGORIES, canonical_name
from anomalyguard.detect.report import AnomalyReport
from anomalyguard.ingest.factory import read_any
from anomalyguard.ingest.inference import infer_schema
from anomalyguard.monitor.store import ANALYSIS_PREFIX, MetricsStore, now_iso
from anomalyguard.remediate.pipeline import RemediationPipeline, RemediationPolicy
from anomalyguard.remediate.review import ReviewQueue
from anomalyguard.schema.coercion import _clean_numeric_strings
from anomalyguard.schema.registry import DataType, Schema

ID_RE = re.compile(r"^[a-f0-9]{8,32}$")
UPLOAD_SUFFIXES = (
    ".csv",
    ".tsv",
    ".json",
    ".jsonl",
    ".ndjson",
    ".parquet",
    ".pq",
    ".csv.gz",
    ".tsv.gz",
    ".jsonl.gz",
    ".json.gz",
)
SENSITIVITY = {"low": 1.5, "medium": 1.0, "high": 0.7}
ARTIFACTS = {
    "cleaned.csv": ("text/csv", "cleaned.csv"),
    "remediation.md": ("text/markdown", "remediation.md"),
    "remediation.json": ("application/json", "remediation.json"),
    "anomalies.json": ("application/json", "report.json"),
    "schema.yaml": ("application/yaml", "schema.yaml"),
}
MAX_STORED_FINDINGS = 50_000


class WorkspaceError(ValueError):
    """Bad input for a dataset or analysis operation (maps to HTTP 4xx)."""


class NotFound(KeyError):
    pass


class UploadTooLarge(WorkspaceError):
    pass


# ----------------------------------------------------------------------
# helpers
# ----------------------------------------------------------------------
def safe_filename(name: str) -> str:
    """Basename only, conservative characters, a supported extension."""
    base = re.split(r"[\\/]", str(name or ""))[-1].strip()
    base = re.sub(r"[^A-Za-z0-9._-]+", "_", base).lstrip("._")[:120]
    if not base.lower().endswith(UPLOAD_SUFFIXES):
        raise WorkspaceError(
            "Unsupported file type. Upload CSV, TSV, JSON, JSONL or Parquet "
            f"({', '.join(UPLOAD_SUFFIXES)})."
        )
    return base


def check_id(value: str) -> str:
    if not ID_RE.match(str(value or "")):
        raise NotFound(f"Unknown id '{value}'")
    return value


def jsonable(v: Any) -> Any:
    """Convert numpy / pandas values (and NaN) to plain JSON types."""
    if isinstance(v, dict):
        return {str(k): jsonable(x) for k, x in v.items()}
    if isinstance(v, (list, tuple)):
        return [jsonable(x) for x in v]
    if isinstance(v, np.generic):
        v = v.item()
    if isinstance(v, float):
        return None if math.isnan(v) or math.isinf(v) else v
    if isinstance(v, (pd.Timestamp, datetime, date)):
        return v.isoformat()
    if v is pd.NaT or (v is not None and not isinstance(v, (str, bytes)) and _isna(v)):
        return None
    if isinstance(v, (str, int, bool)) or v is None:
        return v
    return str(v)


def _isna(v: Any) -> bool:
    try:
        return bool(pd.isna(v))
    except (TypeError, ValueError):
        return False


def _write_json(path: Path, data: Any) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(jsonable(data), indent=1), encoding="utf-8")
    tmp.replace(path)


def _read_json(path: Path, default: Any = None) -> Any:
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def histogram(series: pd.Series, bins: int = 24) -> dict[str, Any] | None:
    """Histogram over the 1st-99th percentile range; values outside are counted
    as ``below``/``above`` so one extreme value does not flatten the chart."""
    nums = pd.to_numeric(_clean_numeric_strings(series), errors="coerce").dropna().astype(float)
    if nums.empty:
        return None
    lo, hi = (float(x) for x in np.percentile(nums, [1, 99]))
    if lo == hi:
        lo, hi = float(nums.min()), float(nums.max())
    if lo == hi:
        return {"edges": [lo, hi], "counts": [len(nums)], "below": 0, "above": 0}
    inside = nums[(nums >= lo) & (nums <= hi)]
    counts, edges = np.histogram(inside, bins=bins, range=(lo, hi))
    return {
        "edges": [float(e) for e in edges],
        "counts": [int(c) for c in counts],
        "below": int((nums < lo).sum()),
        "above": int((nums > hi).sum()),
    }


def rebuild_report(n_rows: int, findings: list[dict[str, Any]], index: list[Any]) -> AnomalyReport:
    """An :class:`AnomalyReport` equivalent to the stored findings (enough for remediation)."""
    by_det: dict[str, list[Finding]] = {}
    for f in findings:
        by_det.setdefault(f["detector"], []).append(
            Finding(
                row=int(f["row"]),
                detector=f["detector"],
                score=float(f.get("score") or 0.0),
                column=f.get("column"),
                value=f.get("value"),
                reason=f.get("reason") or "",
                index=f.get("index"),
            )
        )
    results = []
    for det, fs in by_det.items():
        labels = np.zeros(n_rows, dtype=bool)
        scores = np.zeros(n_rows)
        for f in fs:
            if 0 <= f.row < n_rows:
                labels[f.row] = True
                scores[f.row] = max(scores[f.row], f.score)
        cols = sorted({f.column for f in fs if f.column})
        results.append(DetectionResult(det, scores, scores, labels, 1.0, cols, fs))
    # grouped detectors are named "grouped(mad by region,channel)": remediation
    # needs the group columns to cap within each group
    groups = {}
    for det in by_det:
        m = re.fullmatch(r"grouped\(.+ by (.+)\)", det)
        if m:
            groups[det] = [c.strip() for c in m.group(1).split(",") if c.strip()]
    return AnomalyReport(
        n_rows=n_rows, results=results, index=list(index), combine="any", groups=groups
    )


# ----------------------------------------------------------------------
class Workspace:
    def __init__(self, root: str | Path, store: MetricsStore, queue: ReviewQueue):
        self.root = Path(root)
        self.uploads = self.root / "uploads"
        self.analyses = self.root / "analyses"
        self.uploads.mkdir(parents=True, exist_ok=True)
        self.analyses.mkdir(parents=True, exist_ok=True)
        self.store = store
        self.queue = queue
        self._cache: OrderedDict[str, tuple[float, pd.DataFrame]] = OrderedDict()
        self._lock = threading.Lock()

    # -- datasets -------------------------------------------------------
    def _dataset_dir(self, dataset_id: str) -> Path:
        d = self.uploads / check_id(dataset_id)
        if not (d / "meta.json").exists():
            raise NotFound(f"Dataset {dataset_id} not found")
        return d

    def save_upload(
        self, filename: str, chunks: Iterable[bytes], max_bytes: int | None = None
    ) -> dict[str, Any]:
        """Stream an upload to disk, enforce the size limit and check it parses."""
        name = safe_filename(filename)
        dataset_id = uuid.uuid4().hex[:12]
        folder = self.uploads / dataset_id
        folder.mkdir(parents=True)
        path = folder / name
        size = 0
        try:
            with path.open("wb") as fh:
                for chunk in chunks:
                    size += len(chunk)
                    if max_bytes is not None and size > max_bytes:
                        raise UploadTooLarge(
                            f"File is larger than the {max_bytes / 1024 / 1024:.0f} MB upload limit"
                        )
                    fh.write(chunk)
            if size == 0:
                raise WorkspaceError("The uploaded file is empty")
            try:
                df = read_any(path)
            except Exception as exc:
                raise WorkspaceError(f"Could not read {name}: {exc}") from exc
            if df.empty or len(df.columns) == 0:
                raise WorkspaceError(f"{name} has no rows")
        except BaseException:
            shutil.rmtree(folder, ignore_errors=True)
            raise
        meta = {
            "id": dataset_id,
            "name": Path(name).name,
            "file": name,
            "size": size,
            "rows": len(df),
            "columns": [str(c) for c in df.columns],
            "created_at": now_iso(),
        }
        _write_json(folder / "meta.json", meta)
        return meta

    SAMPLES = {
        "orders": "1,000 e-commerce orders with price, quantity, delivery and data-entry anomalies",
        "sensor": "1,440 hourly sensor readings with spikes, a level shift and seasonal drift",
    }

    def create_sample(self, kind: str) -> dict[str, Any]:
        """Generate a labelled demo dataset and register it like an upload.

        Lets people try the product without having a file to hand (a pip install
        does not ship the repository's ``examples/`` folder).
        """
        from anomalyguard.demo.generator import generate_orders, generate_sensor

        if kind not in self.SAMPLES:
            raise WorkspaceError(f"Unknown sample {kind!r}; choose one of {sorted(self.SAMPLES)}")
        df, _labels = generate_orders() if kind == "orders" else generate_sensor()
        data = df.to_csv(index=False).encode("utf-8")
        return self.save_upload(f"sample_{kind}.csv", [data])

    def list_datasets(self) -> list[dict[str, Any]]:
        out = []
        for d in self.uploads.iterdir():
            meta = _read_json(d / "meta.json") if d.is_dir() else None
            if meta:
                out.append(meta)
        return sorted(out, key=lambda m: m.get("created_at", ""), reverse=True)

    def get_dataset(self, dataset_id: str) -> dict[str, Any]:
        return _read_json(self._dataset_dir(dataset_id) / "meta.json")

    def dataset_path(self, dataset_id: str) -> Path:
        d = self._dataset_dir(dataset_id)
        return d / self.get_dataset(dataset_id)["file"]

    def delete_dataset(self, dataset_id: str) -> None:
        d = self._dataset_dir(dataset_id)
        with self._lock:
            self._cache.pop(dataset_id, None)
        shutil.rmtree(d)

    def load(self, dataset_id: str) -> pd.DataFrame:
        path = self.dataset_path(dataset_id)
        mtime = path.stat().st_mtime
        with self._lock:
            hit = self._cache.get(dataset_id)
            if hit and hit[0] == mtime:
                self._cache.move_to_end(dataset_id)
                return hit[1]
        df = read_any(path)
        with self._lock:
            self._cache[dataset_id] = (mtime, df)
            while len(self._cache) > 4:
                self._cache.popitem(last=False)
        return df

    def profile(self, dataset_id: str) -> dict[str, Any]:
        import anomalyguard as ag

        folder = self._dataset_dir(dataset_id)
        cached = _read_json(folder / "profile.json")
        if cached:
            return cached
        df = self.load(dataset_id)
        meta = self.get_dataset(dataset_id)
        prof = ag.profile(df, name=Path(meta["name"]).stem)
        numeric = set(numeric_columns(df))
        columns = []
        for c in prof.columns:
            d = c.to_dict()
            fld = prof.schema.fields.get(c.name)
            d["numeric"] = c.name in numeric
            d["histogram"] = histogram(df[c.name]) if c.name in numeric else None
            if not d["numeric"] and c.dtype in ("categorical", "string", "boolean"):
                vc = df[c.name].dropna().astype(str).value_counts()
                d["top_values"] = [[str(k), int(v)] for k, v in vc.head(8).items()]
            d["constraints"] = fld.to_dict() if fld else {}
            columns.append(d)
        group_candidates = [
            c.name
            for c in prof.columns
            if c.dtype in ("categorical", "boolean", "string") and 2 <= c.unique <= 50
        ]
        out = {
            "dataset": meta,
            "quality": prof.quality.to_dict(),
            "columns": columns,
            "schema": prof.schema.to_dict(),
            "validation": {
                "passed": prof.validation.passed,
                "invalid_rows": prof.validation.n_invalid_rows,
                "by_rule": prof.validation.counts_by_rule(),
            },
            "suggestions": {
                "numeric_columns": [c for c in df.columns if c in numeric],
                "group_by": group_candidates,
                "time_columns": [
                    c.name for c in prof.columns if c.dtype == DataType.DATETIME.value
                ],
            },
        }
        _write_json(folder / "profile.json", out)
        return jsonable(out)

    def rows(self, dataset_id: str, offset: int = 0, limit: int = 50) -> dict[str, Any]:
        df = self.load(dataset_id)
        page = df.iloc[offset : offset + limit]
        return {
            "columns": [str(c) for c in df.columns],
            "total": len(df),
            "rows": [
                {"index": jsonable(i), "values": jsonable(r)}
                for i, r in zip(page.index, page.to_dict(orient="records"), strict=False)
            ],
        }

    # -- analyses -------------------------------------------------------
    def _analysis_dir(self, analysis_id: str) -> Path:
        d = self.analyses / check_id(analysis_id)
        if not (d / "meta.json").exists():
            raise NotFound(f"Analysis {analysis_id} not found")
        return d

    def normalise_options(self, dataset_id: str, options: dict[str, Any]) -> dict[str, Any]:
        """Validate analysis options against the dataset's columns."""
        meta = self.get_dataset(dataset_id)
        cols = set(meta["columns"])
        detectors = options.get("detectors") or ["mad", "iforest"]
        if isinstance(detectors, str):
            detectors = [d.strip() for d in detectors.split(",") if d.strip()]
        names = []
        for d in detectors:
            try:
                names.append(canonical_name(str(d)))
            except KeyError as exc:
                raise WorkspaceError(str(exc.args[0])) from exc
        names = list(dict.fromkeys(names))
        group_by = options.get("group_by") or None
        if group_by and group_by not in cols:
            raise WorkspaceError(f"group_by column '{group_by}' is not in the dataset")
        time_column = options.get("time_column") or None
        if time_column and time_column not in cols:
            raise WorkspaceError(f"time_column '{time_column}' is not in the dataset")
        columns = options.get("columns") or None
        if columns:
            missing = [c for c in columns if c not in cols]
            if missing:
                raise WorkspaceError(f"Unknown columns: {missing}")
        sens = options.get("sensitivity", "medium")
        if isinstance(sens, str):
            if sens not in SENSITIVITY:
                raise WorkspaceError("sensitivity must be low, medium, high or a number")
            scale = SENSITIVITY[sens]
        else:
            scale = float(sens)
            if not 0.1 <= scale <= 10:
                raise WorkspaceError("numeric sensitivity must be between 0.1 and 10")
        combine = options.get("combine", "any")
        if combine not in ("any", "vote", "all"):
            raise WorkspaceError("combine must be any, vote or all")
        return {
            "detectors": names,
            "group_by": group_by,
            "time_column": time_column,
            "columns": columns,
            "sensitivity": sens,
            "threshold_scale": scale,
            "combine": combine,
            "min_votes": int(options.get("min_votes") or 2),
        }

    def create_analysis(self, dataset_id: str, options: dict[str, Any]) -> dict[str, Any]:
        opts = self.normalise_options(dataset_id, options)
        dataset = self.get_dataset(dataset_id)
        analysis_id = uuid.uuid4().hex[:12]
        folder = self.analyses / analysis_id
        folder.mkdir(parents=True)
        meta = {
            "id": analysis_id,
            "dataset_id": dataset_id,
            "dataset": dataset["name"],
            "options": opts,
            "status": "queued",
            "created_at": now_iso(),
            "run_id": None,
        }
        _write_json(folder / "meta.json", meta)
        return meta

    def _save_meta(self, analysis_id: str, **updates: Any) -> dict[str, Any]:
        path = self._analysis_dir(analysis_id) / "meta.json"
        with self._lock:
            meta = _read_json(path) or {}
            meta.update(updates)
            _write_json(path, meta)
        return meta

    def get_analysis(self, analysis_id: str) -> dict[str, Any]:
        return _read_json(self._analysis_dir(analysis_id) / "meta.json")

    def list_analyses(self, dataset_id: str | None = None, limit: int = 50) -> list[dict[str, Any]]:
        out = []
        for d in self.analyses.iterdir():
            meta = _read_json(d / "meta.json") if d.is_dir() else None
            if meta and (dataset_id is None or meta.get("dataset_id") == dataset_id):
                out.append(meta)
        return sorted(out, key=lambda m: m.get("created_at", ""), reverse=True)[:limit]

    def run_analysis(self, analysis_id: str, progress: Any = None) -> dict[str, Any]:
        """Detect anomalies, record a run and persist findings. Returns the summary."""
        import anomalyguard as ag

        def step(frac: float, msg: str) -> None:
            if progress is not None:
                progress(frac, msg)

        folder = self._analysis_dir(analysis_id)
        meta = self.get_analysis(analysis_id)
        opts = meta["options"]
        pipeline = f"{ANALYSIS_PREFIX}{meta['dataset']}"
        run_id = self.store.start_run(pipeline)
        self._save_meta(analysis_id, status="running", run_id=run_id, started_at=now_iso())
        t0 = time.perf_counter()
        try:
            step(0.05, "Loading data")
            df = self.load(meta["dataset_id"])
            step(0.15, "Profiling")
            prof = self.profile(meta["dataset_id"])
            schema = infer_schema(df, name=Path(meta["dataset"]).stem)
            schema.save(folder / "schema.yaml")
            step(0.3, "Running detectors")
            report = ag.detect(
                df,
                list(opts["detectors"]),
                schema=schema,
                columns=opts.get("columns"),
                group_by=opts.get("group_by"),
                time_column=opts.get("time_column"),
                combine=opts.get("combine", "any"),
                min_votes=int(opts.get("min_votes", 2)),
                threshold_multipliers=self.store.thresholds(),
                threshold_scale=float(opts.get("threshold_scale", 1.0)),
            )
            step(0.8, "Saving findings")
            findings = sorted((f.to_dict() for f in report.findings), key=lambda f: -f["score"])
            _write_json(folder / "findings.json", findings)
            report.to_json(folder / "report.json")
            _write_json(folder / "index.json", list(df.index))
            self.store.add_anomalies(run_id, findings, limit=MAX_STORED_FINDINGS)
            q = prof["quality"]
            summary = {
                "rows": len(df),
                "columns": len(df.columns),
                "n_anomalies": report.n_anomalies,
                "anomaly_rate": round(report.anomaly_rate, 6),
                "n_findings": len(findings),
                "anomalies_by_detector": report.counts_by_detector(),
                "anomalies_by_column": report.counts_by_column(),
                "thresholds": {r.detector: r.threshold for r in report.results},
            }
            metrics = {
                **summary,
                "quality_score": q.get("score"),
                "completeness": q.get("completeness"),
                "validity": q.get("validity"),
                "uniqueness": q.get("uniqueness"),
                "freshness": q.get("freshness"),
                "invalid_rows": q.get("invalid_rows"),
                "duplicate_rows": q.get("duplicate_rows"),
                "null_counts": q.get("null_counts") or {},
                "violations": prof.get("validation", {}).get("by_rule") or {},
                "alerts_sent": 0,
                "cells_changed": 0,
                "rows_dropped": 0,
                "flagged_for_review": 0,
                "analysis_id": analysis_id,
                "dataset_id": meta["dataset_id"],
                "dataset": meta["dataset"],
                "options": opts,
                "duration_ms": round((time.perf_counter() - t0) * 1000, 1),
            }
            self.store.finish_run(
                run_id, jsonable(metrics), "success", None, report.counts_by_detector()
            )
        except Exception as exc:
            err = f"{type(exc).__name__}: {exc}"
            self.store.finish_run(
                run_id, {"duration_ms": round((time.perf_counter() - t0) * 1000, 1)}, "failed", err
            )
            self._save_meta(analysis_id, status="failed", error=err, finished_at=now_iso())
            raise
        step(1.0, "Done")
        self._save_meta(
            analysis_id, status="success", summary=jsonable(summary), finished_at=now_iso()
        )
        return jsonable({"analysis_id": analysis_id, "run_id": run_id, **summary})

    def _ready(self, analysis_id: str) -> dict[str, Any]:
        meta = self.get_analysis(analysis_id)
        if meta.get("status") != "success":
            raise WorkspaceError(f"Analysis {analysis_id} is {meta.get('status')}, not finished")
        return meta

    def analysis_rows(
        self,
        analysis_id: str,
        offset: int = 0,
        limit: int = 50,
        only_anomalous: bool = True,
        column: str | None = None,
        detector: str | None = None,
        severity: str | None = None,
        sort: str = "score",
    ) -> dict[str, Any]:
        """A page of data rows with their findings attached per cell."""
        meta = self._ready(analysis_id)
        df = self.load(meta["dataset_id"])
        run_id = meta["run_id"]
        filtered = only_anomalous or column or detector or severity
        if filtered:
            labels, total = self.store.anomalous_rows(
                run_id, column, detector, severity, sort=sort, offset=offset, limit=limit
            )
            positions = [p for p in df.index.get_indexer(labels).tolist() if p >= 0]
        else:
            total = len(df)
            positions = list(range(offset, min(offset + limit, total)))
        page = df.iloc[positions]
        labels = [jsonable(i) for i in page.index]
        findings = self.store.anomalies(run_id, limit=10_000, row_indexes=labels) if labels else []
        by_row: dict[str, list[dict[str, Any]]] = {}
        for f in findings:
            by_row.setdefault(json.dumps(f["row_index"]), []).append(f)
        rows = []
        for label, values in zip(labels, page.to_dict(orient="records"), strict=False):
            fs = by_row.get(json.dumps(label), [])
            cells: dict[str, list[dict[str, Any]]] = {}
            row_level = []
            for f in fs:
                item = {k: f[k] for k in ("id", "detector", "score", "reason", "severity")}
                if f["column"] in values:
                    cells.setdefault(f["column"], []).append(item)
                else:
                    row_level.append(item)
            rows.append(
                {
                    "index": label,
                    "values": jsonable(values),
                    "cells": cells,
                    "row_findings": row_level,
                    "score": max((f["score"] or 0 for f in fs), default=0),
                }
            )
        return {
            "columns": [str(c) for c in df.columns],
            "total": int(total),
            "offset": offset,
            "limit": limit,
            "rows": rows,
        }

    # -- remediation ----------------------------------------------------
    def remediate(self, analysis_id: str, policy: dict[str, Any] | None = None) -> dict[str, Any]:
        """Apply a remediation policy to the analysed data and write the artifacts."""
        meta = self._ready(analysis_id)
        folder = self._analysis_dir(analysis_id)
        policy = dict(policy or {"default": {"missing": "auto", "outlier": "cap"}})
        try:
            pol = RemediationPolicy.from_dict(policy)
        except (ValueError, TypeError) as exc:
            raise WorkspaceError(f"Invalid remediation policy: {exc}") from exc
        df = self.load(meta["dataset_id"])
        findings = _read_json(folder / "findings.json", [])
        report = rebuild_report(len(df), findings, list(df.index))
        schema_path = folder / "schema.yaml"
        schema = Schema.load(schema_path) if schema_path.exists() else infer_schema(df)
        result = RemediationPipeline(pol, schema=schema).run(df, report)
        rep = result.report()
        result.data.to_csv(folder / "cleaned.csv", index=False)
        _write_json(folder / "cleaned_index.json", list(result.data.index))
        (folder / "remediation.md").write_text(rep.to_markdown(max_rows=500), encoding="utf-8")
        rep.to_json(folder / "remediation.json")
        changes = [c.to_dict() for c in result.changes]
        _write_json(folder / "changes.json", changes)
        _write_json(folder / "flagged.json", [f.to_dict() for f in result.flagged])
        summary = rep.summary()
        out = {
            "summary": summary,
            "column_stats": rep.column_stats(),
            "n_changes": len(changes),
            "n_flagged": len(result.flagged),
            "dropped": [
                {"index": jsonable(result.original.index[k]), "reason": v}
                for k, v in sorted(result.dropped.items())
            ][:200],
            "policy": policy,
            "created_at": now_iso(),
        }
        self._save_meta(analysis_id, remediation=jsonable(out))
        if meta.get("run_id"):
            self.store.update_run(
                meta["run_id"],
                {
                    "cells_changed": result.n_changed_cells,
                    "rows_dropped": len(result.dropped),
                    "flagged_for_review": len({f.row for f in result.flagged}),
                    "remediation": jsonable(summary),
                },
            )
        return jsonable(out)

    def changes(
        self,
        analysis_id: str,
        offset: int = 0,
        limit: int = 50,
        column: str | None = None,
        strategy: str | None = None,
    ) -> dict[str, Any]:
        folder = self._analysis_dir(analysis_id)
        if not (folder / "changes.json").exists():
            raise WorkspaceError("Run a remediation preview first")
        items = _read_json(folder / "changes.json", [])
        if column:
            items = [c for c in items if c.get("column") == column]
        if strategy:
            items = [c for c in items if c.get("strategy") == strategy]
        return {"total": len(items), "offset": offset, "items": items[offset : offset + limit]}

    def flagged(self, analysis_id: str) -> list[dict[str, Any]]:
        return _read_json(self._analysis_dir(analysis_id) / "flagged.json", [])

    def queue_flagged(self, analysis_id: str) -> dict[str, Any]:
        """Send the latest remediation's flagged values to the review queue."""
        meta = self._ready(analysis_id)
        items = self.flagged(analysis_id)
        if not items:
            return {"queued": 0, "ids": []}
        pipeline = f"{ANALYSIS_PREFIX}{meta['dataset']}"
        ids = self.queue.add_flagged(items, pipeline=pipeline, run_id=meta.get("run_id"))
        self._save_meta(analysis_id, queued_for_review=len(set(ids)))
        return {"queued": len(set(ids)), "ids": sorted(set(ids))}

    def apply_review(self, analysis_id: str, item_ids: list[int]) -> int:
        """Write approved review values into this analysis's cleaned file."""
        folder = self._analysis_dir(analysis_id)
        path = folder / "cleaned.csv"
        if not path.exists():
            return 0
        df = read_any(path, delimiter=",", encoding="utf-8")
        index = _read_json(folder / "cleaned_index.json")
        if index and len(index) == len(df):
            df.index = index
        out, n = self.queue.apply(df, item_ids=item_ids, mark=True)
        if n:
            out.to_csv(path, index=False)
        return n

    def artifact(self, analysis_id: str, name: str) -> tuple[Path, str, str]:
        """Path, media type and download name of a whitelisted artifact."""
        if name not in ARTIFACTS:
            raise NotFound(f"Unknown artifact '{name}'")
        media, filename = ARTIFACTS[name]
        meta = self.get_analysis(analysis_id)
        path = self._analysis_dir(analysis_id) / filename
        if not path.exists():
            raise NotFound(f"{name} is not available yet for analysis {analysis_id}")
        stem = re.sub(r"[^A-Za-z0-9_-]+", "_", Path(meta["dataset"]).stem.split(".")[0])
        return path, media, f"{stem}_{name}"

    def available_artifacts(self, analysis_id: str) -> list[str]:
        folder = self._analysis_dir(analysis_id)
        return [n for n, (_, f) in ARTIFACTS.items() if (folder / f).exists()]


def detector_catalog() -> list[dict[str, str]]:
    from anomalyguard.detect import describe_detectors

    names = {n for names in CATEGORIES.values() for n in names}
    return [d for d in describe_detectors() if d["name"] in names]
