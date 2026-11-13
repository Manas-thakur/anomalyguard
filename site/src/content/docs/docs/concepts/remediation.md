---
title: Remediation
description: The remediation order, per-column policies, strategies and what goes to review.
---

Remediation turns detection results into a cleaned dataset, following a **policy** you set per column. Every change is recorded (row, column, before, after, strategy, reason), and every value the policy cannot fix safely is **flagged** for the [review queue](/anomalyguard/docs/concepts/review-and-feedback/) instead of being rewritten.

## Order of operations

1. **Duplicates.** Rows that repeat the primary key (or the whole row, without a primary key) are dropped, keeping the first. `dedupe` can also be a list of columns, or `false`.
2. **Type errors.** Values are coerced to the schema type. With `invalid: coerce`, unparseable values such as `"unknown"` in a numeric column become missing (and are imputed in step 5). `drop` drops the row, `flag` flags the cell, `keep` leaves it.
3. **Outliers.** Only cells a detector attributed to a column are touched, using the column's `outlier` policy (below). A value the strategy cannot move, such as a contextual anomaly that is inside the global fences, is flagged instead. Rows flagged only by multivariate detectors (no single column) follow `unattributed`: `flag` (default), `drop` or `keep`.
4. **Schema constraints.** Numeric values outside the schema's `min` / `max` are clipped (or flagged when the column's outlier policy is `flag` or `keep`). Categories that differ from an allowed value only in case or whitespace are normalised; other disallowed values are flagged.
5. **Missing values.** Filled according to the `missing` policy.
6. **Optional LLM suggestions** for flagged cells; see [LLM-assisted remediation](/anomalyguard/docs/guides/llm-remediation/).

Integer columns that became floats along the way are restored to integers when every value is whole. With `flag_column: needs_review`, a boolean column marks the rows that have flagged values.

## Policies

```yaml
remediation:
  dedupe: true                 # true | [col, ...] | false
  unattributed: flag           # flag | drop | keep
  flag_column: needs_review    # optional
  fix_types: true
  default:
    missing: auto
    outlier: cap
    invalid: coerce
  columns:
    unit_price: {outlier: flag}
    delivery_days: {outlier: clip, min: 0, max: 30}
    discount: {missing: constant, constant: 0}
```

A column policy inherits from `default` and overrides only the keys it sets.

| Key | Values | Default |
|---|---|---|
| `missing` | `auto`, `mean`, `median`, `mode`, `ffill`, `bfill`, `interpolate`, `constant`, `drop`, `flag`, `keep` | `auto` |
| `outlier` | `cap`, `winsorize`, `clip`, `median`, `mean`, `null`, `flag`, `drop`, `keep` | `cap` |
| `invalid` | `coerce`, `drop`, `flag`, `keep` | `coerce` |
| `constant` | value for `missing: constant` | |
| `min`, `max` | bounds for `outlier: clip` | |
| `cap_k` | width of the `cap` fences in robust standard deviations | `3.5` |

**`missing: auto`** uses the median for numeric columns and the mode for categoricals, and flags ids, free text, datetimes and columns of unknown type.

**Outlier strategies:**

- `cap` clips to robust fences, median ± `cap_k` × MAD / 0.6745, computed from the values that were not flagged (the same fences as the `mad` detector).
- `winsorize` clips to the 1st and 99th percentiles of the column.
- `clip` clips to the explicit `min` / `max`.
- `median` and `mean` replace the value; `null` blanks it.
- `flag` sends it to review; `drop` drops the row; `keep` leaves it.

Non-numeric columns are always flagged rather than rewritten.

## Reports

`RemediationResult.report()` summarises the run (`rows_in`, `rows_out`, `rows_dropped`, `cells_changed`, `rows_flagged_for_review`, `changes_by_strategy`, `changes_by_column`, `drop_reasons`) and renders to Markdown (`to_markdown()`) or JSON (`to_json()`). The CLI writes it with `fix --report fix.md`, pipelines with `sink.report_path`, and the web app offers both as downloads on **Fix & export**.

## Report only

Set `remediation: false` in a pipeline (or `enabled: false` inside the mapping) to detect and alert without changing data. The sink then writes the data as read.

## In Python

```python
import anomalyguard as ag
from anomalyguard.remediate import RemediationPipeline

df = ag.read("orders.csv")
report = ag.detect(df, ["mad"], group_by="region")
policy = {"default": {"missing": "auto", "outlier": "cap"}, "columns": {"unit_price": {"outlier": "flag"}}}
result = RemediationPipeline(policy).run(df, report)

result.data          # cleaned DataFrame
result.changes       # every changed cell
result.dropped       # {row: reason}
result.flagged       # FlaggedItem list for review
print(result.report().to_markdown())
```

`ag.fix(df)` is the one-line version: it detects with `mad` and applies the default policy.
