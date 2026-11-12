# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses
[Semantic Versioning](https://semver.org/).

## [Unreleased]

## [0.2.0] - 2026-11-13

### Added

- **Web app** replacing the single dashboard page: sidebar navigation with Overview,
  Analyze, Runs, Review queue, Pipelines and Settings; light and dark themes (follows the
  system, with a toggle); works down to phone width; loading, empty and error states.
  Still plain HTML/CSS/JS served by FastAPI with no build step and no JavaScript CDN.
- **Analyze flow**: upload CSV, TSV, JSON, JSONL or Parquet (drag and drop or picker),
  profile it (inferred schema, per-column statistics and histograms, quality score),
  choose detectors, group-by column and sensitivity, browse results in a paginated data
  table with anomalous cells highlighted by severity and their reasons on hover or click,
  filter by column, detector and severity, preview remediation with a per-column strategy
  and a before/after diff, then download the cleaned CSV and the Markdown/JSON reports.
  Every analysis is recorded as a run.
- **Run detail page**: KPIs, findings by column and detector, a paginated and sortable
  anomaly table with false-positive / confirm feedback, remediation summary, alerts sent
  and artifact downloads.
- **Review queue**: server-side pagination and filters (status, source, column, detector,
  search), select-all across pages, bulk approve / reject / apply / mark false positive,
  and a detail drawer with the full data row, every finding on it and an editable final
  value. "Apply" writes approved values into the analysis's cleaned file.
- **Pipelines page**: lists pipeline YAML files from configurable folders, shows and edits
  the YAML with validation, runs a pipeline now as a background job, and creates new
  pipelines from the built-in templates (optionally pointing at an uploaded file).
- **Overview charts** with a real time axis, one series per pipeline, crosshair tooltips
  and a toggleable legend; time range and run-type filters.
- **Settings page**: detector threshold multipliers (edit, reset, tune from feedback),
  notifier configuration per pipeline, optional extras and environment variable status.
- **Background jobs** (`/api/jobs`) for analyses and pipeline runs, persisted in the
  metrics database; jobs interrupted by a restart are marked as such.
- **Server hardening**: optional API key (`ANOMALYGUARD_API_KEY`, sent as `X-API-Key` or
  `Authorization: Bearer`), configurable CORS (`ANOMALYGUARD_CORS_ORIGINS`), upload size
  limit (`ANOMALYGUARD_MAX_UPLOAD_MB`), sanitised upload names, id-validated paths,
  whitelisted downloads and basic security headers.
- New REST endpoints for datasets, analyses, remediation, downloads, jobs, pipelines,
  review facets and bulk actions, settings and metric series (see the README).
- `anomalyguard doctor`: checks the state directory, database, optional extras, pipeline
  files, notifier secrets and server environment variables (`--json` for scripts).
- `anomalyguard serve --pipeline-dir DIR --max-upload-mb N`.
- Release workflow: on `v*` tags it tests, builds the sdist and wheel, creates a GitHub
  Release with them attached, pushes a multi-arch Docker image to
  `ghcr.io/manas-thakur/anomalyguard`, and publishes to PyPI through trusted publishing
  once the `PYPI_PUBLISH` repository variable is set to `true`.

### Changed

- `/api/runs`, `/api/runs/{id}/anomalies` and `/api/review` accept offset, filter and sort
  parameters and report the total match count in the `X-Total-Count` header. Their
  response bodies are unchanged.
- Review items record the detector (or problem kind: `missing`, `type`, `schema`) that
  flagged them, and the queue has a fourth status, `applied`. Existing databases are
  migrated in place on first open.
- `run_detectors` takes `threshold_scale` to raise or lower every threshold at once.
- Pipeline runs store their output paths and source in the run metrics so the run page
  can offer downloads.
- The `server` extra now includes `python-multipart` (needed for uploads).

### Removed

- `monitor/static/dashboard.html`, replaced by the web app in `monitor/static/`.

## 0.1.0 (untagged)

### Added

- First release: ingest (CSV/TSV, JSON/JSONL, Parquet, SQL, REST, streams), schema
  inference and validation, statistical / ML / time-series / contextual detectors built
  from scratch, policy-driven remediation with a review queue and optional LLM
  suggestions, alert rules and notifiers, SQLite metrics store with a feedback loop,
  declarative YAML pipelines with a scheduler, synthetic data and benchmarks, a CLI and a
  static dashboard.

[Unreleased]: https://github.com/Manas-thakur/anomalyguard/compare/v0.2.0...HEAD
[0.2.0]: https://github.com/Manas-thakur/anomalyguard/releases/tag/v0.2.0
