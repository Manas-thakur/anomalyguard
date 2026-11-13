// Shapes returned by the AnomalyGuard JSON API (src/anomalyguard/monitor/api.py).

export type Severity = "high" | "medium" | "low";
export type RunStatus = "success" | "failed" | "empty" | "running" | string;

export interface RunRow {
  id: number;
  pipeline: string;
  started_at: string;
  finished_at: string | null;
  status: RunStatus;
  error: string | null;
  rows: number;
  n_anomalies: number;
  anomaly_rate: number;
  quality_score: number | null;
  completeness: number | null;
  validity: number | null;
  uniqueness: number | null;
  freshness: number | null;
  cells_changed: number;
  rows_dropped: number;
  flagged_for_review: number;
  alerts_sent: number;
  duration_ms: number | null;
  detectors: Record<string, number>;
}

export interface Breakdown {
  by_column: Record<string, number>;
  by_detector: Record<string, number>;
  by_severity: Partial<Record<Severity, number>>;
  findings: number;
  rows: number;
}

export interface AlertRow {
  id: number;
  run_id: number;
  created_at: string;
  severity: string;
  title: string;
  status: string;
  channels: string;
  pipeline: string;
}

export interface RemediationSummary {
  rows_in: number;
  rows_out: number;
  rows_dropped: number;
  cells_changed: number;
  rows_flagged_for_review: number;
  changes_by_strategy: Record<string, number>;
  changes_by_column: Record<string, number>;
  drop_reasons: Record<string, number>;
}

export interface RunDetail extends RunRow {
  metrics: Record<string, unknown> & {
    analysis_id?: string;
    dataset_id?: string;
    source?: string;
    remediation?: RemediationSummary;
  };
  breakdown: Breakdown;
  alerts: AlertRow[];
  artifacts: string[];
  kind: "analysis" | "pipeline";
  review: number;
}

export interface Finding {
  id: number;
  run_id: number;
  row_index: number | string;
  detector: string;
  score: number;
  value: unknown;
  reason: string;
  column: string | null;
  severity: Severity;
}

export interface IncidentSample {
  id: number;
  row_index: number | string;
  value: unknown;
  score: number;
  detector: string;
  reason: string;
}

export type IncidentKind =
  | "outlier"
  | "pattern"
  | "level_shift"
  | "missing"
  | "duplicates"
  | "invalid"
  | "multivariate";

export interface Incident {
  run_id: number;
  pipeline: string;
  started_at: string;
  id: string;
  kind: IncidentKind;
  column: string | null;
  severity: Severity;
  score: number;
  n_findings: number;
  n_rows: number;
  detectors: string[];
  sample: IncidentSample[];
  expected: { low: number | null; high: number | null; center: number | null; text: string; basis?: string } | null;
  actual: { value: unknown; row?: number | string | null; at?: string; text: string } | null;
  delta_pct: number | null;
  direction?: string;
  title: string;
  explanation: string;
  grouped?: string[];
  chart: "distribution" | "series" | "history" | null;
  entity: string;
  status: "open" | "normal" | "confirmed";
  triaged_at: string | null;
  muted_until: string | null;
  mute_id: number | null;
}

export interface RunIncidents {
  run_id: number;
  incidents: Incident[];
  muted: number;
  open: number;
}

export interface DistributionChart {
  type: "distribution";
  column: string;
  domain: [number, number];
  edges: number[];
  counts: number[];
  below: number;
  above: number;
  min: number;
  max: number;
  n: number;
  band: { low: number | null; high: number | null; center: number | null };
  marks: { v: number; row: number | string; score: number }[];
}

export interface SeriesChart {
  type: "series";
  column: string;
  time: string | null;
  x: (string | number)[];
  y: (number | null)[];
  expected: (number | null)[];
  low: (number | null)[];
  high: (number | null)[];
  flagged: number[];
  period?: number;
  focus?: [number, number] | null;
}

export interface HistoryChart {
  type: "history";
  label: string;
  points: { t: string; v: number; run_id: number }[];
  band: { low: number; high: number };
  current: number;
}

export type IncidentChart = DistributionChart | SeriesChart | HistoryChart | { type: null };

export interface HealthSource {
  pipeline: string;
  name: string;
  kind: "analysis" | "pipeline";
  status: "failing" | "degraded" | "warning" | "healthy";
  last_run: { id: number; status: string; started_at: string; rows: number; error: string | null };
  latest_success: number | null;
  quality: number | null;
  quality_series: { run_id: number; t: string; v: number }[];
  trend: number | null;
  anomaly_rate: number | null;
  rows: number | null;
  open_incidents: number;
  high_incidents: number;
  muted: number;
  runs: number;
}

export interface HealthOverview {
  sources: HealthSource[];
  kpis: {
    open_incidents: number;
    high_incidents: number;
    monitored: number;
    unhealthy: number;
    avg_quality: number | null;
    rows_scanned: number;
    runs: number;
  };
}

export interface SeriesPoint {
  id: number;
  pipeline: string;
  started_at: string;
  status: string;
  rows: number;
  n_anomalies: number;
  anomaly_rate: number;
  quality_score: number | null;
}

export interface Summary {
  runs: number;
  failed_runs: number;
  rows_processed: number;
  anomalies_found: number;
  avg_quality_score: number | null;
  alerts_sent: number;
  pipelines: string[];
  last_run: RunRow | null;
  review: ReviewCounts;
  analyses: number;
  datasets: number;
  jobs_active: number;
}

export interface ReviewCounts {
  pending: number;
  approved: number;
  rejected: number;
  applied: number;
}

export interface Dataset {
  id: string;
  name: string;
  file: string;
  size: number;
  rows: number;
  columns: string[];
  created_at: string;
}

export interface ColumnProfile {
  name: string;
  dtype: string;
  count: number;
  nulls: number;
  null_pct: number;
  unique: number;
  mean: number | null;
  std: number | null;
  min: number | string | null;
  median: number | null;
  max: number | string | null;
  invalid: number;
  top_values: [string, number][];
  numeric: boolean;
  histogram: { edges: number[]; counts: number[]; below?: number; above?: number } | null;
}

export interface QualityScores {
  score: number;
  completeness: number;
  validity: number;
  uniqueness: number;
  freshness: number | null;
  null_counts: Record<string, number>;
  duplicate_rows: number;
  invalid_rows: number;
  newest_timestamp: string | null;
}

export interface DatasetProfile {
  dataset: Dataset;
  quality: QualityScores;
  columns: ColumnProfile[];
  validation: { passed: boolean; invalid_rows: number; by_rule: Record<string, number> };
  suggestions: { numeric_columns: string[]; group_by: string[]; time_columns: string[] };
}

export interface Detector {
  name: string;
  category: string;
  class: string;
  description: string;
}

export interface AnalysisOptions {
  detectors: string[];
  group_by: string | null;
  time_column: string | null;
  columns: string[] | null;
  sensitivity: "low" | "medium" | "high";
  combine: "any" | "vote" | "all";
  min_votes?: number;
}

export interface RemediationPolicy {
  default: { missing?: string; outlier?: string; invalid?: string };
  columns: Record<string, { missing?: string; outlier?: string }>;
  dedupe?: boolean;
}

export interface RemediationResult {
  summary: RemediationSummary;
  column_stats: Record<string, { before: Record<string, number | null>; after: Record<string, number | null> }>;
  n_changes: number;
  n_flagged: number;
  policy: RemediationPolicy;
  created_at: string;
}

export interface Analysis {
  id: string;
  dataset_id: string;
  dataset: string;
  options: AnalysisOptions;
  status: "queued" | "running" | "success" | "failed";
  error?: string | null;
  created_at: string;
  run_id: number | null;
  summary?: {
    rows: number;
    columns: number;
    n_anomalies: number;
    anomaly_rate: number;
    n_findings: number;
    anomalies_by_detector: Record<string, number>;
    anomalies_by_column: Record<string, number>;
  };
  remediation?: RemediationResult | null;
  artifacts?: string[];
  breakdown?: Breakdown;
}

export interface CellFinding {
  id: number;
  detector: string;
  score: number;
  reason: string;
  severity: Severity;
}

export interface AnalysisRows {
  columns: string[];
  total: number;
  offset: number;
  limit: number;
  rows: {
    index: number | string;
    values: Record<string, unknown>;
    cells: Record<string, CellFinding[]>;
    row_findings: CellFinding[];
    score: number;
  }[];
}

export interface Change {
  index: number | string;
  column: string;
  before: unknown;
  after: unknown;
  strategy: string;
  reason: string;
  confidence?: number;
}

export interface Job {
  id: string;
  kind: "analysis" | "pipeline" | string;
  label: string;
  status: "queued" | "running" | "success" | "failed" | "interrupted";
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
  progress: number;
  message: string | null;
  error: string | null;
  params: Record<string, unknown>;
  result: Record<string, unknown> | null;
}

export interface ReviewItem {
  id: number;
  created_at: string;
  pipeline: string | null;
  run_id: number | null;
  row_index: number | string | null;
  value: unknown;
  reason: string;
  suggestion: unknown;
  suggestion_confidence: number | null;
  status: "pending" | "approved" | "rejected" | "applied";
  resolved_value: unknown;
  reviewer_note: string | null;
  resolved_at: string | null;
  detector: string | null;
  applied_at: string | null;
  column: string | null;
}

export interface ReviewFacets {
  counts: ReviewCounts;
  pipelines: { value: string; count: number }[];
  columns: { value: string; count: number }[];
  detectors: { value: string; count: number }[];
}

export interface ReviewDetail {
  item: ReviewItem;
  row: Record<string, unknown> | null;
  findings: Finding[];
  run: { id: number; pipeline: string; started_at: string; status: string } | null;
}

export interface BulkResult {
  action: string;
  matched: number;
  updated: number;
  skipped: number;
  applied: number;
  not_applicable: number;
  review: ReviewCounts;
}

export interface Pipeline {
  id: string;
  file: string;
  path: string;
  dir: string;
  valid: boolean;
  error: string | null;
  name: string | null;
  description: string | null;
  source: string | null;
  detectors: string[] | null;
  remediation: boolean | null;
  schedule: Record<string, unknown> | null;
  interval_seconds: number | null;
  notifiers: string[] | null;
  last_run: RunRow | null;
  runs: number;
}

export interface PipelineDetail extends Pipeline {
  yaml: string;
  recent_runs: RunRow[];
  jobs: Job[];
}

export interface PipelineList {
  dirs: { path: string; exists: boolean }[];
  write_dir: string;
  pipelines: Pipeline[];
}

export interface PipelineTemplate {
  name: string;
  description: string;
  fields: string[];
  defaults: Record<string, string>;
}

export interface Threshold {
  detector: string;
  multiplier: number;
  reason: string | null;
  updated_at: string;
}

export interface Precision {
  true_positive: number;
  false_positive: number;
  precision: number | null;
}

export interface Settings {
  version: string;
  server: {
    auth_enabled: boolean;
    cors_origins: string[];
    max_upload_mb: number;
    pipeline_dirs: string[];
    workers: number;
  };
  state: {
    state_dir: string;
    db: string;
    exists: boolean;
    writable: boolean;
    db_exists: boolean;
    runs: number;
    review_pending: number;
    uploads: number;
  };
  extras: Record<string, { installed: boolean; missing: string[] }>;
  env: { name: string; set: boolean; value: string | null; purpose: string }[];
  notifiers: {
    pipeline: string;
    file: string;
    error?: string;
    notifiers?: { type: string; min_severity?: string; ok: boolean; detail: string }[];
  }[];
  thresholds: Threshold[];
  precision: Record<string, Precision>;
  cwd: string;
}
