---
title: Troubleshooting and FAQ
description: anomalyguard doctor, common errors and how to fix them, and frequently asked questions.
---

## Start with `anomalyguard doctor`

```bash
anomalyguard doctor            # add --json for scripts
```

```
AnomalyGuard 0.3.0  (Python 3.x.y, <platform>)
  executable: <path to python>

State
  ok  directory  /home/me/project/.anomalyguard
  ok  database   /home/me/project/.anomalyguard/anomalyguard.db (present)
      runs: 3, review pending: 36, uploads: 0

Extras
  ok  server   installed
  ok  parquet  installed
  ok  sql      installed

Environment
      ANOMALYGUARD_API_KEY         not set        API key required by the dashboard/API
      ANOMALYGUARD_CORS_ORIGINS    not set        browser origins allowed to call the API
      ...

Pipelines
  --  folder pipelines (not created yet)
  ok  folder examples
  ok  orders_quality       examples/pipeline.yaml
  ok  sensor_monitor       examples/sensor_pipeline.yaml

Notifiers
  ok  orders_quality       console  >= info
  ok  orders_quality       file     >= info     ../out/alerts.jsonl
  ok  sensor_monitor       console  >= info

No problems found.
```

(Example output; paths and versions differ on your machine.) It checks that the state directory is writable, the database and its contents, which extras are installed, the server environment variables (secret values are never printed), every pipeline file in the pipeline folders, and whether each notifier's URL or password is available. It exits with code 1 only when the state directory is not writable. The web app's **Settings** page shows the same information.

## Common problems

**`The web app needs the server extra`.** Install it: `pip install "anomalyguard[server] @ git+https://github.com/Manas-thakur/anomalyguard"`.

**`Parquet support needs pyarrow`.** Install the `parquet` extra. Databases other than SQLite need the `sql` extra.

**The web app shows no runs.** `anomalyguard run` and `anomalyguard serve` keep state in `.anomalyguard/` under the *current directory*. Start both from the same folder, or point `serve --db` at the database the runs wrote to (or set `monitor.db` in the pipeline).

**My pipeline is not on the Pipelines page.** The server scans `pipelines/` and `examples/` under its working directory. Use `serve --pipeline-dir DIR` (repeatable) or `ANOMALYGUARD_PIPELINE_DIRS=dir1,dir2`. Invalid files are listed with their error.

**`401 Missing or invalid API key`.** The server has `ANOMALYGUARD_API_KEY` set. Send it as `X-API-Key` or `Authorization: Bearer`; in the web app, enter it when asked. `/api/docs` needs it too.

**`413` on upload.** The file is above the upload limit (100 MB by default). Raise it with `serve --max-upload-mb N` or `ANOMALYGUARD_MAX_UPLOAD_MB`, and in your reverse proxy.

**A pipeline run fails with `Webhook notifier needs a url`.** A webhook or Slack notifier got an empty URL, usually because `${SLACK_WEBHOOK_URL}` is not set. Set the variable, or comment the notifier out.

**`error: pipeline 'x' has no schedule; pass --every 5m`.** `run --schedule` needs `schedule.every` (or `interval_seconds`) in the file, or pass `--every`.

**`File not found` right after `anomalyguard init -o some/dir/pipeline.yaml`.** Paths in a pipeline are relative to the YAML file, and `init` writes `--source` as given. Give `--source` relative to the output folder, or edit `source.path`.

**`Unknown top-level keys`.** The pipeline has a key outside `name`, `description`, `source`, `schema`, `detectors`, `detection`, `remediation`, `review`, `alerts`, `sink`, `monitor`, `state`, `schedule`. Check the indentation. See the [Pipeline YAML reference](/anomalyguard/docs/reference/pipeline-yaml/).

**SQLite file: `--table` is required.** For `.db` / `.sqlite` files, pass `--table NAME` on the CLI or `table:` / `query:` in the source.

**A job shows `interrupted`.** The server stopped while it was queued or running. Start it again from the Analyze or Pipelines page.

**`No threshold changes` from `feedback tune`.** A detector needs at least 3 reviews since it was last tuned, and its precision must be below 80% (to raise the threshold) or at least 95% with a multiplier above 1.0 (to relax it).

**`-v` for details.** `anomalyguard -v <command>` prints debug logs and full tracebacks.

## Detection questions

**Too many findings.** Raise the threshold for the noisy detector (`threshold:` in its spec, or `Settings → Detector thresholds`), use a lower sensitivity in Analyze, use `--combine vote` so detectors must agree, or mark false positives and run `feedback tune`. `contamination: 0.01` flags a fixed 1% instead.

**It misses values that are wrong for their category.** Use `group_by` (`--group-by region`) so each group is scored against itself. See [Contextual detection](/anomalyguard/docs/concepts/detectors/#contextual-detection).

**Time-series detectors flag nonsense.** They assume rows are in time order. Set `time_column` (`--time-column timestamp`, `detection.time_column`), and set `period` to the number of samples per cycle (24 for hourly data with a daily cycle).

**An ID column is being scored.** Columns named `id`, `index`, `row`, `row_id` or ending in `_id` are skipped automatically. Others need an explicit `columns` list.

**`freshness` is missing from the quality score.** It needs `timestamp_column` and `max_age_hours` in the schema.

## FAQ

**Is AnomalyGuard free?** Yes, it is MIT licensed.

**Does my data leave my machine?** Only if you configure it to: REST sources, webhook, Slack and email notifiers, and the optional LLM suggestions (use a local Ollama model to keep data local). Everything else, including the web app, runs locally.

**Does it need scikit-learn, Node.js or a database server?** No. The detectors are implemented in NumPy (SciPy provides the t-distribution and the KD-tree), the web app ships prebuilt in the package, and state is SQLite.

**Can several people use one server?** It is single-user: there are no accounts or roles, only one shared API key.

**Can it read from Kafka, S3 or a file watch?** Not built in. Use `StreamSource` from Python to feed records from any client, or paths pandas can read.

**Does it support cron expressions?** No, only intervals (`30s`, `5m`, `1h`, `1d`). Use cron to call `anomalyguard run` if you need calendar schedules.

**How do I get approved review values into my data?** For web app analyses, **Apply** writes them into the cleaned CSV. For pipelines, call `ReviewQueue.apply(df)` in your own code. See [Applying decisions](/anomalyguard/docs/concepts/review-and-feedback/#applying-decisions).

**How do I reset everything?** Stop the server and delete `.anomalyguard/`. It holds state only, no configuration.
