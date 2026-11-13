---
title: Schema and quality score
description: Schema files, validation rules, type coercion and how the quality score is computed.
---

A **schema** describes the columns you expect: their types and constraints, the primary key and the timestamp column. AnomalyGuard can infer one from data, and you can save it, tighten it by hand and load it again.

## Schema files

Schemas are YAML or JSON. This one is `examples/orders.schema.yaml` from the repository:

```yaml
name: orders
version: 1
primary_key: [order_id]
timestamp_column: timestamp
max_age_hours: 87600        # freshness: data older than this counts as stale
fields:
  order_id:
    type: integer
    nullable: false
    unique: true
  customer_id:
    type: string
    nullable: false
    pattern: 'C\d{4}'
  region:
    type: categorical
    nullable: false
    allowed: [north, south, east, west]
  quantity:
    type: integer
    nullable: false
    min: 1
    max: 100
  unit_price:
    type: float
    nullable: false
    min: 0
```

**Top-level keys**: `name`, `version` (default 1), `primary_key` (list of columns), `timestamp_column`, `max_age_hours`, `strict` (when `true`, columns not in the schema are a schema error), `fields`.

**Field keys**: `type` (`integer`, `float`, `string`, `boolean`, `datetime`, `categorical`, `unknown`), `nullable` (default `true`), `unique`, `min`, `max`, `min_length`, `max_length`, `pattern` (regular expression), `allowed` (alias `enum`), `description`. A field can also be written as just its type: `status: categorical`. Unknown keys are rejected.

## Inferring a schema

```bash
anomalyguard profile orders.csv --schema-out orders.schema.yaml
```

Inference picks a type for every column and adds conservative constraints: `nullable: false` for columns without nulls, `min: 0` for non-negative numeric columns, `allowed` values for small categoricals, `unique` for id-like columns (which also become the primary key), `max: now` for timestamp columns whose values are at least 95% in the past, and an email `pattern` for text columns that hold email addresses. `max: now` is evaluated each time data is validated (with a day of slack for time zones), so a saved schema never goes stale; it reports values such as `2031-01-01 10:00:00 is in the future`. In a pipeline, `schema.path` is loaded if the file exists; otherwise it is inferred on the first run and saved there, so you can edit it afterwards.

## Validation

`anomalyguard validate FILE --schema schema.yaml` checks every row and exits with code 1 when any rule fails. The rules reported are `type`, `not_null`, `unique`, `primary_key`, `min`, `max`, `min_length`, `max_length`, `pattern` and `allowed`.

```
FAILED: 48/1000 rows with violations, quality score 97.8%

row  column         rule  value  message
---  -------------  ----  -----  ---------------
10   quantity       max   493    493.0 > max 100
24   delivery_days  max   63     63.0 > max 30
...
```

Validation also **coerces** values to the schema types, so `"12.5"` in a float column becomes `12.5` and `"unknown"` becomes missing (and counts as a `type` violation). Detection runs on the coerced data, so one stray string does not hide a numeric column from the detectors.

## Quality score

Every profile, validation and pipeline run computes four dimensions and a weighted score:

| Dimension | Meaning | Weight |
|---|---|---|
| `completeness` | share of non-missing cells | 0.3 |
| `validity` | share of rows with no schema violation (1.0 without a schema) | 0.4 |
| `uniqueness` | share of rows that are not duplicates (on the primary key if there is one, otherwise the full row) | 0.2 |
| `freshness` | 1.0 when the newest `timestamp_column` value is within `max_age_hours`, falling linearly to 0 at twice that age | 0.1 |

Freshness is only computed when the schema has both `timestamp_column` and `max_age_hours`; otherwise it is left out and the other weights are renormalised. The score is reported as `quality_score` in run metrics, where [alert rules](/anomalyguard/docs/concepts/alerts/) can use it together with `completeness`, `validity`, `uniqueness`, `freshness`, `invalid_rows` and `duplicate_rows`.

## In Python

```python
import anomalyguard as ag
from anomalyguard.schema import Schema, SchemaValidator, compute_quality

df = ag.read("orders.csv")
schema = Schema.load("orders.schema.yaml")

prof = ag.profile(df, schema=schema)
print(prof.quality.score, prof.validation.counts_by_rule())

report = SchemaValidator(schema).validate(df)
print(report.passed, report.n_invalid_rows)
print(compute_quality(df, schema, report).to_dict())
```

`SchemaRegistry(root)` stores versions of a schema as `<root>/<name>/v<version>.yaml` (`register`, `get`, `versions`, `names`).
