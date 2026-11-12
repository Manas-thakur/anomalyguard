from __future__ import annotations

import json
import sqlite3

import httpx
import pandas as pd
import pytest

from anomalyguard.ingest import (
    CheckpointStore,
    CSVSource,
    IncrementalReader,
    IngestError,
    JSONSource,
    ParquetSource,
    RESTSource,
    SQLSource,
    StreamSource,
    create_source,
    guess_type,
    infer_dtype,
    infer_schema,
    profile,
    read_any,
)
from anomalyguard.schema import DataType


def test_csv_batches_and_seek(tmp_path):
    path = tmp_path / "d.csv"
    pd.DataFrame({"id": range(25), "v": [float(i) for i in range(25)]}).to_csv(path, index=False)
    src = CSVSource(path)
    batches = list(src.read_batches(batch_size=10))
    assert [len(b) for b in batches] == [10, 10, 5]
    cp = src.checkpoint()
    assert cp.offset == 25 and cp.record_count == 25

    # append rows; a source resumed from the checkpoint only sees the new ones
    with path.open("a") as fh:
        fh.write("25,25.0\n26,26.0\n")
    src2 = CSVSource(path)
    src2.seek(cp)
    df = src2.read()
    assert df["id"].tolist() == [25, 26]


def test_tsv_and_headerless(tmp_path):
    path = tmp_path / "d.tsv"
    path.write_text("1\ta\n2\tb\n")
    df = CSVSource(path, has_header=False).read()
    assert list(df.columns) == ["col_0", "col_1"]
    assert len(df) == 2


def test_missing_file_raises(tmp_path):
    with pytest.raises(IngestError):
        CSVSource(tmp_path / "nope.csv").read()


def test_json_array_with_records_path_and_flatten(tmp_path):
    path = tmp_path / "d.json"
    path.write_text(
        json.dumps({"data": {"items": [{"a": 1, "b": {"c": 2}}, {"a": 3, "b": {"c": 4}}]}})
    )
    df = JSONSource(path, records_path="data.items").read()
    assert list(df.columns) == ["a", "b.c"]
    assert df["b.c"].tolist() == [2, 4]


def test_jsonl(tmp_path):
    path = tmp_path / "d.jsonl"
    path.write_text("\n".join(json.dumps({"x": i}) for i in range(7)) + "\n\n")
    src = JSONSource(path)
    assert src.format == "jsonl"
    assert [len(b) for b in src.read_batches(3)] == [3, 3, 1]


def test_jsonl_invalid_line(tmp_path):
    path = tmp_path / "bad.jsonl"
    path.write_text('{"x": 1}\n{oops}\n')
    with pytest.raises(IngestError, match=":2:"):
        JSONSource(path).read()


def test_parquet_roundtrip(tmp_path):
    pytest.importorskip("pyarrow")
    path = tmp_path / "d.parquet"
    pd.DataFrame({"a": range(12)}).to_parquet(path)
    assert len(ParquetSource(path).read()) == 12
    assert len(read_any(path)) == 12


def test_sqlite_incremental_watermark(tmp_path):
    db = tmp_path / "events.db"
    with sqlite3.connect(db) as conn:
        conn.execute("CREATE TABLE events (id INTEGER, value REAL)")
        conn.executemany("INSERT INTO events VALUES (?, ?)", [(i, i * 1.5) for i in range(1, 6)])
    store = CheckpointStore(tmp_path / "cp.json")
    reader = IncrementalReader(
        SQLSource(str(db), table="events", cursor="id", name="events"), store
    )
    assert reader.read_new()["id"].tolist() == [1, 2, 3, 4, 5]
    assert store.get("events").watermark == 5

    with sqlite3.connect(db) as conn:
        conn.executemany("INSERT INTO events VALUES (?, ?)", [(6, 9.0), (7, 10.5)])
    reader = IncrementalReader(
        SQLSource(f"sqlite:///{db}", table="events", cursor="id", name="events"), store
    )
    assert reader.read_new()["id"].tolist() == [6, 7]
    reader = IncrementalReader(
        SQLSource(str(db), table="events", cursor="id", name="events"), store
    )
    assert reader.read_new().empty


def test_sql_needs_query_or_table():
    with pytest.raises(ValueError):
        SQLSource("x.db")


def test_csv_cursor_on_timestamps(tmp_path):
    path = tmp_path / "t.csv"
    pd.DataFrame(
        {"ts": pd.date_range("2026-01-01", periods=4, freq="h").astype(str), "v": range(4)}
    ).to_csv(path, index=False)
    store = CheckpointStore(tmp_path / "cp.json")
    assert len(IncrementalReader(CSVSource(path, cursor="ts", name="t"), store).read_new()) == 4
    with path.open("a") as fh:
        fh.write("2026-01-01 04:00:00,4\n")
    new = IncrementalReader(CSVSource(path, cursor="ts", name="t"), store).read_new()
    assert new["v"].tolist() == [4]


def test_rest_page_pagination():
    def handler(request: httpx.Request) -> httpx.Response:
        page = int(request.url.params["page"])
        assert request.headers["Authorization"] == "Bearer secret"
        items = [{"id": page * 10 + i} for i in range(2)] if page <= 2 else []
        return httpx.Response(200, json={"results": items})

    import os

    os.environ["AG_TEST_TOKEN"] = "secret"
    src = RESTSource(
        "https://api.example.test/items",
        records_path="results",
        pagination={"type": "page", "param": "page", "start": 1},
        api_key_env="AG_TEST_TOKEN",
        transport=httpx.MockTransport(handler),
    )
    assert src.read()["id"].tolist() == [10, 11, 20, 21]


def test_rest_cursor_and_next_link():
    def cursor_handler(request: httpx.Request) -> httpx.Response:
        cur = request.url.params.get("cursor")
        if cur is None:
            return httpx.Response(200, json={"data": [{"x": 1}], "meta": {"next": "abc"}})
        return httpx.Response(200, json={"data": [{"x": 2}], "meta": {"next": None}})

    src = RESTSource(
        "https://api.example.test/c",
        records_path="data",
        pagination={"type": "cursor", "param": "cursor", "cursor_path": "meta.next"},
        transport=httpx.MockTransport(cursor_handler),
    )
    assert src.read()["x"].tolist() == [1, 2]

    def link_handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/p1":
            return httpx.Response(
                200, json={"items": [{"x": 1}], "next": "https://api.example.test/p2"}
            )
        return httpx.Response(200, json={"items": [{"x": 2}], "next": None})

    src = RESTSource(
        "https://api.example.test/p1",
        records_path="items",
        pagination={"type": "next_link", "next_path": "next"},
        transport=httpx.MockTransport(link_handler),
    )
    assert src.read()["x"].tolist() == [1, 2]


def test_rest_http_error():
    src = RESTSource(
        "https://api.example.test/x", transport=httpx.MockTransport(lambda r: httpx.Response(500))
    )
    with pytest.raises(IngestError):
        src.read()


def test_stream_source_from_generator_and_frame():
    def gen():
        for i in range(5):
            yield {"i": i}

    src = StreamSource(gen)
    assert [len(b) for b in src.read_batches(2)] == [2, 2, 1]
    # callables are re-invoked on each read; streams never skip by offset
    assert len(src.read()) == 5
    assert src.checkpoint().offset == 10
    # with a cursor, already-seen records are dropped
    cur = StreamSource(gen, cursor="i")
    assert len(cur.read()) == 5
    assert cur.read().empty
    frame = pd.DataFrame({"a": range(5)})
    assert len(StreamSource(frame).read()) == 5


def test_factory_and_guess_type(tmp_path):
    assert guess_type("x.csv.gz") == "csv"
    assert guess_type("x.ndjson") == "jsonl"
    assert guess_type("x.sqlite") == "sql"
    assert guess_type("https://host/api") == "rest"
    with pytest.raises(IngestError):
        guess_type("x.unknown")
    (tmp_path / "a.csv").write_text("a\n1\n")
    src = create_source({"type": "csv", "path": "a.csv"}, base_dir=tmp_path)
    assert len(src.read()) == 1
    with pytest.raises(IngestError):
        create_source({"type": "kafka"})
    with pytest.raises(IngestError):
        create_source({"type": "csv", "path": "a.csv", "bogus": 1}, base_dir=tmp_path)


def test_infer_dtype_tolerates_bad_values():
    assert infer_dtype(pd.Series(["1", "2", "3", "x"] * 10 + ["4"] * 60)) == DataType.INTEGER
    assert infer_dtype(pd.Series(["1.5", "2"])) == DataType.FLOAT
    assert infer_dtype(pd.Series(["yes", "no", "yes"])) == DataType.BOOLEAN
    assert infer_dtype(pd.Series(["2026-01-01", "2026-02-03 10:00"])) == DataType.DATETIME
    assert infer_dtype(pd.Series(["a", "b"] * 30)) == DataType.CATEGORICAL
    assert infer_dtype(pd.Series([f"free text {i}" for i in range(100)])) == DataType.STRING
    assert infer_dtype(pd.Series([None, None])) == DataType.UNKNOWN


def test_infer_schema_on_orders(orders):
    df, _ = orders
    schema = infer_schema(df, name="orders")
    assert schema.fields["order_id"].unique
    assert schema.primary_key == ["order_id"]
    assert schema.timestamp_column == "timestamp"
    assert schema.fields["unit_price"].dtype == DataType.FLOAT  # despite "unknown" strings
    assert schema.fields["region"].dtype == DataType.CATEGORICAL
    assert set(schema.fields["region"].allowed) == {"north", "south", "east", "west"}
    assert not schema.fields["customer_id"].unique  # repeats, so not an id column
    profs = {p.name: p for p in profile(df, schema)}
    assert profs["unit_price"].invalid > 0
    assert profs["quantity"].max >= 150
