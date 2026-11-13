---
title: HTTP API reference
description: Every endpoint of the AnomalyGuard server, with parameters, bodies, responses and authentication.
---

`anomalyguard serve` (with the `server` extra) starts a FastAPI app that serves the web app and this JSON API on `http://127.0.0.1:8765` by default. The web app does everything through these endpoints. Interactive OpenAPI docs are at `/api/docs` and the schema at `/api/openapi.json`.

## Conventions

**Authentication.** When `ANOMALYGUARD_API_KEY` is set, every request to a path under `/api/` must carry the key, either as `X-API-Key: <key>` or as `Authorization: Bearer <key>`. Without it the server answers `401` with `WWW-Authenticate: ApiKey`. `/api/auth`, `/health`, the web app's pages and assets, and CORS preflight (`OPTIONS`) requests stay open. `/api/docs` and `/api/openapi.json` are under `/api/`, so they need the key too.

```bash
curl -H "X-API-Key: $ANOMALYGUARD_API_KEY" "http://127.0.0.1:8765/api/runs?limit=5"
```

**Pagination.** List endpoints that take `limit` and `offset` return a JSON array and put the total number of matches in the `X-Total-Count` response header (`/api/runs`, `/api/runs/{id}/anomalies`, `/api/review`).

**Errors.** Errors are JSON `{"detail": "..."}`: `401` (missing or wrong key), `404` (unknown id), `409` (pipeline file already exists), `413` (upload too large), `422` (invalid input).

**Background jobs.** Analyses and pipeline runs are background jobs. Their endpoints return `202` with a `job`; poll `GET /api/jobs/{id}`, or pass `?wait=true` to block until the job finishes.

**Web app routes.** `GET` requests to paths outside `/api/` that are not files are answered with the web app (single-page app fallback), so routes such as `/runs/42` or `/review` can be opened and reloaded directly. `/api/*`, `/static/*`, `/health` and paths that look like files (with a dot in the last segment) never fall back: unknown ones return `404`. Built assets under `/static/assets/` have content-hashed names and are served with `Cache-Control: public, max-age=31536000, immutable`; everything else is revalidated (`no-cache`).

**Headers.** Responses carry `X-Content-Type-Options: nosniff`, `Referrer-Policy: same-origin` and `X-Frame-Options: DENY`. With `ANOMALYGUARD_CORS_ORIGINS`, the listed origins may call the API from a browser (methods `GET`, `POST`, `PUT`, `DELETE`; request headers `X-API-Key`, `Authorization`, `Content-Type`; `X-Total-Count` and `Content-Disposition` exposed).

## Service

| Method | Path | Description |
|---|---|---|
| GET | `/health` | Liveness: `{"status": "ok", "version", "db"}`. Never needs a key |
| GET | `/api/auth` | `{"auth_enabled", "authenticated"}`: whether a key is required and whether this request has a valid one. Never needs a key |
| GET | `/api/summary` | Totals, pipelines, last run, review counts (`review`), threshold multipliers, number of analyses and datasets, active jobs |
| GET | `/api/settings` | Version, server settings (`auth_enabled`, `cors_origins`, `max_upload_mb`, `pipeline_dirs`, `workers`), state, extras, environment variables (secret values never included), notifiers per pipeline, thresholds, precision, working directory |
| GET | `/api/detectors` | Available detectors with category and description |

## Runs

| Method | Path | Description |
|---|---|---|
| GET | `/api/runs` | Run history, newest first. Query: `limit` (1-1000, default 100), `offset`, `pipeline`, `status` (`success`, `failed`, `empty`, ...), `kind` (`analysis` or `pipeline`), `q` (text search). `X-Total-Count` |
| GET | `/api/runs/{run_id}` | One run with its metrics, `breakdown` (findings by column and detector), `alerts`, `artifacts` (downloadable file names), `kind` and its number of review items (`review`) |
| GET | `/api/runs/{run_id}/anomalies` | Stored findings. Query: `limit` (1-5000, default 200), `offset`, `column`, `detector`, `severity` (`high`, `medium`, `low`), `q`, `sort` (`score`, `row`, `column`, `detector`, `id`; default `score`), `order` (`asc`, `desc`; default `desc`). `X-Total-Count` |
| GET | `/api/runs/{run_id}/artifacts/{name}` | Download a run output (cleaned data, reports, anomalies) by a name from `artifacts` |
| GET | `/api/alerts` | Recent alerts. Query: `limit` (1-1000, default 100), `run_id` |
| GET | `/api/metrics/series` | Run metrics over time grouped per pipeline: `{"since", "series": [{"pipeline", "points": [...]}]}`. Query: `pipeline`, `days` (up to 3650), `kind` (`analysis` or `pipeline`) |

## Incidents

| Method | Path | Description |
|---|---|---|
| GET | `/api/runs/{run_id}/incidents` | The run's findings grouped into incidents, most severe first, each with kind, title, explanation, expected range, actual value, change, severity, status and chart type. Muted incidents are left out (and counted in `muted`) unless `include_muted=true` |
| GET | `/api/runs/{run_id}/incidents/{incident_id}/chart` | Chart data: a distribution or time series with the expected band and marked values, or run history |
| POST | `/api/runs/{run_id}/incidents/{incident_id}/triage` | Body `{"action": "normal" \| "confirm" \| "reopen", "note": "..."}`. `normal` records false-positive feedback for the findings (up to 1,000) and rejects matching pending review items; `confirm` records true positives and queues the flagged cells for review; `reopen` clears the status. Returns `feedback`, `queued`, `rejected` counts, the updated `incident` and review counts |
| POST | `/api/runs/{run_id}/incidents/{incident_id}/mute` | Body `{"hours": 24, "note": "..."}` (hours above 0, at most 720; default 24). Mutes this kind of incident on this source and column |
| GET | `/api/incidents/mutes` | Active mutes |
| DELETE | `/api/incidents/mutes/{mute_id}` | Remove a mute |
| GET | `/api/incidents` | Incidents of the most recent successful runs, newest run first (the Health feed). Query: `limit` (1-200, default 20), `include_muted` |
| GET | `/api/health/overview` | Per-source health rows (status, quality trend, open incidents, last run) and KPIs |

## Datasets

Uploads are stored under `uploads/` next to the database.

| Method | Path | Description |
|---|---|---|
| POST | `/api/datasets` | Upload a file as multipart form field `file` (`.csv`, `.tsv`, `.json`, `.jsonl`, `.ndjson`, `.parquet`, `.pq`, `.csv.gz`, `.tsv.gz`, `.jsonl.gz`, `.json.gz`). `201` with the dataset; `413` above the upload limit |
| POST | `/api/datasets/sample` | Create a labelled demo dataset. Body `{"kind": "orders" \| "sensor"}` (default `orders`). `201` |
| GET | `/api/datasets` | Uploaded datasets |
| GET | `/api/datasets/{dataset_id}` | One dataset with its recent analyses (up to 20) |
| DELETE | `/api/datasets/{dataset_id}` | Delete an upload |
| GET | `/api/datasets/{dataset_id}/profile` | Inferred schema, per-column statistics and histograms, quality score |
| GET | `/api/datasets/{dataset_id}/rows` | Raw rows. Query: `offset`, `limit` (1-500, default 50) |

```bash
curl -F "file=@orders.csv" http://127.0.0.1:8765/api/datasets
```

## Analyses

An analysis runs detectors on an uploaded dataset. Each analysis is also recorded as a run named `analysis:<file>`.

| Method | Path | Description |
|---|---|---|
| POST | `/api/analyses` | Start an analysis job (`202`). Body below. Query: `wait=true` to block. Returns `{"analysis", "job"}` |
| GET | `/api/analyses` | Analyses. Query: `dataset_id`, `limit` (1-500, default 50) |
| GET | `/api/analyses/{analysis_id}` | Summary, options, available `artifacts`, and the findings `breakdown` |
| GET | `/api/analyses/{analysis_id}/rows` | Data rows with findings per cell. Query: `offset`, `limit` (1-500, default 50), `only_anomalous` (default `true`), `column`, `detector`, `severity`, `sort` (`score` or `row`) |
| POST | `/api/analyses/{analysis_id}/remediate` | Apply a remediation policy, write the cleaned file and reports, and return the summary. Body: a [remediation policy](/anomalyguard/docs/concepts/remediation/#policies), e.g. `{"default": {"missing": "auto", "outlier": "cap", "invalid": "coerce"}, "columns": {"unit_price": {"outlier": "flag"}}, "dedupe": true}` |
| GET | `/api/analyses/{analysis_id}/changes` | Cell-level diff of the last remediation. Query: `offset`, `limit` (1-1000, default 50), `column`, `strategy` |
| GET | `/api/analyses/{analysis_id}/flagged` | Values the last remediation flagged |
| POST | `/api/analyses/{analysis_id}/review` | Send the flagged values to the review queue |
| GET | `/api/analyses/{analysis_id}/download/{name}` | Download `cleaned.csv`, `remediation.md`, `remediation.json`, `anomalies.json` or `schema.yaml` |

`POST /api/analyses` body:

| Field | Default | Meaning |
|---|---|---|
| `dataset_id` | required | Uploaded dataset |
| `detectors` | `["mad", "iforest"]` | Names (or a comma-separated string) |
| `group_by` | | Column for contextual detection |
| `columns` | all numeric | Columns to score |
| `time_column` | | Sort by this column first |
| `sensitivity` | `medium` | `low` (thresholds × 1.5), `medium` (× 1.0), `high` (× 0.7), or a number from 0.1 to 10 |
| `combine` | `any` | `any`, `vote` or `all` |
| `min_votes` | `2` | For `vote` |

```bash
curl -X POST "http://127.0.0.1:8765/api/analyses?wait=true" \
  -H "Content-Type: application/json" \
  -d '{"dataset_id": "<id>", "detectors": ["mad", "iforest"], "group_by": "region"}'
```

## Jobs

| Method | Path | Description |
|---|---|---|
| GET | `/api/jobs` | Background jobs, newest first. Query: `limit` (1-500, default 50), `kind` (`analysis`, `pipeline`), `status` |
| GET | `/api/jobs/{job_id}` | One job with status (`queued`, `running`, `success`, `failed` or `interrupted`), progress, message, result or error |

Jobs are stored in the database; jobs that were queued or running when the server stopped are marked `interrupted` on restart. `ANOMALYGUARD_WORKERS` sets the number of worker threads.

## Review queue

| Method | Path | Description |
|---|---|---|
| GET | `/api/review` | Review items. Query: `status` (`pending` (default), `approved`, `rejected`, `applied`, `all`), `limit` (1-1000, default 100), `offset`, `pipeline`, `column`, `detector`, `run_id`, `q`, `sort` (`id`, `created_at`, `column`, `pipeline`, `status`, `detector`; default `id`), `order` (default `desc`). `X-Total-Count` |
| GET | `/api/review/facets` | Filter values with counts (sources, columns, detectors). Query: `status` |
| GET | `/api/review/{item_id}` | One item with context: `{"item", "row" (the full data row, for analyses), "findings" (every finding on that row), "run"}` |
| POST | `/api/review/{item_id}/approve` | Body (optional) `{"value": ..., "note": "..."}`. Without `value`, the suggestion (else the original value) is used |
| POST | `/api/review/{item_id}/reject` | Body (optional) `{"note": "..."}`. Keeps the original value |
| POST | `/api/review/{item_id}/false-positive` | Rejects the item and records false-positive feedback for its detectors. Returns `{"item", "feedback"}` |
| POST | `/api/review/bulk` | Act on many items at once (below) |

`POST /api/review/bulk` body, by ids or by filter (at most 10,000 items):

```json
{"action": "approve", "ids": [12, 13, 14], "note": "checked against invoices"}
{"action": "false_positive", "all_matching": true, "filter": {"status": "pending", "pipeline": "orders_quality", "column": "unit_price"}}
```

`action` is `approve`, `reject`, `apply` or `false_positive`. `filter` accepts `status` (default `pending`), `pipeline`, `column`, `detector`, `run_id` and `q`. `value` overrides the value for `approve` / `apply`. Only pending items are approved, rejected or marked; `apply` approves pending items first, then writes approved items of web app analyses into the analysis's cleaned file and marks them `applied` (items from pipeline runs are counted as `not_applicable`). The response has `matched`, `updated`, `skipped`, `applied`, `not_applicable` and the new review counts.

## Feedback and thresholds

| Method | Path | Description |
|---|---|---|
| POST | `/api/feedback` | Record feedback. Body `{"label": "false_positive" \| "true_positive", "anomaly_id": N}`, or `detector` (with optional `run_id`, `row_index`, `column`) instead of `anomaly_id`; optional `note`. Default label `false_positive` |
| GET | `/api/feedback` | `{"precision": {detector: {...}}, "recent": [...]}` |
| POST | `/api/feedback/tune` | Adjust multipliers from feedback since the last tune. Returns `{"changes", "thresholds"}` |
| GET | `/api/thresholds` | Multiplier per detector, with the reason and time of the last change |
| PUT | `/api/thresholds/{detector}` | Body `{"multiplier": 1.3, "reason": "..."}` (0.1 to 10) |
| DELETE | `/api/thresholds/{detector}` | Reset to 1.0 |

## Pipelines

Pipelines are YAML files in the pipeline folders (`ANOMALYGUARD_PIPELINE_DIRS` or `serve --pipeline-dir`). `{pipeline_id}` is the id returned by the list endpoint.

| Method | Path | Description |
|---|---|---|
| GET | `/api/pipelines` | `{"dirs": [{"path", "exists"}], "write_dir", "pipelines": [...]}`, each pipeline with id, file, name, description, validity and error |
| GET | `/api/pipelines/templates` | Built-in templates (`csv_quality`, `timeseries_monitor`, `database_quality`) |
| POST | `/api/pipelines` | Create `<name>.yaml` in the first pipeline folder (`201`). Body `{"name", "template" (default csv_quality), "source": "path" \| "dataset:<id>", "group_by", "value_column", "table", "cursor", "overwrite", "yaml"}` (`yaml` uses your text instead of a template). `409` if the file exists, `422` if invalid |
| GET | `/api/pipelines/{pipeline_id}` | YAML, summary, the 10 most recent runs and recent jobs |
| PUT | `/api/pipelines/{pipeline_id}` | Save edited YAML: body `{"yaml": "..."}`. `422` if invalid |
| POST | `/api/pipelines/validate` | Validate YAML text: body `{"yaml": "..."}`. Returns `{"valid", "error"}`, plus `name` and `warnings` (for example a missing source file) when valid |
| POST | `/api/pipelines/{pipeline_id}/validate` | Validate a saved file |
| POST | `/api/pipelines/{pipeline_id}/run` | Run once as a background job (`202`). Query `wait=true` to block. The run is recorded in the server's database unless the pipeline sets `monitor.db` |
