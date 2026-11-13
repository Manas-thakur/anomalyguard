---
title: Sources
description: Where AnomalyGuard reads data from, and how incremental reads work.
---

A **source** reads data into a pandas DataFrame. In a [pipeline](/anomalyguard/docs/concepts/pipelines/) it is the `source:` mapping; in Python it is a class in `anomalyguard.ingest`; on the CLI any file path works.

## Source types

| `type` | Class | Reads | Notes |
|---|---|---|---|
| `csv`, `tsv` | `CSVSource` | `.csv`, `.tsv`, `.txt`, `.tab`, optionally `.gz` / `.bz2` / `.zip` / `.xz` | Tab-separated when the path ends in `.tsv` or `.tab` |
| `json`, `jsonl`, `ndjson` | `JSONSource` | JSON arrays/objects, or one record per line | `records_path` picks a nested list; nested objects are flattened |
| `parquet` | `ParquetSource` | `.parquet`, `.pq` | Needs the `parquet` extra (pyarrow) |
| `sql`, `sqlite`, `database` | `SQLSource` | a `table` or a `query` | SQLite files work out of the box; other databases need the `sql` extra and a SQLAlchemy URL |
| `rest`, `api`, `http` | `RESTSource` | JSON from an HTTP endpoint | Page, offset, cursor and next-link pagination |
| (Python only) | `StreamSource` | a DataFrame, an iterable of records or DataFrames, or a callable returning one | Each read consumes what the stream yields now |

When `type` is omitted, it is guessed from the `path` or `url`: by extension for files, `sqlite:` / `postgresql:` / `mysql:` prefixes and `.db` / `.sqlite` / `.sqlite3` files for SQL, and `http(s)://` for REST.

On the CLI, `profile`, `validate`, `detect` and `fix` accept `.csv`, `.tsv`, `.json`, `.jsonl` / `.ndjson` and `.parquet` files (optionally gzip-compressed). SQLite files need `--table NAME`.

## Options per type

**Files** (`csv`, `tsv`): `path`, `delimiter`, `has_header` (default `true`), `encoding` (`utf-8`), `compression` (`infer`), `read_options` (extra arguments for `pandas.read_csv`).

**JSON** (`json`, `jsonl`): `path`, `format` (`auto`, `json` or `jsonl`), `records_path` (dotted path to the list of records, for example `data.items`), `flatten` (default `true`), `encoding`.

**Parquet**: `path`, `columns` (read only these).

**SQL**: `url` (a SQLite file path or any SQLAlchemy URL such as `postgresql://user@host/db`), and either `table` or `query`.

**REST**: `url`, `method` (`GET`), `params`, `headers`, `records_path`, `pagination`, `max_pages` (100), `timeout` (30 s), `api_key_env` (name of an environment variable holding a token), `api_key_header` (`Authorization`; the token is sent as `Bearer <token>` in that header, or as-is in any other header), `rate_limit_seconds` (pause between pages, 0).

```yaml
source:
  type: rest
  url: https://api.example.com/v1/orders
  records_path: data.items
  api_key_env: ORDERS_API_TOKEN
  pagination: {type: page, param: page, start: 1, size_param: per_page, size: 500}
  # {type: offset, param: offset, limit_param: limit, size: 500}
  # {type: cursor, param: cursor, cursor_path: meta.next_cursor}
  # {type: next_link, next_path: links.next}
```

**All sources** accept `name` and `cursor`. In a pipeline, `max_rows` caps how many rows are read.

Relative `path` values (and SQLite file URLs) are resolved against the pipeline file's folder.

## Incremental reads

Every source tracks two things while it reads: an **offset** (rows consumed) and, when `cursor` names a column, a **watermark** (the largest cursor value seen). With `state.incremental: true`, a pipeline saves a checkpoint after each batch under `.anomalyguard/state/` and the next run only reads what is new:

- **With a cursor** (for example `cursor: updated_at` or `cursor: id`), only rows whose cursor value is strictly greater than the watermark are returned. For SQL sources the filter is pushed into the query. This is the reliable choice for tables that change.
- **Without a cursor**, replayable sources (files, SQL, REST) skip the number of rows already read, which suits append-only files.

A run that finds no new rows is recorded with status `empty` and does nothing else.

```yaml
source:
  type: sql
  url: data/events.db
  table: events
  cursor: id
state:
  incremental: true
```

## In Python

```python
import anomalyguard as ag
from anomalyguard.ingest import create_source, read_any

df = ag.read("orders.csv")                        # same as read_any
df = read_any("warehouse.db", table="orders")      # SQLite

src = create_source({"type": "csv", "path": "orders.csv", "cursor": "timestamp"})
with src:
    first = src.read(limit=100)
```

See the [Python API](/anomalyguard/docs/reference/python-api/) for `IncrementalReader` and `CheckpointStore`.
