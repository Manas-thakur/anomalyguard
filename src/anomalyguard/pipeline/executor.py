"""Run a configured pipeline end to end."""

from __future__ import annotations

import logging
import time
import traceback
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from anomalyguard.alert.base import AlertMessage, Severity
from anomalyguard.alert.manager import AlertManager, DispatchRecord, RateLimiter
from anomalyguard.alert.notifiers import ConsoleNotifier, create_notifier
from anomalyguard.alert.rules import DEFAULT_RULES, AlertRule
from anomalyguard.detect.report import AnomalyReport
from anomalyguard.detect.runner import run_detectors
from anomalyguard.ingest.factory import create_source
from anomalyguard.ingest.incremental import IncrementalReader
from anomalyguard.ingest.inference import infer_schema
from anomalyguard.monitor.feedback import FeedbackLoop
from anomalyguard.monitor.store import MetricsStore
from anomalyguard.pipeline.config import PipelineConfig
from anomalyguard.pipeline.sinks import write_frame
from anomalyguard.pipeline.state import PipelineState
from anomalyguard.remediate.llm import LLMSuggester
from anomalyguard.remediate.pipeline import RemediationPipeline, RemediationResult
from anomalyguard.remediate.review import ReviewQueue
from anomalyguard.schema.quality import QualityMetrics, compute_quality
from anomalyguard.schema.registry import Schema
from anomalyguard.schema.validator import SchemaValidator, ValidationReport

log = logging.getLogger("anomalyguard.pipeline")

#: earlier rows kept for incremental runs (``detection.reference_rows``)
DEFAULT_REFERENCE_ROWS = 5000
#: batches smaller than this are unreliable to fit detectors on by themselves
SMALL_BATCH = 30


@dataclass
class PipelineResult:
    name: str
    status: str  # success | empty | failed
    run_id: int | None = None  # global id in the metrics database (None without monitoring)
    run_number: int | None = None  # this pipeline's own run sequence (1, 2, 3, ...)
    metrics: dict[str, Any] = field(default_factory=dict)
    report: AnomalyReport | None = None
    remediation: RemediationResult | None = None
    quality: QualityMetrics | None = None
    validation: ValidationReport | None = None
    schema: Schema | None = None
    alerts: list[DispatchRecord] = field(default_factory=list)
    outputs: dict[str, str] = field(default_factory=dict)
    error: str | None = None
    duration_ms: float = 0.0

    @property
    def ok(self) -> bool:
        return self.status != "failed"

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "status": self.status,
            "run_id": self.run_id,
            "run_number": self.run_number,
            "metrics": self.metrics,
            "alerts": [a.to_dict() for a in self.alerts],
            "outputs": self.outputs,
            "error": self.error,
            "duration_ms": round(self.duration_ms, 1),
        }


class PipelineExecutor:
    def __init__(self, config: PipelineConfig, console: bool = True):
        self.config = config
        self.console = console
        self.state = PipelineState(config.state_dir)
        self.store = MetricsStore(config.db_path) if config.monitor.get("enabled", True) else None

    # -- building blocks ------------------------------------------------
    def _alert_manager(self) -> AlertManager:
        acfg = self.config.alerts or {}
        if acfg.get("enabled", True) is False:
            return AlertManager()
        notifiers = [create_notifier(n, self.config.base_dir) for n in acfg.get("notifiers", [])]
        if not notifiers and self.console and "notifiers" not in acfg:
            notifiers = [ConsoleNotifier("info")]
        rules = (
            [AlertRule.from_dict(r) for r in acfg["rules"]]
            if "rules" in acfg
            else list(DEFAULT_RULES)
        )
        rl_cfg = acfg.get("rate_limit")
        limiter = None
        if rl_cfg is not False:
            rl_cfg = dict(rl_cfg or {})
            rl_cfg.setdefault(
                "state_path", str(self.config.state_dir / f"{self.config.name}.alerts.json")
            )
            limiter = RateLimiter(**rl_cfg)
        return AlertManager(notifiers, rules, limiter)

    def _read(self) -> pd.DataFrame:
        cfg = self.config
        src_cfg = dict(cfg.source)
        max_rows = src_cfg.pop("max_rows", None)
        incremental = bool(cfg.state.get("incremental", False))
        source = create_source(src_cfg, cfg.base_dir)
        source.name = cfg.name
        with source:
            if incremental:
                return IncrementalReader(source, self.state.checkpoints).read_new()
            return source.read(limit=max_rows)

    def _schema(self, df: pd.DataFrame) -> Schema:
        scfg = self.config.schema or {}
        if scfg.get("path"):
            schema_path = self.config.resolve(scfg["path"])
            assert schema_path is not None
            if schema_path.exists():
                return Schema.load(schema_path)
            if not scfg.get("infer", True):
                raise FileNotFoundError(f"Schema file not found: {schema_path}")
            schema = infer_schema(df, name=self.config.name)
            schema.save(schema_path)  # first run bootstraps the schema file
            log.info("inferred schema written to %s", schema_path)
            return schema
        return infer_schema(df, name=self.config.name)

    # -- main -----------------------------------------------------------
    def run(self) -> PipelineResult:
        cfg = self.config
        t0 = time.perf_counter()
        run_id = self.store.start_run(cfg.name) if self.store else None
        run_number = (
            self.store.run_number(run_id)
            if self.store and run_id is not None
            else int(self.state.get(cfg.name).get("run_count", 0)) + 1
        )
        result = PipelineResult(
            name=cfg.name, status="success", run_id=run_id, run_number=run_number
        )
        try:
            self._run(result)
        except Exception as exc:
            result.status = "failed"
            result.error = f"{type(exc).__name__}: {exc}"
            log.debug("pipeline failed:\n%s", traceback.format_exc())
            msg = AlertMessage(
                f"Pipeline '{cfg.name}' failed",
                result.error,
                Severity.CRITICAL,
                cfg.name,
                "pipeline_failure",
            )
            try:
                result.alerts = self._alert_manager().dispatch([msg])
            except Exception:  # alerting must never mask the original error
                pass
        result.duration_ms = (time.perf_counter() - t0) * 1000
        result.metrics["duration_ms"] = round(result.duration_ms, 1)
        # alerts delivered on at least one channel; failed deliveries are counted apart
        result.metrics["alerts_sent"] = sum(1 for a in result.alerts if a.delivered)
        result.metrics["alerts_failed"] = sum(
            1 for a in result.alerts if a.status in ("failed", "partial")
        )
        if self.store and run_id is not None:
            detectors = (
                {r.detector: r.n_anomalies for r in result.report.results} if result.report else {}
            )
            stored = {**result.metrics, "outputs": result.outputs}
            if cfg.source.get("path"):
                stored["source"] = str(cfg.resolve(cfg.source["path"]))
            self.store.finish_run(run_id, stored, result.status, result.error, detectors)
            if result.alerts:
                self.store.add_alerts(run_id, [a.to_dict() for a in result.alerts])
        self.state.update(
            cfg.name,
            last_run_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
            last_status=result.status,
            last_run_id=run_id,
            last_error=result.error,
            run_count=int(self.state.get(cfg.name).get("run_count", 0)) + 1,
        )
        return result

    # -- reference window for incremental runs ----------------------------
    @property
    def _reference_path(self) -> Path:
        return self.state.dir / f"{self.config.name}.reference.jsonl"

    def _reference_rows(self) -> int:
        if not self.config.state.get("incremental", False):
            return 0
        return int((self.config.detection or {}).get("reference_rows", DEFAULT_REFERENCE_ROWS))

    def _load_reference(self) -> pd.DataFrame | None:
        path = self._reference_path
        if not path.exists() or path.stat().st_size == 0:
            return None
        try:
            ref = pd.read_json(path, lines=True, dtype=False, convert_dates=False)
        except ValueError:
            log.warning("ignoring unreadable reference rows in %s", path)
            return None
        return ref if not ref.empty else None

    def _save_reference(self, reference: pd.DataFrame | None, batch: pd.DataFrame, n: int) -> None:
        rows = batch if reference is None else pd.concat([reference, batch], ignore_index=True)
        rows = rows.tail(n)
        self.state.dir.mkdir(parents=True, exist_ok=True)
        text = rows.to_json(orient="records", lines=True, date_format="iso", default_handler=str)
        tmp = self._reference_path.with_suffix(".tmp")
        tmp.write_text(text if text.endswith("\n") or not text else text + "\n", encoding="utf-8")
        tmp.replace(self._reference_path)

    def _run(self, result: PipelineResult) -> None:
        cfg = self.config
        df = self._read()
        result.metrics["rows"] = len(df)
        if df.empty:
            result.status = "empty"
            result.metrics.update(n_anomalies=0, anomaly_rate=0.0)
            return

        # Incremental runs only see the new rows. Detectors are fitted on a
        # bounded window of earlier rows plus the new ones, and only the new
        # rows are reported, so a 3-row batch is judged against history.
        keep_reference = self._reference_rows()
        reference = self._load_reference() if keep_reference > 0 else None
        if reference is not None:
            reference = reference.reindex(columns=df.columns)
        combined = df if reference is None else pd.concat([reference, df], ignore_index=True)

        schema = self._schema(combined)
        result.schema = schema
        validation = SchemaValidator(schema).validate(df)
        quality = compute_quality(df, schema, validation)
        result.validation, result.quality = validation, quality

        det = cfg.detection or {}
        multipliers = self.store.thresholds() if self.store else None
        notes: list[str] = []
        if reference is None:
            coerced = validation.coerced if validation.coerced is not None else df
            if cfg.state.get("incremental", False) and len(df) < SMALL_BATCH:
                notes.append(
                    f"only {len(df)} new rows and no reference rows from earlier runs: "
                    "detectors were fitted on this batch alone, so results are unreliable"
                    + ("" if keep_reference else " (detection.reference_rows is 0)")
                )
        else:
            full = SchemaValidator(schema).validate(combined).coerced
            coerced = full if full is not None else combined
        report = run_detectors(
            coerced,
            cfg.detectors,
            columns=det.get("columns"),
            group_by=det.get("group_by"),
            time_column=det.get("time_column"),
            combine=det.get("combine", "any"),
            min_votes=int(det.get("min_votes", 1)),
            threshold_multipliers=multipliers,
        )
        if reference is not None:
            report = report.tail(len(reference))
            result.metrics["reference_rows"] = len(reference)
        for note in notes:
            log.warning("[%s] %s", cfg.name, note)
        report.warnings.extend(notes)
        if report.warnings:
            result.metrics["warnings"] = list(report.warnings)
        report.index = list(df.index)
        result.report = report
        if keep_reference > 0:
            self._save_reference(reference, df, keep_reference)

        remediation = None
        if cfg.remediation is not None and cfg.remediation.get("enabled", True):
            rcfg = {k: v for k, v in cfg.remediation.items() if k not in ("enabled", "llm")}
            llm_cfg = cfg.remediation.get("llm") or {}
            llm = LLMSuggester.from_config(llm_cfg) if llm_cfg.get("enabled") else None
            remediation = RemediationPipeline(
                rcfg,
                schema=schema,
                llm=llm,
                llm_auto_apply=bool(llm_cfg.get("auto_apply", False)),
                llm_min_confidence=float(llm_cfg.get("min_confidence", 0.8)),
                llm_max_items=int(llm_cfg.get("max_items", 20)),
            ).run(df, report)
            result.remediation = remediation
            if cfg.review.get("enabled", True) and remediation.flagged:
                ReviewQueue(cfg.review_db_path).add_flagged(
                    remediation.flagged, pipeline=cfg.name, run_id=result.run_id
                )

        previous = self.store.last_run(cfg.name) if self.store else None
        result.metrics.update(
            n_anomalies=report.n_anomalies,
            anomaly_rate=round(report.anomaly_rate, 6),
            quality_score=quality.score,
            completeness=quality.completeness,
            validity=quality.validity,
            uniqueness=quality.uniqueness,
            freshness=quality.freshness,
            invalid_rows=quality.invalid_rows,
            duplicate_rows=quality.duplicate_rows,
            null_counts=quality.null_counts,
            violations=quality.violations,
            cells_changed=remediation.n_changed_cells if remediation else 0,
            rows_dropped=len(remediation.dropped) if remediation else 0,
            flagged_for_review=len({f.row for f in remediation.flagged}) if remediation else 0,
            anomalies_by_detector=report.counts_by_detector(),
            anomalies_by_column=report.counts_by_column(),
        )

        metrics_for_rules = dict(result.metrics)
        if previous:
            metrics_for_rules["previous"] = previous
        result.alerts = self._alert_manager().process(metrics_for_rules, source=cfg.name)

        if self.store and result.run_id is not None:
            limit = int(cfg.monitor.get("store_anomalies", 1000))
            findings = sorted(report.findings, key=lambda f: -f.score)
            self.store.add_anomalies(result.run_id, [f.to_dict() for f in findings], limit=limit)
            if cfg.monitor.get("auto_tune", False):
                FeedbackLoop(self.store).tune()

        self._write_outputs(df, result)

    def _write_outputs(self, df: pd.DataFrame, result: PipelineResult) -> None:
        sink = self.config.sink
        if not sink:
            return
        resolve = self.config.resolve
        if sink.get("path"):
            data = result.remediation.data if result.remediation is not None else df
            out = write_frame(
                data,
                resolve(sink["path"]),
                sink.get("type"),
                sink.get("table"),
                sink.get("mode", "overwrite"),
            )
            result.outputs["data"] = str(out)
        if sink.get("anomalies_path") and result.report is not None:
            p = resolve(sink["anomalies_path"])
            assert p is not None
            result.report.to_json(p)
            result.outputs["anomalies"] = str(p)
        if sink.get("report_path") and result.remediation is not None:
            p = resolve(sink["report_path"])
            assert p is not None
            Path(p).parent.mkdir(parents=True, exist_ok=True)
            text = (
                result.remediation.report().to_markdown()
                if str(p).endswith(".md")
                else result.remediation.report().to_json()
            )
            Path(p).write_text(text, encoding="utf-8")
            result.outputs["report"] = str(p)


def run_pipeline(config: PipelineConfig | str | Path, console: bool = True) -> PipelineResult:
    if not isinstance(config, PipelineConfig):
        config = PipelineConfig.load(config)
    return PipelineExecutor(config, console=console).run()
