---
title: Remediation
description: The remediation order, per-column policies, strategies and what goes to review.
---

Remediation turns detection results into a cleaned dataset, following a **policy** you set per column. Every change is recorded (row, column, before, after, strategy, reason), and every value the policy cannot fix safely is **flagged** for the [review queue](/anomalyguard/docs/concepts/review-and-feedback/) instead of being rewritten.

## Order of operations

1. **Duplicates.** Rows that repeat the primary key (or the whole row, without a primary key) are dropped, keeping the first. `dedupe` can also be a list of columns, or `false`.
2. **Type errors.** Values are coerced to the schema type. With `invalid: coerce`, unparseable values such as `"unknown"` (or `inf`) in a numeric column become missing (and are imputed in step 5). `drop` drops the row, `flag` flags the cell, `keep` leaves it. Whatever the `invalid` policy, the column's parseable values still get their outliers fixed in step 3; the policy only decides what happens to the unparseable cells.
3. **Outliers.** Only cells a detector attributed to a column are touched, using the column's `outlier` policy (below). When detection was grouped (`--group-by`, `group_by:`), the strategy works within each group too. A flagged value the strategy does not move (out of range in a way a cap cannot fix safely, or already inside the capping range) is flagged for review instead. Rows flagged only by multivariate detectors (no single column) follow `unattributed`: `flag` (default), `drop` or `keep`.
4. **Schema constraints.** Numeric values outside the schema's `min` / `max` are clipped (or flagged when the column's outlier policy is `flag` or `keep`). Dates outside the schema range, such as order times in the future (`max: now`), are flagged: a wrong date cannot be repaired without inventing one. Categories that differ from an allowed value only in case or whitespace are normalised; other disallowed values are flagged.
5. **Missing values.** Filled according to the `missing` policy.
6. **Optional LLM suggestions** for flagged cells; see [LLM-assisted remediation](/anomalyguard/docs/guides/llm-remediation/). With `auto_apply`, applied suggestions are queued with status `applied`.

A cell flagged for review keeps its value through the later steps, so the review item and the output agree. When two steps change the same cell (for example a type fix and then an imputation, or a cap and then a schema clip), the report records one change with the original value as `before`, the final value as `after` and both strategies (`type_fix+impute_median`).

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
| `constant` | value for `missing: constant` (required with it; CLI `--missing-value`) | |
| `min`, `max` | bounds for `outlier: clip` (at least one is required with it; CLI `--min` / `--max`) | |
| `cap_k` | width of the `cap` fences in robust standard deviations | `3.5` |

**`missing: auto`** uses the median for numeric columns and the mode for categoricals, and flags ids, free text, datetimes and columns of unknown type.

Whatever the `missing` policy, identifier columns (named `id` / `*_id`, `unique` in the schema, or the primary key) are never filled: their missing cells are flagged. `mean`, `median` and `interpolate` only apply to numeric columns; on text, categorical or date columns the missing cells are flagged with the reason.

**Outlier strategies:**

- `cap` clips to robust fences, median ± `cap_k` × MAD / 0.6745, computed from the values that were not flagged (the same fences as the `mad` detector, on a log scale for positive, right-skewed columns). With grouped detection the fences are computed per group from that group's unflagged values, so a value is never pulled into another group's range (a yen price into a dollar range); a group with fewer than 8 unflagged values uses the column's fences. In a column that is never negative (schema `min >= 0`, no negative unflagged value, or under 1% negative values) the lower fence is at least 0. Integer columns get fences rounded outward, so a value on the boundary is not nudged, and capped values keep the column's decimal places. Only moderately out-of-range values are capped: a value more than three fence widths past the fences (for example a price typed ×100) or a negative value in a column that is never negative is left unchanged and flagged for review, because clipping it would write a plausible but wrong number. A flagged value that is already inside the (rounded) fences is also left unchanged and flagged.
- `winsorize` clips to the 1st and 99th percentiles of the column.
- `clip` clips to the explicit `min` / `max`.
- `median` and `mean` replace the value (with the group's median or mean when detection was grouped); `null` blanks it.
- `flag` sends it to review; `drop` drops the row; `keep` leaves it.

Non-numeric columns are always flagged rather than rewritten. A numeric column that still holds text (`invalid: flag`, `drop` or `keep`) is fixed through a numeric copy; only the changed cells are written back.

## Reports

`RemediationResult.report()` summarises the run (`rows_in`, `rows_out`, `rows_dropped`, `cells_changed`, `rows_flagged_for_review`, `changes_by_strategy`, `changes_by_column`, `drop_reasons`) and renders to Markdown (`to_markdown()`) or JSON (`to_json()`). The JSON lists at most 1,000 changes and has `total_changes` and `truncated`, so a cut list is visible; the Markdown shows the first 50 and "... N more". Missing cells are shown as `(missing)`, since `NA` can be a real value. The CLI writes it with `fix --report fix.md`, pipelines with `sink.report_path`, and the web app offers both as downloads on **Fix & export**.

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
