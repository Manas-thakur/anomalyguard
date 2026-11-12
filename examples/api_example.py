"""End-to-end walkthrough of the Python API on the bundled orders data.

Run from the repository root:

    uv run python examples/api_example.py
"""

from __future__ import annotations

from pathlib import Path

import anomalyguard as ag
from anomalyguard.alert import AlertManager, AlertRule, ConsoleNotifier
from anomalyguard.detect import GroupedDetector, IsolationForestDetector, MADDetector, run_detectors
from anomalyguard.remediate import RemediationPipeline, ReviewQueue
from anomalyguard.schema import Schema, SchemaValidator

HERE = Path(__file__).parent
OUT = HERE.parent / "out"
OUT.mkdir(exist_ok=True)

# 1. Ingest -----------------------------------------------------------------
df = ag.read(HERE / "data" / "orders.csv")
print(f"Loaded {len(df)} rows, columns: {list(df.columns)}")

# 2. Schema & quality -----------------------------------------------------
schema = Schema.load(HERE / "orders.schema.yaml")
prof = ag.profile(df, schema=schema)
q = prof.quality
print(
    f"Quality score {q.score:.1%} (completeness {q.completeness:.1%}, "
    f"validity {q.validity:.1%}, uniqueness {q.uniqueness:.1%})"
)
print("Violations by rule:", prof.validation.counts_by_rule())

# 3. Detect -----------------------------------------------------------------
# Work on type-coerced values so stray strings in numeric columns become NaN.
coerced = SchemaValidator(schema).validate(df).coerced
cols = ["quantity", "unit_price", "delivery_days"]
report = run_detectors(
    coerced,
    [
        MADDetector(columns=cols),
        GroupedDetector(MADDetector(columns=["unit_price"]), group_by="region"),
        IsolationForestDetector(columns=cols, random_state=0),
    ],
)
print(f"\n{report.n_anomalies} anomalous rows ({report.anomaly_rate:.1%})")
for rec in report.records(limit=3):
    print(f"  row {rec['index']} score={rec['score']:.1f}")
    for reason in rec["reasons"]:
        print(f"    - {reason}")
report.to_json(OUT / "api_anomalies.json")

# 4. Remediate --------------------------------------------------------------
policy = {
    "dedupe": True,
    "default": {"missing": "auto", "outlier": "cap"},
    "columns": {"unit_price": {"outlier": "flag"}},  # prices go to a human
}
result = RemediationPipeline(policy, schema=schema).run(df, report)
summary = result.report().summary()
print(
    f"\nRemediation: {summary['cells_changed']} cells fixed, {summary['rows_dropped']} rows dropped, "
    f"{summary['rows_flagged_for_review']} rows flagged"
)
result.data.to_csv(OUT / "api_orders_clean.csv", index=False)
(OUT / "api_remediation.md").write_text(result.report().to_markdown(), encoding="utf-8")

queue = ReviewQueue(OUT / "api_review.db")
queue.add_flagged(result.flagged, pipeline="api_example")
print("Review queue:", queue.counts())

# 5. Alert ------------------------------------------------------------------
alerts = AlertManager(
    notifiers=[ConsoleNotifier("info")],
    rules=[
        AlertRule("anomaly_rate", ">", 0.03, "warning"),
        AlertRule("quality_score", "<", 0.99, "error"),
    ],
)
alerts.process(
    {"anomaly_rate": report.anomaly_rate, "quality_score": q.score}, source="api_example"
)

print(f"\nOutputs written to {OUT}")
