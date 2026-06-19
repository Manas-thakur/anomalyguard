# Part 1: `anomalyguard-ingest` — Data Source Connectors

## Purpose

The ingest layer connects to various data sources — files, databases, streams, APIs — and reads data in a uniform format. It handles connection management, schema inference, incremental reading, and streaming.

## Component Breakdown

### 1.1 `Source` Interface

**File:** `anomalyguard/ingest/source.py`

```python
class Source(ABC):
    """Abstract base class for data sources."""
    
    name: str
    config: SourceConfig
    
    @abstractmethod
    async def connect(self) -> None: ...
    
    @abstractmethod
    async def read(self, batch_size: int = 1000) -> AsyncGenerator[Record, None]: ...
    
    @abstractmethod
    async def schema(self) -> Schema: ...
    
    @abstractmethod
    async def disconnect(self) -> None: ...
    
    @abstractmethod
    async def checkpoint(self) -> Checkpoint: ...
    
    @abstractmethod
    async def seek(self, checkpoint: Checkpoint) -> None: ...

@dataclass
class Record:
    data: dict[str, Any]
    metadata: RecordMetadata  # source, timestamp, offset, etc.

@dataclass
class RecordMetadata:
    source_name: str
    timestamp: datetime
    offset: str | int | None    # For checkpointing
    raw: str | None = None      # Raw line/record before parsing
```

### 1.2 Implementations

**`CSVSource`:**
- Reads CSV/TSV files with configurable delimiter, quote character, encoding
- Handles: header detection, type inference from sample, chunked reading for large files
- Supports: local files, remote URLs (HTTP/S3), compressed files (gz, bz2, zip)

```python
class CSVSource(Source):
    def __init__(
        self,
        path: str,
        delimiter: str = ",",
        has_header: bool = True,
        encoding: str = "utf-8",
        chunk_size: int = 10000,
        compression: str | None = None,  # "gzip", "bz2", "zip"
    ):
        ...
```

**`JSONSource`:**
- Reads JSON, JSONL (JSON Lines), NDJSON formats
- Handles: nested JSON flattening (optional), array vs object-per-line
- Supports: local files, remote URLs, streaming JSON arrays

```python
class JSONSource(Source):
    def __init__(
        self,
        path: str,
        format: Literal["json", "jsonl", "ndjson"] = "jsonl",
        flatten: bool = False,
        array_path: str | None = None,  # JSONPath to array in JSON file
    ):
        ...
```

**`DatabaseSource`:**
- Connects to any SQLAlchemy-supported database
- Executes configurable queries with incremental reading via ORDER BY + LIMIT/OFFSET or WHERE timestamp > last_checkpoint
- Supports: PostgreSQL, MySQL, SQLite, MSSQL, Oracle

```python
class DatabaseSource(Source):
    def __init__(
        self,
        connection_string: str,
        query: str,          # SELECT * FROM table WHERE id > :last_id ORDER BY id
        incremental_column: str | None = "id",  # Column for incremental reads
        batch_size: int = 1000,
    ):
        ...
```

**`KafkaSource`:**
- Consumes from Kafka topics
- Handles: consumer groups, offset management, deserialization (JSON, Avro, Protobuf)
- Supports: SSL/SASL authentication, multiple partitions

```python
class KafkaSource(Source):
    def __init__(
        self,
        bootstrap_servers: str,
        topic: str,
        group_id: str = "anomalyguard",
        deserializer: str = "json",  # "json", "avro", "raw"
    ):
        ...
```

**`RESTAPISource`:**
- Polls a REST API endpoint periodically
- Handles: pagination (cursor, page number, offset), authentication (API key, OAuth), rate limiting

```python
class RESTAPISource(Source):
    def __init__(
        self,
        url: str,
        method: str = "GET",
        headers: dict | None = None,
        auth: AuthConfig | None = None,
        pagination: PaginationConfig | None = None,
        poll_interval_seconds: float = 60.0,
    ):
        ...
```

### 1.3 Schema Inference

**File:** `anomalyguard/ingest/schema_inference.py`

Automatically detect data types, constraints, and statistical properties from a sample of records.

```python
@dataclass
class InferredField:
    name: str
    dtype: InferredType       # integer, float, string, boolean, datetime, categorical, unknown
    nullable: bool
    sample_values: list[Any]  # Representative samples
    stats: FieldStats         # Statistical profile
    constraints: list[Constraint]

@dataclass
class FieldStats:
    count: int
    null_count: int
    unique_count: int
    min: Any | None
    max: Any | None
    mean: float | None
    median: float | None
    std: float | None
    percentiles: dict[int, Any] | None  # {25: ..., 50: ..., 75: ..., 90: ..., 95: ..., 99: ...}
    histogram: list[tuple[float, float]] | None  # [(bin_start, count), ...]

class SchemaInferenceEngine:
    def __init__(self, sample_size: int = 1000):
        self.sample_size = sample_size
    
    def infer(self, records: list[Record]) -> Schema:
        """Infer schema from a sample of records."""
        ...
    
    def infer_field(self, name: str, values: list[Any]) -> InferredField:
        """Infer type, stats, and constraints for a single field."""
        # Type detection logic:
        # 1. Try int → all values are int-compatible
        # 2. Try float → all values are float-compatible
        # 3. Try datetime → all values parse as known datetime formats
        # 4. Try boolean → values are in {true, false, 0, 1, yes, no, ...}
        # 5. Check cardinality → if unique values < threshold, mark as categorical
        # 6. Fallback to string
        ...
```

**Blog Content Angle:** "Building a Schema Inference Engine: Type Detection, Statistics, and Constraints from Raw Data"

### 1.4 Incremental Reading

**File:** `anomalyguard/ingest/incremental.py`

```python
@dataclass
class Checkpoint:
    source_name: str
    offset: str | int          # Last read position
    timestamp: datetime
    record_count: int          # Total records read so far
    metadata: dict

class IncrementalReader:
    """Wraps a Source to support incremental reads with checkpointing."""
    
    def __init__(self, source: Source, checkpoint_store: CheckpointStore):
        self.source = source
        self.checkpoint_store = checkpoint_store
    
    async def read_new(self) -> AsyncGenerator[Record, None]:
        """Read only records after the last checkpoint."""
        last_checkpoint = await self.checkpoint_store.get(self.source.name)
        if last_checkpoint:
            await self.source.seek(last_checkpoint)
        
        async for batch in self.source.read():
            yield batch
            await self.checkpoint_store.save(Checkpoint(
                source_name=self.source.name,
                offset=self.source.current_offset(),
                timestamp=datetime.utcnow(),
                record_count=batch_count,
            ))
```

---

## File Structure

```
packages/python/ingest/
├── __init__.py
├── source.py                 # Source ABC, Record, RecordMetadata, SourceConfig
├── sources/
│   ├── __init__.py
│   ├── csv_source.py         # CSVSource
│   ├── json_source.py        # JSONSource
│   ├── database_source.py    # DatabaseSource
│   ├── kafka_source.py       # KafkaSource
│   ├── rest_source.py        # RESTAPISource
│   └── file_watch.py         # FileWatchSource
├── schema_inference.py       # SchemaInferenceEngine, InferredField, FieldStats
├── incremental.py            # IncrementalReader, Checkpoint, CheckpointStore
└── errors.py                 # ConnectionError, ParseError, SchemaInferenceError
```
