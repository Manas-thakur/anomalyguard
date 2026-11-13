# AnomalyGuard: CLI + dashboard image.
#   docker build -t anomalyguard .
#   docker run --rm -p 8765:8765 -v "$PWD/.anomalyguard:/data/.anomalyguard" anomalyguard
#   docker run --rm -v "$PWD:/data" anomalyguard detect examples/data/orders.csv
# The /data/.anomalyguard volume keeps everything the server writes: the database,
# uploads, analyses and pipelines created in the web app (/data/.anomalyguard/pipelines).
# /data/pipelines (mount your own YAML there) and the bundled /data/examples are scanned too.
FROM python:3.12-slim

LABEL org.opencontainers.image.title="AnomalyGuard"       org.opencontainers.image.description="Data anomaly detection and remediation with a web app and REST API"       org.opencontainers.image.source="https://github.com/Manas-thakur/anomalyguard"       org.opencontainers.image.licenses="MIT"

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    ANOMALYGUARD_PIPELINE_DIRS=/data/.anomalyguard/pipelines,/data/pipelines,/data/examples

WORKDIR /app
COPY pyproject.toml README.md LICENSE ./
COPY src ./src
RUN pip install ".[server,parquet,sql]" \
    && useradd --create-home --uid 1000 anomalyguard \
    && mkdir -p /data \
    && chown anomalyguard /data

COPY --chown=anomalyguard examples /data/examples

USER anomalyguard
WORKDIR /data
EXPOSE 8765
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8765/health').status == 200 else 1)" || exit 1

ENTRYPOINT ["anomalyguard"]
CMD ["serve", "--host", "0.0.0.0", "--port", "8765"]
