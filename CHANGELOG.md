# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses
[Semantic Versioning](https://semver.org/).

## [Unreleased]

## [0.3.1] - 2026-11-13

### Added
- Schema inference adds `max: now` to timestamp columns that are (almost) all in the past, so future timestamps are reported, and an email `pattern` to columns that hold email addresses, so malformed addresses are reported as "not a valid email address". `max: now` is evaluated at validation time.
- `flatline` detector (aliases `stuck`, `stuck_at`): flags runs of identical consecutive values (a stuck sensor or frozen feed), with a run-length threshold learned from the data.
- Incremental pipelines keep a reference window of earlier rows (`detection.reference_rows`, default 5,000, stored in the state folder): detectors are fitted on the reference rows plus the new batch and only the new rows are reported. A batch under 30 rows without reference rows gives a warning.
- CLI: `--param DETECTOR.KEY=VALUE` (repeatable, YAML values) for `detect` and `fix`, so every detector parameter and the benchmark's best configurations are reachable from the command line (`-m ensemble --param ensemble.detectors=...`); `--group-by` takes several comma-separated columns.
- CLI: `--delimiter`/`--sep`, `--encoding`, `--na-values` and `--decimal` for `profile`, `validate`, `detect` and `fix`; `fix --missing-value` (for `--missing constant`) and `fix --min/--max` (for `--outlier clip`); `detect --show-ids` lists every finding.
- `detect` and `fix` apply thresholds tuned with `feedback tune` when the `--db` state database has them (named on stderr); `--no-tuned-thresholds` turns this off.
- New `anomalyguard findings [RUN_ID]` lists stored finding ids for `feedback --anomaly-id`.
- Runs show a per-pipeline run number next to the global id (`[orders] run 3 (#17)`) in the CLI, API (`run_number`) and web app.
- The remediation JSON report has `total_changes` and `truncated`, so a change list cut at 1,000 entries is visible.

### Changed
- CSV files: only empty cells are read as missing. Text such as `NA` (North America), `N/A`, `null` or `None` stays a value everywhere CSVs are read (CLI, pipelines, uploads and cleaned files in the web app); opt in to extra tokens with `--na-values` or the source's `na_values`. A cell spelling `NaN` in a numeric column counts as missing.
- CSV delimiters are sniffed when not given (`,` `;` TAB `|`), semicolon files with decimal commas are read with `decimal=","`, and files that are not UTF-8 are read as cp1252/latin-1 with a warning. Rows with more fields than the header no longer become a made-up index (the file is rejected, or the extra fields are dropped with a warning); a file that still parses to one column whose header contains another delimiter gives a warning.
- Statistical detectors (`zscore`, `mad`, `iqr`, `grubbs`) score log-normal-like columns (positive, clearly right-skewed, close to symmetric on a log scale; not small counts or mixtures of differently scaled groups) on a log scale (`log_scale: auto`; opt out with `log_scale: false` or `--no-log-scale`). The benchmark results are unchanged. On clean log-normal data `mad` now flags 0.1% of rows instead of 6.8%, and `iqr` 2.2% instead of 10.2%. `cap` uses the same rule for its fences.
- With a time column, time-series detectors run on a regular time grid: gaps in the timestamps become empty points (with a warning giving their number and size), so seasonal phases and rolling windows follow the clock instead of the row count.
- Remediation is group-aware: with grouped detection (`--group-by`, `group_by:`) `cap` computes its fences per group from that group's unflagged values (column fences for groups under 8 values), and `median`/`mean` replacement uses the group's statistic, so a clean value is never pulled into another group's range.
- `cap`: the lower fence of a never-negative column is at least 0, integer fences are rounded outward so boundary values are not nudged (quickstart: `quantity` 10 is no longer changed to 9), and flagged values already inside the fences are left unchanged and flagged.
- When two steps change one cell (a type fix then an imputation, a cap then a schema clip), the report records one change with the original `before`, the final `after` and both strategies (`type_fix+impute_median`), and `cells_changed` counts the cell once. Cells flagged for review are not rewritten by later steps, so review items match the output.
- Install instructions and missing-extra errors use the GitHub install command pinned to the release tag (`@v0.3.0`, or `@main` for the latest code) instead of a PyPI command.
- The Docker image saves pipelines created in the web app under `/data/.anomalyguard/pipelines`, so the documented single volume keeps them.

### Fixed
- `cap` no longer overwrites values far outside the expected range (more than three fence widths past it, e.g. a value typed ×100) or negative values in never-negative columns with a plausible-looking number; they are left unchanged and flagged for review. Capped values keep the column's decimal places.
- Results and run pages: the tab bar and analysis steps no longer show stray scrollbars.
- `fix` imputed the region code `NA` (read as missing) with the most common region, and `validate` reported `not_null` errors for it.
- `validate` crashed on any `not_null` violation ("cannot convert float NaN to integer"), and `profile`/`detect` crashed on infinite values; `inf`/`-inf` are now reported as invalid values ("'inf' is not a finite number").
- Very large whole numbers (above 2^53, e.g. 1e18 or 1e300) crashed type inference and coercion; such columns are typed as float.
- A file read with the wrong delimiter silently produced made-up numbers from the extra fields.
- `--invalid drop|flag|keep` turned off outlier fixing for the column; the parseable values are now fixed and the policy applies only to the unparseable cells.
- `rolling_zscore` flagged normal readings after a stuck period because the window's spread was zero. A window whose scale falls below half the series' typical window scale now uses the typical scale: fewer false alarms, slightly lower recall (benchmark `sensor`, `window=6`: precision 0.18 -> 0.44, recall 0.19 -> 0.10).
- `fix` flags dates outside the schema range (such as `max: now` future timestamps) for review instead of leaving them unreported.
- Numeric dates such as `11/01/2026` are read in the day/month order that the column's unambiguous values allow (any `13/01/2026` means day-first), with a warning naming the choice; when a column mixes both orders, the ambiguous dates are treated as invalid.
- `--missing mean|median|interpolate` silently left text and category gaps unfilled, and `mode`/`ffill`/`bfill`/`constant` filled identifier columns; such cells are now flagged with the reason. `missing: constant` without a value and `outlier: clip` without `min`/`max` are errors instead of no-ops.
- LLM suggestions applied with `auto_apply` stayed pending in the review queue; they are queued as `applied`.
- `--combine vote` with one detector or `--min-votes` above the number of detectors silently flagged nothing; it is now clamped with a warning.
- `--time-column` with a missing column and `-m ""` were ignored; both are errors. `-m ensemble` without members explains how to give them.
- Numpy `RuntimeWarning`s for all-missing or constant columns are no longer printed.
- An empty (0-byte) CSV reported a 100% quality score; it is now an error ("file is empty"), as is a file without data rows. A SQLite file without `--table` lists its tables.
- `demo generate -n 0` wrote 1,000 rows and `-n -5` failed with a numpy error; `-o x.xlsx` wrote CSV. Both are validated (rows at least 1; `.csv`, `.jsonl` or `.parquet`), and writing to an unsupported file type is an error.
- CLI errors from a `KeyError` no longer print stray quotes; validation messages show `5`, not `np.int64(5)`; remediation reports show missing cells as `(missing)` rather than `NA`.
- Pipeline files with a bad `schedule.every` or `schedule.interval_seconds` are rejected when loaded, with the file and field in the error; `run` reports it even without `--schedule`.
- The Pipelines page, `GET /api/pipelines` and `doctor` list invalid pipeline files (YAML errors with line and column, missing name or source, bad schedule, unknown detector) with their error instead of hiding them or failing with 500; `doctor` keeps the file name and checks every file. A missing source file is shown as a warning.
- Failed webhook, Slack and email deliveries are logged as warnings with the HTTP status or error, never the webhook token. Alerts record per-channel `deliveries`, `channels` lists only channels that delivered, and status is `sent`, `partial` or `failed`; the API and run page show each failed channel's error. Run metrics add `alerts_failed`, and `alerts_sent` counts alerts delivered on at least one channel.
- `feedback --detector` and `PUT /api/thresholds/{name}` reject unknown detector names (aliases are stored under the canonical name; names like `grouped(mad by region)` are accepted).
- Feedback `row_index` is no longer double-encoded in `/api/feedback`.
- Approving an already-approved review item without a value keeps the reviewer's value; approving a whole-row item from the CLI explains there is no cell value to set.
- `review`, `feedback` and `findings` error on a `--db` path that does not exist instead of creating it; `review list --status applied` is supported. With monitoring off the CLI no longer prints `run #None`.
- Pipeline jobs started from the web app end with a summary message instead of "Running"; `/api/runs` items include `kind`; Markdown run reports are served as `text/markdown`; the mute error states the valid range.
- Docs: the Python API review-queue example approves a cell item, so `apply` writes the value; the benchmark page has the current real results and the CLI commands that reproduce the best configurations.

## [0.3.0] - 2026-11-13

### Added

- **Web app rebuilt on a component kit**: React 19, TypeScript, Vite, Tailwind CSS v4 and
  shadcn/ui (Radix primitives), with Recharts through shadcn charts for the expected-band,
  distribution, history, sparkline and trend charts, and TanStack Table for the runs, findings,
  data and diff tables. The source lives in `web/`; `pnpm build` writes the app into
  `src/anomalyguard/monitor/static/`, and the build output is committed and shipped in the wheel,
  so installing and running AnomalyGuard still needs no Node.js. Fonts (Inter, JetBrains Mono)
  are self-hosted; nothing loads from a CDN.
- Client-side routes (`/runs/12`, `/review`, `/analyze/a/<id>`, ...) can be bookmarked and
  reloaded: the server answers non-API GET paths with the app. The Health page is at `/`; links
  from the previous hash-based UI (`/#/runs/12`) are redirected.
- A **Jobs** menu in the header: a queue of running and finished analyses and pipeline runs with
  their progress. The analysis setup shows the job's steps as they run.
- Inline **confirmations** before sending flagged values to the review queue and before writing
  approved items into cleaned data.
- Skeleton loading states, toasts with undo for mutes, and empty and error states with a retry on
  every page; the review item opens as a bottom sheet and the navigation as a sheet on phones.
- `web/` checks: `pnpm typecheck`, `pnpm lint` (ESLint) and `pnpm test` (Vitest: API client,
  formatters, the review-inbox keyboard reducer). CI builds the app and fails if the committed
  build is out of date; the release workflow builds the app before the Python package.
- **Documentation site and landing page** (Astro + Starlight) in `site/`, published to
  https://manas-thakur.github.io/anomalyguard/ by `.github/workflows/pages.yml`: installation,
  quickstart, concepts, detector, pipeline YAML, CLI, HTTP API and Python API references,
  configuration, alerts, LLM-assisted remediation, deployment, benchmarks and troubleshooting.
- `CONTRIBUTING.md`.
- **Incidents**: findings of a run are grouped by source, column and kind. Each incident has a
  plain-language status tag, a one-sentence explanation, the expected range (robust MAD band, or
  trend + seasonality for time series) against the actual value, and a chart with the band shaded.
  Inline triage: *Mark as normal* (false-positive feedback), *Confirm* (true positives, flagged cells
  sent to review) and *Mute 24h* (per source, column and kind). New endpoints under
  `/api/runs/{id}/incidents`, `/api/incidents` and `/api/health/overview`.
- **Health** page (replaces Overview): KPI strip, one row per source with status, quality
  sparkline, trend arrow, open incidents and last run, and a recent-incidents feed.
- **Review inbox**: split-pane, keyboard-first triage (`j`/`k`, `a`, `r`, `m`, `e`, `x`,
  Shift+click ranges) with a bulk bar; a bottom sheet on phones.
- **Command palette** (Ctrl/Cmd+K) and a shortcuts dialog (`?`); `g` + letter navigation.
- Run metrics now include per-column null counts (analyses and pipeline runs), and analyses store
  schema violations by rule.
- `docs/design/references.md`: the design references and what was adopted from each.

### Changed

- Hashed web assets under `/static/assets/` are cached for a year (`immutable`); everything else
  is revalidated.
- The README was rewritten around the new app, with links to the documentation site.
- Run detail and analysis results open on incidents; the data / findings table moved to a tab.
- Calmer visual system: one accent, hairline borders, light elevation for floating surfaces,
  Inter for text, motion of 200 ms or less (and none under reduced motion).

### Fixed

- The LLM remediation prompt showed NumPy values as `np.float64(3035.34)`; it now shows `3035.34`.

### Removed

- The hand-written HTML/CSS/JS web app in `src/anomalyguard/monitor/static/` (replaced by the
  React build).

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

[Unreleased]: https://github.com/Manas-thakur/anomalyguard/compare/v0.3.0...HEAD
[0.3.0]: https://github.com/Manas-thakur/anomalyguard/compare/v0.2.0...v0.3.0
[0.2.0]: https://github.com/Manas-thakur/anomalyguard/releases/tag/v0.2.0
