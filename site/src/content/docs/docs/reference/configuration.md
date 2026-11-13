---
title: Configuration
description: Environment variables, server options and the layout of the state directory.
---

AnomalyGuard is configured with command-line flags, pipeline YAML files and a few environment variables. There is no global config file.

## Environment variables

| Variable | Used by | Default | Meaning |
|---|---|---|---|
| `ANOMALYGUARD_API_KEY` | `serve` | unset (no key) | API key required for every `/api/*` request, sent as `X-API-Key` or `Authorization: Bearer`. The web app asks for it once and keeps it in the browser |
| `ANOMALYGUARD_CORS_ORIGINS` | `serve` | unset (same origin only) | Comma-separated browser origins allowed to call the API from other sites, e.g. `https://dash.example.com` |
| `ANOMALYGUARD_MAX_UPLOAD_MB` | `serve` | `100` | Largest accepted upload, in MB (`serve --max-upload-mb` overrides it) |
| `ANOMALYGUARD_PIPELINE_DIRS` | `serve`, `doctor` | `pipelines,examples` | Comma-separated folders scanned for pipeline YAML (relative to the working directory). The first one receives pipelines created in the UI. `--pipeline-dir` overrides it |
| `ANOMALYGUARD_WORKERS` | `serve` | `2` | Background job threads (analyses and pipeline runs) |
| `ANOMALYGUARD_SMTP_PASSWORD` | email notifier | | SMTP password; the default `password_env` |
| `OPENAI_API_KEY` | LLM suggestions | | Key for `provider: openai`; the default `api_key_env` |
| `SLACK_WEBHOOK_URL` | the examples | | Used as `${SLACK_WEBHOOK_URL}` in the example pipelines; any name works |

`anomalyguard doctor` and the web app's **Settings** page show which of these are set, without printing secret values.

**Secrets in pipelines.** `${VAR}` and `${VAR:-default}` are replaced with environment variables anywhere in a pipeline file. Notifiers and sources also read secrets by variable name: `url_env` (webhook, Slack), `password_env` (email), `api_key_env` (REST sources, LLM).

**Logging.** `anomalyguard -v <command>` turns on debug logging and full tracebacks.

## Server options

| Setting | Flag | Environment | Default |
|---|---|---|---|
| Database (and state folder) | `serve --db` | | `.anomalyguard/anomalyguard.db` |
| Listen address | `serve --host` | | `127.0.0.1` |
| Port | `serve --port` | | `8765` |
| Pipeline folders | `serve --pipeline-dir` (repeatable) | `ANOMALYGUARD_PIPELINE_DIRS` | `pipelines`, `examples` |
| Upload limit | `serve --max-upload-mb` | `ANOMALYGUARD_MAX_UPLOAD_MB` | `100` |
| API key | | `ANOMALYGUARD_API_KEY` | none |
| CORS origins | | `ANOMALYGUARD_CORS_ORIGINS` | none |
| Job threads | | `ANOMALYGUARD_WORKERS` | `2` |

## State directory

Runtime state lives in `.anomalyguard/` under the **current working directory** unless a flag or pipeline key moves it. Run `anomalyguard run` and `anomalyguard serve` from the same folder so they share it.

```
.anomalyguard/
├── anomalyguard.db        # SQLite: runs and metrics, stored findings, alerts, feedback,
│                          #   threshold multipliers, incident triage and mutes,
│                          #   the review queue, background jobs
├── state/
│   ├── pipelines.json     # per-pipeline run counters, last status, last error
│   ├── checkpoints.json   # incremental read offsets and watermarks
│   └── <pipeline>.alerts.json   # alert rate-limit history
├── uploads/               # files uploaded in the web app
└── analyses/              # per-analysis results: cleaned.csv, reports, anomalies.json, schema.yaml
```

| What | Default | Override |
|---|---|---|
| Metrics database | `.anomalyguard/anomalyguard.db` | `serve --db`, `doctor --db`, `review --db`, `feedback --db`, pipeline `monitor.db` |
| Review queue | the metrics database | pipeline `review.db`, `fix --review-db` |
| Checkpoints, run counters, alert history | `.anomalyguard/state/` | pipeline `state.dir` |
| Uploads and analyses | `uploads/` and `analyses/` next to the database | moves with `serve --db` |

The folder is created on first use. It is safe to delete when you want to start over; it holds no configuration. In the Docker image it is `/data/.anomalyguard`.
