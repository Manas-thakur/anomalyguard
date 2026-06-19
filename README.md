# AnomalyGuard — Intelligent Data Anomaly Detection & Remediation System

## Philosophy

Most AI systems fail not because of bad models, but because of bad data. AnomalyGuard is a modular, pipeline-based system for detecting and fixing data anomalies in real-time streams. Every component is built from scratch: statistical anomaly detection, ML-based detection, remediation strategies, alerting, and monitoring.

The goal: build a system that continuously monitors data quality, automatically fixes common issues, alerts humans when needed, and improves over time through a feedback loop.

## Why This Matters

Data quality is the #1 cause of production AI failures:
- **Garbage in, garbage out** — Anomaly detection models are only as good as the data they train on
- **Silent failures** — Model accuracy degrades gradually as data drifts, and no one notices until too late
- **Manual data cleaning** — Data scientists spend 60-80% of their time cleaning data, not building models

AnomalyGuard automates the data quality monitoring and cleaning pipeline, catching issues before they reach your AI models.

## Architecture

```
Data Sources (CSV, DB, Stream, API)
    │
    ▼
┌─────────────────────┐
│      Ingest         │  Connectors, schema inference, incremental reading
└──────────┬──────────┘
           │
           ▼
┌─────────────────────┐
│      Schema         │  Validation, constraints, quality metrics
└──────────┬──────────┘
           │
           ▼
┌─────────────────────┐
│      Detect         │  Statistical + ML + contextual anomaly detection
└──────────┬──────────┘
           │
           ▼
┌─────────────────────┐
│     Remediate       │  Auto-fix: impute, cap, transform, flag for human
└──────────┬──────────┘
           │
           ▼
┌─────────────────────┐
│      Alert          │  Notifications: console, file, Slack, email
└──────────┬──────────┘
           │
           ▼
┌─────────────────────┐
│     Monitor         │  Metrics, dashboard, feedback loop
└─────────────────────┘
```

## Tech Stack

| Layer | Technology |
|-------|-----------|
| **Core** | Python 3.11+ (uv) |
| **CLI / Dashboard** | TypeScript, Node 20+ (pnpm) |
| **Storage** | SQLite (local), PostgreSQL (cloud) |
| **Anomaly Detection** | NumPy, SciPy, Scikit-learn (local), custom implementations |
| **LLM for Remediation** | Ollama on RTX 4060 (Llama 3.1 8B / Qwen 2.5 7B) |
| **Dashboard** | React + lightweight-charts |
| **CI/CD** | GitHub Actions |

## Monorepo Structure

```
anomalyguard/
├── packages/
│   ├── python/
│   │   ├── ingest/         # Connectors: CSV, JSON, DB, Kafka, REST
│   │   ├── schema/         # Schema validation, type inference, constraint detection
│   │   ├── detect/         # Anomaly detection algorithms (statistical + ML)
│   │   ├── remediate/      # Auto-fix strategies: impute, cap, transform, flag
│   │   ├── alert/          # Notifications: console, file, email, Slack
│   │   ├── monitor/        # Metrics, dashboards, health tracking
│   │   └── pipeline/       # Pipeline orchestration, scheduling, persistence
│   └── typescript/
│       ├── cli/            # CLI tool
│       └── dashboard/      # React dashboard
├── apps/
│   └── demo/               # Demo: synthetic + real-world datasets, benchmark
├── docs/                   # Astro + MDX blog
└── .github/workflows/      # CI
```

## Blog Content Roadmap

| Phase | Posts |
|-------|-------|
| Foundations | "Data Quality: The Most Important AI Skill Nobody Talks About", "Building a Schema Inference Engine from Scratch" |
| Detection | "Anomaly Detection Algorithms: From Z-Score to Isolation Forest", "Contextual Anomaly Detection: Why Context Matters", "Ensemble Detection: Combining Multiple Algorithms for Better Results" |
| Remediation | "Auto-Fixing Bad Data: Imputation, Capping, and Transformation Strategies", "When to Fix vs When to Flag: Building Remediation Pipelines" |
| Production | "Real-Time Data Quality Monitoring: Architecture and Implementation", "Building a Feedback Loop for Continuous Improvement" |
