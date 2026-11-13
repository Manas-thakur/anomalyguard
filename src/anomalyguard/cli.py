"""Command-line interface: ``anomalyguard <command> ...``."""

from __future__ import annotations

import argparse
import json
import logging
import math
import sys
from pathlib import Path
from typing import Any

from anomalyguard import __version__


# ----------------------------------------------------------------------
# output helpers
# ----------------------------------------------------------------------
def _cell(v: Any, width: int = 60) -> str:
    if v is None:
        return "-"
    if isinstance(v, float):
        if math.isnan(v):
            s = "-"
        elif math.isinf(v):
            s = "inf" if v > 0 else "-inf"
        elif v == int(v) and abs(v) < 1e15:
            s = str(int(v))
        elif 1000 <= abs(v) < 1e15:
            s = f"{v:.1f}"
        else:
            s = f"{v:.4g}"
    else:
        s = str(v)
    s = s.replace("\n", " ")
    return s if len(s) <= width else s[: width - 3] + "..."


def table(rows: list[list[Any]], headers: list[str], max_width: int = 60) -> str:
    cells = [[_cell(v, max_width) for v in r] for r in rows]
    widths = [max([len(h)] + [len(r[i]) for r in cells]) for i, h in enumerate(headers)]
    line = "  ".join(h.ljust(w) for h, w in zip(headers, widths, strict=False))
    out = [line, "  ".join("-" * w for w in widths)]
    out += ["  ".join(c.ljust(w) for c, w in zip(r, widths, strict=False)) for r in cells]
    return "\n".join(x.rstrip() for x in out)


def pct(v: float | None) -> str:
    return "-" if v is None else f"{100 * v:.1f}%"


def _split(value: str | None) -> list[str] | None:
    if not value:
        return None
    return [v.strip() for v in value.split(",") if v.strip()]


class CLIError(Exception):
    """A usage error reported as ``error: ...`` with exit code 2."""


def _read(path: str, args: argparse.Namespace):
    from anomalyguard.ingest import guess_type, read_any

    opts: dict[str, Any] = {}
    if getattr(args, "table", None):
        opts["table"] = args.table
    try:
        kind = guess_type(path)
    except Exception:
        kind = None
    if kind == "csv":
        if getattr(args, "delimiter", None):
            opts["delimiter"] = args.delimiter
        if getattr(args, "na_values", None) is not None:
            opts["na_values"] = _split(args.na_values) or []
        if getattr(args, "decimal", None):
            opts["decimal"] = args.decimal
    if getattr(args, "encoding", None) and kind in ("csv", "json", "jsonl"):
        opts["encoding"] = args.encoding
    df = read_any(path, **opts)
    if df.empty:
        raise CLIError(f"{path}: no data rows to analyse")
    return df


def _parse_params(items: list[str] | None, methods: list[str]) -> dict[str, dict[str, Any]]:
    """``--param detector.key=value`` -> ``{canonical detector: {key: value}}``."""
    import yaml

    out: dict[str, dict[str, Any]] = {}
    known = {_canonical(m) for m in methods}
    for item in items or []:
        if "=" not in item or "." not in item.split("=", 1)[0]:
            raise CLIError(f"--param {item!r}: use detector.key=value, e.g. seasonal.period=24")
        target, raw = item.split("=", 1)
        det, key = target.split(".", 1)
        det_name = _canonical(det)
        if det_name not in known:
            raise CLIError(
                f"--param {item!r}: '{det}' is not one of the detectors given with -m "
                f"({', '.join(methods)})"
            )
        try:
            value = yaml.safe_load(raw) if raw.strip() else None
        except yaml.YAMLError:
            value = raw
        if key.strip() in ("detectors", "columns", "group_by") and isinstance(value, str):
            value = [v.strip() for v in value.split(",") if v.strip()]
        out.setdefault(det_name, {})[key.strip()] = value
    return out


def _canonical(name: str) -> str:
    from anomalyguard.detect.registry import canonical_name

    key = name.strip().lower()
    if key == "ensemble":
        return key
    try:
        return canonical_name(name)
    except KeyError as exc:
        raise CLIError(exc.args[0]) from None


LOG_SCALE_DETECTORS = {"zscore", "mad", "iqr", "grubbs"}


def _method_specs(args: argparse.Namespace, default: list[str]) -> list[Any]:
    if args.method is not None and not args.method.strip(", "):
        raise CLIError("-m/--method is empty; pass detector names, e.g. -m mad,iforest")
    methods = _split(args.method) or list(default)
    params = _parse_params(getattr(args, "param", None), methods)
    specs: list[Any] = []
    for m in methods:
        key = _canonical(m)
        spec: dict[str, Any] = {"method": m, **params.get(key, {})}
        if getattr(args, "contamination", None) is not None and key != "ensemble":
            spec.setdefault("contamination", args.contamination)
        if getattr(args, "no_log_scale", False) and key in LOG_SCALE_DETECTORS:
            spec.setdefault("log_scale", False)
        specs.append(spec)
    return specs


def _tuned_thresholds(args: argparse.Namespace) -> dict[str, float] | None:
    """Thresholds tuned by 'feedback tune', when the state database has any."""
    if getattr(args, "no_tuned_thresholds", False):
        return None
    db = Path(getattr(args, "db", None) or "")
    if not db.is_file():
        return None
    from anomalyguard.monitor.store import MetricsStore

    try:
        mult = {k: v for k, v in MetricsStore(db).thresholds().items() if v != 1.0}
    except Exception:  # an unreadable state db must not stop a scan
        return None
    if mult:
        shown = ", ".join(f"{k} x{v:.2f}" for k, v in sorted(mult.items()))
        print(
            f"Using tuned thresholds from {db}: {shown} (--no-tuned-thresholds to ignore)",
            file=sys.stderr,
        )
    return mult or None


def _detect_kwargs(args: argparse.Namespace) -> dict[str, Any]:
    return {
        "columns": _split(args.columns),
        "group_by": _split(args.group_by),
        "time_column": args.time_column,
        "threshold_multipliers": _tuned_thresholds(args),
    }


def _parse_value(text: str) -> Any:
    """A number (or true/false/null) if it parses as JSON, else the text."""
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return text


def _load_schema(path: str | None):
    if not path:
        return None
    from anomalyguard.schema import Schema

    return Schema.load(path)


# ----------------------------------------------------------------------
# commands
# ----------------------------------------------------------------------
def cmd_profile(args: argparse.Namespace) -> int:
    import anomalyguard as ag

    df = _read(args.path, args)
    prof = ag.profile(df, schema=_load_schema(args.schema), name=Path(args.path).stem)
    if args.schema_out:
        prof.schema.save(args.schema_out)
    if args.json:
        print(json.dumps(prof.to_dict(), indent=2, default=str))
        return 0
    q = prof.quality
    print(f"{args.path}: {q.n_rows} rows x {q.n_columns} columns\n")
    rows = []
    for c in prof.columns:
        stats = (
            f"mean={_cell(c.mean)} std={_cell(c.std)} min={_cell(c.min)} median={_cell(c.median)} max={_cell(c.max)}"
            if c.mean is not None
            else ", ".join(f"{k}({n})" for k, n in c.top_values[:3])
            or (f"{c.min} .. {c.max}" if c.min else "")
        )
        rows.append([c.name, c.dtype, c.nulls, c.unique, c.invalid, stats])
    print(table(rows, ["column", "type", "nulls", "unique", "invalid", "summary"], max_width=80))
    print()
    print(
        f"Quality score {pct(q.score)}  (completeness {pct(q.completeness)}, validity {pct(q.validity)}, "
        f"uniqueness {pct(q.uniqueness)}"
        + (f", freshness {pct(q.freshness)}" if q.freshness is not None else "")
        + ")"
    )
    if prof.validation.errors:
        counts = ", ".join(f"{k}: {v}" for k, v in sorted(prof.validation.counts_by_rule().items()))
        print(
            f"Schema violations: {len(prof.validation.errors)} ({counts}) in {prof.validation.n_invalid_rows} rows"
        )
    if q.duplicate_rows:
        print(f"Duplicate rows: {q.duplicate_rows}")
    if args.schema_out:
        print(f"\nSchema written to {args.schema_out}")
    return 0


def cmd_validate(args: argparse.Namespace) -> int:
    from anomalyguard.schema import SchemaValidator, compute_quality

    df = _read(args.path, args)
    schema = _load_schema(args.schema)
    rep = SchemaValidator(schema).validate(df)
    if args.json:
        print(json.dumps(rep.to_dict(max_errors=args.max_errors), indent=2, default=str))
        return 0 if rep.passed else 1
    q = compute_quality(df, schema, rep)
    status = "PASSED" if rep.passed else "FAILED"
    print(
        f"{status}: {rep.n_invalid_rows}/{rep.n_rows} rows with violations, quality score {pct(q.score)}"
    )
    for err in rep.schema_errors:
        print(f"  schema: {err}")
    if rep.errors:
        rows = [
            [e.row, e.column, e.rule, e.value, e.message] for e in rep.errors[: args.max_errors]
        ]
        print()
        print(table(rows, ["row", "column", "rule", "value", "message"]))
        if len(rep.errors) > args.max_errors:
            print(f"... {len(rep.errors) - args.max_errors} more")
    return 0 if rep.passed else 1


def _print_report(report, top: int) -> None:
    s = report.summary()
    print(
        f"Scanned {s['n_rows']} rows: {s['n_anomalies']} anomalous ({pct(s['anomaly_rate'])}), combine={s['combine']}"
    )
    print("By detector: " + ", ".join(f"{k}={v}" for k, v in s["detectors"].items()))
    if s["columns"]:
        print("By column:   " + ", ".join(f"{k}={v}" for k, v in s["columns"].items()))
    recs = report.records(limit=top)
    if recs:
        print(f"\nTop {len(recs)} anomalies (highest score first):")
        for r in recs:
            cols = ",".join(r["columns"]) or "(row)"
            print(f"  row {r['index']}  score={r['score']:.2f}  votes={r['votes']}  columns={cols}")
            for reason in r["reasons"][:3]:
                print(f"      - {reason}")


def cmd_detect(args: argparse.Namespace) -> int:
    import anomalyguard as ag

    specs = _method_specs(args, ["mad", "iforest"])
    df = _read(args.path, args)
    report = ag.detect(
        df,
        specs,
        schema=_load_schema(args.schema),
        combine=args.combine,
        min_votes=args.min_votes,
        **_detect_kwargs(args),
    )
    if args.output:
        report.to_json(args.output)
    if args.json:
        print(report.to_json(limit=args.top))
    else:
        _print_report(report, args.top)
        if args.show_ids:
            _print_findings(report)
        if args.output:
            print(f"\nFull report written to {args.output}")
    return 1 if (args.fail_on_anomalies and report.n_anomalies) else 0


def _print_findings(report) -> None:
    findings = sorted(report.findings, key=lambda f: -f.score)
    print(f"\nAll findings ({len(findings)}; row = 0-based position in the file):")
    rows = [[f.row, f.index, f.column or "(row)", f.detector, f.score] for f in findings]
    print(table(rows, ["row", "index", "column", "detector", "score"]))


def cmd_fix(args: argparse.Namespace) -> int:
    import anomalyguard as ag
    from anomalyguard.ingest import infer_schema
    from anomalyguard.pipeline.sinks import write_frame
    from anomalyguard.remediate import RemediationPipeline, RemediationPolicy, ReviewQueue

    default: dict[str, Any] = {
        "missing": args.missing,
        "outlier": args.outlier,
        "invalid": args.invalid,
    }
    if args.missing_value is not None:
        default["constant"] = _parse_value(args.missing_value)
    if args.min is not None:
        default["min"] = args.min
    if args.max is not None:
        default["max"] = args.max
    try:
        policy = RemediationPolicy.from_dict(
            {"default": default, "dedupe": not args.no_dedupe, "flag_column": args.flag_column}
        )
    except ValueError as exc:
        raise CLIError(str(exc)) from None
    specs = _method_specs(args, ["mad"])
    df = _read(args.path, args)
    schema = _load_schema(args.schema) or infer_schema(df, name=Path(args.path).stem)
    report = ag.detect(df, specs, schema=schema, **_detect_kwargs(args))
    result = RemediationPipeline(policy, schema=schema).run(df, report)
    write_frame(result.data, args.output)
    rep = result.report()
    s = rep.summary()
    print(f"Wrote {s['rows_out']} rows to {args.output}")
    print(
        f"  {s['cells_changed']} cells fixed, {s['rows_dropped']} rows dropped, "
        f"{s['rows_flagged_for_review']} rows flagged for review"
    )
    if s["changes_by_strategy"]:
        print(
            "  by strategy: "
            + ", ".join(f"{k}={v}" for k, v in sorted(s["changes_by_strategy"].items()))
        )
    if args.report:
        text = rep.to_markdown() if args.report.endswith(".md") else rep.to_json()
        Path(args.report).parent.mkdir(parents=True, exist_ok=True)
        Path(args.report).write_text(text, encoding="utf-8")
        print(f"  report: {args.report}")
    if args.review_db and result.flagged:
        ReviewQueue(args.review_db).add_flagged(
            result.flagged, pipeline=f"fix:{Path(args.path).name}"
        )
        print(f"  {len(result.flagged)} items added to review queue {args.review_db}")
    return 0


def cmd_run(args: argparse.Namespace) -> int:
    from anomalyguard.pipeline import PipelineConfig, PipelineExecutor, Scheduler, parse_duration

    configs = [PipelineConfig.load(p) for p in args.pipelines]

    def show(result) -> None:
        if args.json:
            print(json.dumps(result.to_dict(), indent=2, default=str))
            return
        m = result.metrics
        # the pipeline's own run number, plus the global id used by the web app and API
        run = f"run {result.run_number}" if result.run_number else "run"
        if result.run_id is not None:
            run += f" (#{result.run_id})"
        if result.status == "failed":
            print(f"[{result.name}] {run} FAILED: {result.error}")
            return
        if result.status == "empty":
            print(f"[{result.name}] {run}: no new data")
            return
        failed_alerts = m.get("alerts_failed", 0)
        print(
            f"[{result.name}] {run}: {m.get('rows')} rows, {m.get('n_anomalies')} anomalies "
            f"({pct(m.get('anomaly_rate'))}), quality {pct(m.get('quality_score'))}, "
            f"{m.get('cells_changed', 0)} cells fixed, {m.get('rows_dropped', 0)} dropped, "
            f"{m.get('flagged_for_review', 0)} flagged, {m.get('alerts_sent', 0)} alerts"
            + (f" ({failed_alerts} with failed deliveries)" if failed_alerts else "")
            + f", {m.get('duration_ms', 0):.0f} ms"
        )
        for k, v in result.outputs.items():
            print(f"    {k}: {v}")

    if args.schedule or args.every:
        jobs = []
        for cfg in configs:
            interval = parse_duration(args.every) if args.every else cfg.interval_seconds
            if not interval:
                print(
                    f"error: pipeline '{cfg.name}' has no schedule; pass --every 5m",
                    file=sys.stderr,
                )
                return 2
            jobs.append((cfg, interval))
        names = ", ".join(f"{c.name} every {int(i)}s" for c, i in jobs)
        print(f"Scheduling {names} (Ctrl+C to stop)")
        sched = Scheduler(jobs, max_runs=args.max_runs, on_result=show)
        try:
            results = sched.run()
        except KeyboardInterrupt:
            print("\nStopped.")
            results = sched.results
        return 0 if all(r.ok for r in results) else 1

    failed = False
    for cfg in configs:
        result = PipelineExecutor(cfg, console=not args.json).run()
        show(result)
        failed = failed or not result.ok
    return 1 if failed else 0


def cmd_init(args: argparse.Namespace) -> int:
    from anomalyguard.pipeline.templates import TEMPLATES, render_template

    if args.list:
        for name in TEMPLATES:
            print(name)
        return 0
    out = Path(args.output)
    if out.exists() and not args.force:
        print(f"error: {out} already exists (use --force to overwrite)", file=sys.stderr)
        return 1
    name = args.name or (Path(args.source).stem if args.source else "my_pipeline")
    text = render_template(
        args.template,
        name=name,
        filename=out.name,
        source=args.source,
        group_by=args.group_by,
        value_column=args.value_column,
        table=args.table,
        cursor=args.cursor,
    )
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(text, encoding="utf-8")
    print(f"Wrote {out} (template: {args.template}). Next: anomalyguard run {out}")
    return 0


def cmd_demo_generate(args: argparse.Namespace) -> int:
    from anomalyguard.demo import generate
    from anomalyguard.pipeline.sinks import write_frame

    if args.rows is not None and args.rows < 1:
        raise CLIError(f"-n/--rows must be at least 1 (got {args.rows})")
    out = Path(args.output or f"{args.dataset}.csv")
    for p in (out, Path(args.labels) if args.labels else None):
        if p is not None and p.suffix.lower() not in (".csv", ".parquet", ".jsonl"):
            raise CLIError(f"cannot write {p.name}: use a .csv, .parquet or .jsonl file name")
    df, labels = generate(args.dataset, rows=args.rows, seed=args.seed)
    write_frame(df, out)
    labels_path = Path(args.labels) if args.labels else out.with_name(out.stem + "_labels.csv")
    write_frame(labels, labels_path)
    counts = labels[labels["is_anomaly"]]["anomaly_type"].value_counts().to_dict()
    print(f"Wrote {len(df)} rows to {out} and ground truth to {labels_path}")
    print("Injected: " + ", ".join(f"{k}={v}" for k, v in sorted(counts.items())))
    return 0


def cmd_demo_benchmark(args: argparse.Namespace) -> int:
    from anomalyguard.demo import run_benchmark

    datasets = _split(args.datasets) or ["tabular", "orders", "sensor"]
    rep = run_benchmark(datasets, seed=args.seed)
    if args.json:
        print(json.dumps(rep.to_dict(), indent=2, default=str))
    else:
        print(rep.to_markdown())
    if args.output:
        Path(args.output).parent.mkdir(parents=True, exist_ok=True)
        text = (
            json.dumps(rep.to_dict(), indent=2, default=str)
            if args.output.endswith(".json")
            else rep.to_markdown()
        )
        Path(args.output).write_text(text, encoding="utf-8")
    return 0


def cmd_serve(args: argparse.Namespace) -> int:
    try:
        import multipart  # noqa: F401  (python-multipart, needed for uploads)
        import uvicorn

        from anomalyguard.monitor.api import create_app
        from anomalyguard.monitor.settings import ServerSettings
    except ImportError:
        from anomalyguard.monitor.doctor import install_command

        print(
            f"The web app needs the server extra: {install_command('server')}",
            file=sys.stderr,
        )
        return 1
    settings = ServerSettings.from_env()
    if args.pipeline_dir:
        settings.pipeline_dirs = [Path(d) for d in args.pipeline_dir]
    if args.max_upload_mb is not None:
        settings.max_upload_mb = args.max_upload_mb
    app = create_app(args.db, settings)
    auth = "API key required" if settings.auth_enabled else "no API key"
    print(
        f"AnomalyGuard on http://{args.host}:{args.port}  (db: {args.db}, {auth}, Ctrl+C to stop)"
    )
    if args.host not in ("127.0.0.1", "localhost", "::1") and not settings.auth_enabled:
        print(
            "warning: listening on a non-local address without ANOMALYGUARD_API_KEY set",
            file=sys.stderr,
        )
    uvicorn.run(app, host=args.host, port=args.port, log_level="warning")
    return 0


def cmd_doctor(args: argparse.Namespace) -> int:
    from anomalyguard.monitor import doctor
    from anomalyguard.monitor.settings import ServerSettings

    dirs = (
        [Path(d) for d in args.pipeline_dir]
        if args.pipeline_dir
        else ServerSettings.from_env().pipeline_dirs
    )
    info = doctor.collect(args.db, dirs)
    problems = []
    st = info["state"]
    if not st["writable"]:
        problems.append(f"state directory {st['state_dir']} is not writable")
    if not info["extras"]["server"]["installed"]:
        problems.append("server extra missing: anomalyguard serve will not start")
    bad = [p for p in info["pipelines"] if not p["valid"]]
    for p in bad:
        problems.append(f"invalid pipeline {p['file']}: {p['error']}")
    for entry in info["notifiers"]:
        for n in entry.get("notifiers", []):
            if not n["ok"]:
                problems.append(f"{entry['pipeline']}: {n['type']} notifier: {n['detail']}")
    if args.json:
        print(json.dumps({**info, "problems": problems}, indent=2, default=str))
        return 1 if not st["writable"] else 0

    def mark(ok: bool) -> str:
        return "ok  " if ok else "!!  "

    print(f"AnomalyGuard {info['version']}  (Python {info['python']}, {info['platform']})")
    print(f"  executable: {info['executable']}")
    print("\nState")
    print(f"  {mark(st['writable'])}directory  {st['state_dir']}")
    db_line = "present" if st["db_exists"] else "not created yet (first run creates it)"
    print(f"  {mark(True)}database   {st['db']} ({db_line})")
    if st["runs"] is not None:
        print(
            f"      runs: {st['runs']}, review pending: {st['review_pending']}, "
            f"uploads: {st['uploads']}"
        )
    print("\nExtras")
    for name, e in info["extras"].items():
        detail = "installed" if e["installed"] else f"missing {', '.join(e['missing'])}"
        print(f"  {mark(e['installed'])}{name:<8} {detail}")
    print("\nEnvironment")
    for e in info["env"]:
        value = "set" if e["set"] else "not set"
        if e["value"]:
            value = f"= {e['value']}"
        print(f"      {e['name']:<28} {value:<14} {e['purpose']}")
    print("\nPipelines")
    for d in info["pipeline_dirs"]:
        state = "" if d["exists"] else " (not created yet)"
        print(f"  {'ok  ' if d['exists'] else '--  '}folder {d['path']}{state}")
    for p in info["pipelines"]:
        print(f"  {mark(p['valid'])}{p['name'] or '?':<20} {p['file']}")
        if p["error"]:
            print(f"        {p['error']}")
        for w in p.get("warnings") or []:
            print(f"        warning: {w}")
    if info["notifiers"]:
        print("\nNotifiers")
        for entry in info["notifiers"]:
            for n in entry.get("notifiers", []):
                print(
                    f"  {mark(n['ok'])}{entry['pipeline']:<20} {n['type']:<8} "
                    f">= {n['min_severity']:<8} {n['detail']}"
                )
    print()
    if problems:
        print(f"{len(problems)} problem(s):")
        for p in problems:
            print(f"  - {p}")
    else:
        print("No problems found.")
    return 1 if not st["writable"] else 0


def _existing_db(path: str) -> bool:
    """Commands that only read or update state must not create a database at a mistyped path."""
    if Path(path).is_file():
        return True
    print(
        f"error: database not found: {path} (pass --db with the path used by 'run', 'fix --review-db' or 'serve')",
        file=sys.stderr,
    )
    return False


def cmd_review(args: argparse.Namespace) -> int:
    from anomalyguard.remediate import ReviewQueue

    if not _existing_db(args.db):
        return 1
    q = ReviewQueue(args.db)
    if args.action == "list":
        items = q.list(status=None if args.status == "all" else args.status, limit=args.limit)
        if not items:
            print("No review items.")
            return 0
        rows = [
            [
                i["id"],
                i["status"],
                i["pipeline"],
                i["row_index"],
                i["column"],
                i["value"],
                i["suggestion"],
                i["reason"],
            ]
            for i in items
        ]
        print(
            table(
                rows,
                ["id", "status", "pipeline", "row", "column", "value", "suggestion", "reason"],
                max_width=50,
            )
        )
        return 0
    if args.id is None:
        print("error: an item id is required", file=sys.stderr)
        return 2
    try:
        if args.action == "approve":
            value: Any = args.value
            if value is not None:
                try:
                    value = json.loads(value)
                except json.JSONDecodeError:
                    pass
            item = q.approve(args.id, value=value, note=args.note)
        else:
            item = q.reject(args.id, note=args.note)
    except KeyError as exc:
        print(f"error: {exc.args[0]}", file=sys.stderr)
        return 1
    if item["column"] is None:
        # whole-row items (e.g. a multivariate anomaly) have no cell to write
        print(
            f"Item {item['id']} {item['status']}: it flags the whole row "
            f"{item['row_index']!r}, so there is no cell value to set; "
            "the decision is recorded and 'apply' leaves the data unchanged."
        )
        return 0
    print(f"Item {item['id']} {item['status']} (value: {item['resolved_value']!r})")
    return 0


def cmd_feedback(args: argparse.Namespace) -> int:
    from anomalyguard.monitor import FeedbackLoop, MetricsStore

    if not _existing_db(args.db):
        return 1
    store = MetricsStore(args.db)
    loop = FeedbackLoop(store)
    if args.action == "tune":
        changes = loop.tune()
        if not changes:
            print("No threshold changes (need >= 3 new reviews per detector with precision < 80%).")
        for c in changes:
            print(
                f"{c.detector}: threshold x{c.old:.2f} -> x{c.new:.2f} (precision {c.precision:.2f} over {c.n_feedback} reviews)"
            )
        return 0
    if args.action == "stats":
        prec = loop.precision()
        mult = store.thresholds()
        rows = [
            [
                d,
                p["true_positive"],
                p["false_positive"],
                pct(p["precision"]),
                f"x{mult.get(d, 1.0):.2f}",
            ]
            for d, p in prec.items()
        ]
        print(
            table(rows, ["detector", "confirmed", "false_pos", "precision", "threshold"])
            if rows
            else "No feedback yet."
        )
        return 0
    if args.anomaly_id is None and not args.detector:
        print("error: pass --anomaly-id (see the dashboard) or --detector", file=sys.stderr)
        return 2
    label = "false_positive" if args.action == "fp" else "true_positive"
    try:
        fid = loop.mark(label, anomaly_id=args.anomaly_id, detector=args.detector, note=args.note)
    except KeyError as exc:
        print(f"error: {exc.args[0]}", file=sys.stderr)
        if args.anomaly_id is not None:
            print("  list finding ids with: anomalyguard findings RUN_ID", file=sys.stderr)
        return 1 if args.anomaly_id is not None else 2
    print(f"Recorded feedback #{fid}: {label}")
    return 0


def cmd_findings(args: argparse.Namespace) -> int:
    from anomalyguard.monitor import MetricsStore

    if not _existing_db(args.db):
        return 1
    store = MetricsStore(args.db)
    run_id = args.run_id
    if run_id is None:
        runs = store.runs(limit=1, kind="pipeline")
        if not runs:
            print("No runs recorded yet.")
            return 0
        run_id = int(runs[0]["id"])
    run = store.get_run(run_id)
    if run is None:
        print(f"error: run {run_id} not found", file=sys.stderr)
        return 1
    total = store.count_anomalies(run_id, column=args.column, detector=args.detector)
    items = store.anomalies(run_id, limit=args.limit, column=args.column, detector=args.detector)
    if args.json:
        print(json.dumps({"run_id": run_id, "total": total, "findings": items}, default=str))
        return 0
    print(
        f"Run #{run_id} ({run['pipeline']}, run {run.get('run_number')}): "
        f"{total} stored findings, highest score first"
    )
    if not items:
        return 0
    rows = [
        [a["id"], a["row_index"], a["column"] or "(row)", a["detector"], a["score"], a["reason"]]
        for a in items
    ]
    print(table(rows, ["id", "row", "column", "detector", "score", "reason"], max_width=70))
    if total > len(items):
        print(f"... {total - len(items)} more (use --limit)")
    print("\nMark one: anomalyguard feedback fp --anomaly-id ID   (or tp for a real anomaly)")
    return 0


def cmd_detectors(args: argparse.Namespace) -> int:
    from anomalyguard.detect import describe_detectors

    rows = [[d["name"], d["category"], d["description"]] for d in describe_detectors()]
    print(table(rows, ["name", "category", "description"], max_width=90))
    return 0


# ----------------------------------------------------------------------
# parser
# ----------------------------------------------------------------------
def _data_options(sp: argparse.ArgumentParser) -> None:
    sp.add_argument("--table", help="table name for SQLite files")
    sp.add_argument(
        "--delimiter",
        "--sep",
        dest="delimiter",
        help="CSV field delimiter (default: sniffed from the file; '\\t' or 'tab' for tabs)",
    )
    sp.add_argument(
        "--encoding", help="file encoding (default: UTF-8, falling back to cp1252/latin-1)"
    )
    sp.add_argument(
        "--na-values",
        help="extra CSV cell values to read as missing, comma-separated (e.g. 'NA,N/A,null'); "
        "by default only empty cells are missing",
    )
    sp.add_argument("--decimal", help="CSV decimal separator (default: '.', or ',' when detected)")


def _detect_options(sp: argparse.ArgumentParser, default_methods: str, db_default: str) -> None:
    sp.add_argument(
        "-m",
        "--method",
        default=None,
        help=f"comma-separated detectors (default: {default_methods}; see 'anomalyguard detectors')",
    )
    sp.add_argument("--columns", help="comma-separated columns (default: all numeric)")
    sp.add_argument(
        "--group-by",
        help="detect within groups of these column(s), comma-separated (contextual anomalies)",
    )
    sp.add_argument(
        "--time-column",
        help="time column: rows are sorted by it and time-series detectors run on a regular grid",
    )
    sp.add_argument(
        "--param",
        action="append",
        metavar="DETECTOR.KEY=VALUE",
        help="detector parameter, repeatable (e.g. seasonal.period=24, rolling_zscore.window=48, "
        "ensemble.detectors=mad,iforest)",
    )
    sp.add_argument(
        "--no-log-scale",
        action="store_true",
        help="score skewed positive columns on their original scale instead of a log scale",
    )
    sp.add_argument(
        "--db",
        default=db_default,
        help="state database whose tuned thresholds ('feedback tune') are applied if present",
    )
    sp.add_argument(
        "--no-tuned-thresholds",
        action="store_true",
        help="ignore thresholds tuned with 'feedback tune'",
    )


def build_parser() -> argparse.ArgumentParser:
    from anomalyguard.monitor.store import DEFAULT_DB

    p = argparse.ArgumentParser(prog="anomalyguard", description="Detect and fix data anomalies.")
    p.add_argument("--version", action="version", version=f"anomalyguard {__version__}")
    p.add_argument("-v", "--verbose", action="store_true", help="debug logging")
    sub = p.add_subparsers(dest="command", required=True, metavar="command")

    sp = sub.add_parser("profile", help="profile a dataset: types, stats, quality score")
    sp.add_argument("path")
    sp.add_argument("--schema", help="validate against this schema instead of inferring one")
    sp.add_argument("--schema-out", help="write the inferred schema (YAML/JSON)")
    _data_options(sp)
    sp.add_argument("--json", action="store_true")
    sp.set_defaults(func=cmd_profile)

    sp = sub.add_parser("validate", help="validate a dataset against a schema file")
    sp.add_argument("path")
    sp.add_argument("--schema", required=True)
    _data_options(sp)
    sp.add_argument("--max-errors", type=int, default=20)
    sp.add_argument("--json", action="store_true")
    sp.set_defaults(func=cmd_validate)

    sp = sub.add_parser("detect", help="detect anomalies and explain them")
    sp.add_argument("path")
    _detect_options(sp, "mad,iforest", DEFAULT_DB)
    sp.add_argument("--combine", choices=["any", "vote", "all"], default="any")
    sp.add_argument(
        "--min-votes", type=int, default=2, help="detectors that must agree with --combine vote"
    )
    sp.add_argument(
        "--contamination",
        type=float,
        help="flag this share of rows per detector instead of fixed thresholds",
    )
    sp.add_argument("--schema")
    _data_options(sp)
    sp.add_argument("-o", "--output", help="write the full JSON report here")
    sp.add_argument("--top", type=int, default=10)
    sp.add_argument(
        "--show-ids", action="store_true", help="also list every finding (row, column, detector)"
    )
    sp.add_argument("--json", action="store_true")
    sp.add_argument(
        "--fail-on-anomalies", action="store_true", help="exit code 1 if anomalies are found"
    )
    sp.set_defaults(func=cmd_detect)

    sp = sub.add_parser("fix", help="detect and remediate, writing a cleaned file")
    sp.add_argument("path")
    sp.add_argument(
        "-o", "--output", required=True, help="cleaned output (.csv, .jsonl, .json, .parquet)"
    )
    _detect_options(sp, "mad", DEFAULT_DB)
    sp.add_argument("--schema")
    _data_options(sp)
    sp.add_argument(
        "--missing",
        default="auto",
        help="auto|mean|median|mode|ffill|bfill|interpolate|constant|drop|flag|keep",
    )
    sp.add_argument("--missing-value", help="fill value for --missing constant")
    sp.add_argument(
        "--outlier", default="cap", help="cap|winsorize|clip|median|mean|null|flag|drop|keep"
    )
    sp.add_argument("--min", type=float, help="lower bound for --outlier clip")
    sp.add_argument("--max", type=float, help="upper bound for --outlier clip")
    sp.add_argument("--invalid", default="coerce", help="coerce|drop|flag|keep (type errors)")
    sp.add_argument("--no-dedupe", action="store_true")
    sp.add_argument("--flag-column", help="add a boolean column marking rows that need review")
    sp.add_argument("--report", help="write a remediation report (.md or .json)")
    sp.add_argument("--review-db", help="add flagged items to this review queue (SQLite)")
    sp.set_defaults(func=cmd_fix)

    sp = sub.add_parser("run", help="run pipeline YAML file(s)")
    sp.add_argument("pipelines", nargs="+")
    sp.add_argument(
        "--schedule", action="store_true", help="keep running on the pipeline's schedule"
    )
    sp.add_argument("--every", help="run repeatedly at this interval (e.g. 30s, 5m, 1h)")
    sp.add_argument("--max-runs", type=int, help="stop after N runs per pipeline")
    sp.add_argument("--json", action="store_true")
    sp.set_defaults(func=cmd_run)

    sp = sub.add_parser("init", help="write a starter pipeline.yaml")
    sp.add_argument("-t", "--template", default="csv_quality")
    sp.add_argument("-o", "--output", default="pipeline.yaml")
    sp.add_argument("--name")
    sp.add_argument("--source", help="data file / database for the pipeline")
    sp.add_argument("--group-by", help="(csv_quality) add a per-group detector")
    sp.add_argument("--value-column", help="(timeseries_monitor) column to monitor")
    sp.add_argument("--table", help="(database_quality) table name")
    sp.add_argument("--cursor", help="(database_quality) incremental cursor column")
    sp.add_argument("--force", action="store_true")
    sp.add_argument("--list", action="store_true", help="list templates")
    sp.set_defaults(func=cmd_init)

    demo = sub.add_parser("demo", help="synthetic data and benchmarks")
    dsub = demo.add_subparsers(dest="demo_command", required=True, metavar="subcommand")
    sp = dsub.add_parser("generate", help="generate a dataset with labelled anomalies")
    sp.add_argument("-d", "--dataset", default="orders", choices=["orders", "sensor", "tabular"])
    sp.add_argument("-n", "--rows", type=int)
    sp.add_argument("--seed", type=int, default=42)
    sp.add_argument("-o", "--output")
    sp.add_argument("--labels", help="ground-truth output (default: <output>_labels.csv)")
    sp.set_defaults(func=cmd_demo_generate)
    sp = dsub.add_parser(
        "benchmark", help="precision/recall/F1 of every detector on synthetic data"
    )
    sp.add_argument("--datasets", help="comma-separated: tabular,orders,sensor")
    sp.add_argument("--seed", type=int, default=42)
    sp.add_argument("-o", "--output", help="write results (.md or .json)")
    sp.add_argument("--json", action="store_true")
    sp.set_defaults(func=cmd_demo_benchmark)

    sp = sub.add_parser("serve", help="start the web app and REST API (needs anomalyguard[server])")
    sp.add_argument("--db", default=DEFAULT_DB)
    sp.add_argument("--host", default="127.0.0.1")
    sp.add_argument("--port", type=int, default=8765)
    sp.add_argument(
        "--pipeline-dir",
        action="append",
        help="folder with pipeline YAML files (repeatable; default: pipelines, examples)",
    )
    sp.add_argument("--max-upload-mb", type=float, help="upload size limit (default 100)")
    sp.set_defaults(func=cmd_serve)

    sp = sub.add_parser("doctor", help="check the environment, state, extras and notifiers")
    sp.add_argument("--db", default=DEFAULT_DB)
    sp.add_argument("--pipeline-dir", action="append", help="folder with pipeline YAML files")
    sp.add_argument("--json", action="store_true")
    sp.set_defaults(func=cmd_doctor)

    sp = sub.add_parser("review", help="list/approve/reject flagged values")
    sp.add_argument("action", choices=["list", "approve", "reject"])
    sp.add_argument("id", nargs="?", type=int)
    sp.add_argument("--value", help="value to use when approving (JSON or text)")
    sp.add_argument("--note")
    sp.add_argument(
        "--status",
        default="pending",
        choices=["pending", "approved", "rejected", "applied", "all"],
    )
    sp.add_argument("--limit", type=int, default=50)
    sp.add_argument("--db", default=DEFAULT_DB)
    sp.set_defaults(func=cmd_review)

    sp = sub.add_parser(
        "feedback", help="mark anomalies as false/true positives and tune thresholds"
    )
    sp.add_argument("action", choices=["fp", "tp", "stats", "tune"])
    sp.add_argument("--anomaly-id", type=int, help="finding id (see 'anomalyguard findings')")
    sp.add_argument("--detector", help="detector name, e.g. mad or 'grouped(mad by region)'")
    sp.add_argument("--note")
    sp.add_argument("--db", default=DEFAULT_DB)
    sp.set_defaults(func=cmd_feedback)

    sp = sub.add_parser(
        "findings", help="list a run's stored findings and their ids (for 'feedback')"
    )
    sp.add_argument("run_id", nargs="?", type=int, help="run id (default: the latest run)")
    sp.add_argument("--column")
    sp.add_argument("--detector")
    sp.add_argument("--limit", type=int, default=50)
    sp.add_argument("--json", action="store_true")
    sp.add_argument("--db", default=DEFAULT_DB)
    sp.set_defaults(func=cmd_findings)

    sp = sub.add_parser("detectors", help="list available detectors")
    sp.set_defaults(func=cmd_detectors)
    return p


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(errors="replace")  # type: ignore[union-attr]
        except (AttributeError, ValueError):
            pass
    parser = build_parser()
    args = parser.parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.WARNING,
        format="%(levelname)s %(name)s: %(message)s" if args.verbose else "%(message)s",
    )
    if not args.verbose:
        for handler in logging.getLogger().handlers:
            handler.setFormatter(_PlainFormatter())
    try:
        return int(args.func(args) or 0)
    except KeyboardInterrupt:
        return 130
    except CLIError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    except Exception as exc:
        if args.verbose:
            raise
        # KeyError's str() adds quotes around the message
        msg = exc.args[0] if isinstance(exc, KeyError) and exc.args else exc
        print(f"error: {msg}", file=sys.stderr)
        return 1


class _PlainFormatter(logging.Formatter):
    """``warning: message`` like the rest of the CLI's output."""

    def format(self, record: logging.LogRecord) -> str:
        return f"{record.levelname.lower()}: {record.getMessage()}"


if __name__ == "__main__":
    sys.exit(main())
