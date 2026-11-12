"""Command-line interface: ``anomalyguard <command> ...``."""

from __future__ import annotations

import argparse
import json
import logging
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
        if v == int(v) and abs(v) < 1e15:
            s = str(int(v))
        elif abs(v) >= 1000:
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


def _read(path: str, args: argparse.Namespace):
    from anomalyguard.ingest import read_any

    opts = {}
    if getattr(args, "table", None):
        opts["table"] = args.table
    return read_any(path, **opts)


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

    df = _read(args.path, args)
    methods: list[Any] = _split(args.method) or ["mad", "iforest"]
    if args.contamination is not None:
        methods = [{"method": m, "contamination": args.contamination} for m in methods]
    report = ag.detect(
        df,
        methods,
        schema=_load_schema(args.schema),
        columns=_split(args.columns),
        group_by=args.group_by,
        time_column=args.time_column,
        combine=args.combine,
        min_votes=args.min_votes,
    )
    if args.output:
        report.to_json(args.output)
    if args.json:
        print(report.to_json(limit=args.top))
    else:
        _print_report(report, args.top)
        if args.output:
            print(f"\nFull report written to {args.output}")
    return 1 if (args.fail_on_anomalies and report.n_anomalies) else 0


def cmd_fix(args: argparse.Namespace) -> int:
    import anomalyguard as ag
    from anomalyguard.ingest import infer_schema
    from anomalyguard.pipeline.sinks import write_frame
    from anomalyguard.remediate import RemediationPipeline, RemediationPolicy, ReviewQueue

    df = _read(args.path, args)
    schema = _load_schema(args.schema) or infer_schema(df, name=Path(args.path).stem)
    policy = RemediationPolicy.from_dict(
        {
            "default": {"missing": args.missing, "outlier": args.outlier, "invalid": args.invalid},
            "dedupe": not args.no_dedupe,
            "flag_column": args.flag_column,
        }
    )
    report = ag.detect(
        df,
        _split(args.method) or ["mad"],
        schema=schema,
        columns=_split(args.columns),
        group_by=args.group_by,
        time_column=args.time_column,
    )
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
        if result.status == "failed":
            print(f"[{result.name}] run #{result.run_id} FAILED: {result.error}")
            return
        if result.status == "empty":
            print(f"[{result.name}] run #{result.run_id}: no new data")
            return
        print(
            f"[{result.name}] run #{result.run_id}: {m.get('rows')} rows, {m.get('n_anomalies')} anomalies "
            f"({pct(m.get('anomaly_rate'))}), quality {pct(m.get('quality_score'))}, "
            f"{m.get('cells_changed', 0)} cells fixed, {m.get('rows_dropped', 0)} dropped, "
            f"{m.get('flagged_for_review', 0)} flagged, {m.get('alerts_sent', 0)} alerts, {m.get('duration_ms', 0):.0f} ms"
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

    df, labels = generate(args.dataset, rows=args.rows, seed=args.seed)
    out = Path(args.output or f"{args.dataset}.csv")
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
        import uvicorn

        from anomalyguard.monitor.api import create_app
    except ImportError:
        print(
            "The dashboard needs the server extra: pip install 'anomalyguard[server]'",
            file=sys.stderr,
        )
        return 1
    app = create_app(args.db)
    print(
        f"AnomalyGuard dashboard on http://{args.host}:{args.port}  (db: {args.db}, Ctrl+C to stop)"
    )
    uvicorn.run(app, host=args.host, port=args.port, log_level="warning")
    return 0


def cmd_review(args: argparse.Namespace) -> int:
    from anomalyguard.remediate import ReviewQueue

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
    print(f"Item {item['id']} {item['status']} (value: {item['resolved_value']!r})")
    return 0


def cmd_feedback(args: argparse.Namespace) -> int:
    from anomalyguard.monitor import FeedbackLoop, MetricsStore

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
    fid = loop.mark(label, anomaly_id=args.anomaly_id, detector=args.detector, note=args.note)
    print(f"Recorded feedback #{fid}: {label}")
    return 0


def cmd_detectors(args: argparse.Namespace) -> int:
    from anomalyguard.detect import describe_detectors

    rows = [[d["name"], d["category"], d["description"]] for d in describe_detectors()]
    print(table(rows, ["name", "category", "description"], max_width=90))
    return 0


# ----------------------------------------------------------------------
# parser
# ----------------------------------------------------------------------
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
    sp.add_argument("--table", help="table name for SQLite files")
    sp.add_argument("--json", action="store_true")
    sp.set_defaults(func=cmd_profile)

    sp = sub.add_parser("validate", help="validate a dataset against a schema file")
    sp.add_argument("path")
    sp.add_argument("--schema", required=True)
    sp.add_argument("--table")
    sp.add_argument("--max-errors", type=int, default=20)
    sp.add_argument("--json", action="store_true")
    sp.set_defaults(func=cmd_validate)

    sp = sub.add_parser("detect", help="detect anomalies and explain them")
    sp.add_argument("path")
    sp.add_argument(
        "-m",
        "--method",
        default="mad,iforest",
        help="comma-separated detectors (see 'anomalyguard detectors')",
    )
    sp.add_argument("--columns", help="comma-separated columns (default: all numeric)")
    sp.add_argument("--group-by", help="detect within groups of this column (contextual anomalies)")
    sp.add_argument("--time-column", help="sort by this column first (time-series detectors)")
    sp.add_argument("--combine", choices=["any", "vote", "all"], default="any")
    sp.add_argument("--min-votes", type=int, default=2)
    sp.add_argument(
        "--contamination",
        type=float,
        help="flag this share of rows per detector instead of fixed thresholds",
    )
    sp.add_argument("--schema")
    sp.add_argument("--table")
    sp.add_argument("-o", "--output", help="write the full JSON report here")
    sp.add_argument("--top", type=int, default=10)
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
    sp.add_argument("-m", "--method", default="mad")
    sp.add_argument("--columns")
    sp.add_argument("--group-by")
    sp.add_argument("--time-column")
    sp.add_argument("--schema")
    sp.add_argument("--table")
    sp.add_argument(
        "--missing",
        default="auto",
        help="auto|mean|median|mode|ffill|bfill|interpolate|drop|flag|keep",
    )
    sp.add_argument(
        "--outlier", default="cap", help="cap|winsorize|median|mean|null|flag|drop|keep"
    )
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

    sp = sub.add_parser("serve", help="start the monitoring dashboard (needs anomalyguard[server])")
    sp.add_argument("--db", default=DEFAULT_DB)
    sp.add_argument("--host", default="127.0.0.1")
    sp.add_argument("--port", type=int, default=8765)
    sp.set_defaults(func=cmd_serve)

    sp = sub.add_parser("review", help="list/approve/reject flagged values")
    sp.add_argument("action", choices=["list", "approve", "reject"])
    sp.add_argument("id", nargs="?", type=int)
    sp.add_argument("--value", help="value to use when approving (JSON or text)")
    sp.add_argument("--note")
    sp.add_argument(
        "--status", default="pending", choices=["pending", "approved", "rejected", "all"]
    )
    sp.add_argument("--limit", type=int, default=50)
    sp.add_argument("--db", default=DEFAULT_DB)
    sp.set_defaults(func=cmd_review)

    sp = sub.add_parser(
        "feedback", help="mark anomalies as false/true positives and tune thresholds"
    )
    sp.add_argument("action", choices=["fp", "tp", "stats", "tune"])
    sp.add_argument("--anomaly-id", type=int)
    sp.add_argument("--detector")
    sp.add_argument("--note")
    sp.add_argument("--db", default=DEFAULT_DB)
    sp.set_defaults(func=cmd_feedback)

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
        format="%(levelname)s %(name)s: %(message)s",
    )
    try:
        return int(args.func(args) or 0)
    except KeyboardInterrupt:
        return 130
    except Exception as exc:
        if args.verbose:
            raise
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
