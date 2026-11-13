---
title: Installation
description: Install AnomalyGuard with pip from GitHub, choose extras, set up a development environment with uv, or run the Docker image.
---

AnomalyGuard needs **Python 3.10 or newer**. The core package depends on NumPy, pandas, SciPy, PyYAML and httpx.

## pip (from GitHub)

AnomalyGuard is not on PyPI; pip installs it from GitHub. The commands below install the **v0.3.0** release:

```bash
# library + CLI
pip install "anomalyguard @ git+https://github.com/Manas-thakur/anomalyguard@v0.3.1"

# with the web app, Parquet and SQLAlchemy support
pip install "anomalyguard[server,parquet,sql] @ git+https://github.com/Manas-thakur/anomalyguard@v0.3.1"

# everything
pip install "anomalyguard[all] @ git+https://github.com/Manas-thakur/anomalyguard@v0.3.1"
```

For the latest unreleased code, use `@main` instead of the tag:

```bash
pip install "anomalyguard[server] @ git+https://github.com/Manas-thakur/anomalyguard@main"
```

Each [GitHub Release](https://github.com/Manas-thakur/anomalyguard/releases) also has the sdist and wheel attached, which pip can install directly. Error messages about a missing extra (for example `serve` without the `server` extra) print the matching command for your installed version.

Check the install:

```bash
anomalyguard --version
anomalyguard doctor
```

`python -m anomalyguard` works as well as the `anomalyguard` command.

## Extras

| Extra | Adds | Needed for |
|---|---|---|
| `server` | fastapi, uvicorn, python-multipart | `anomalyguard serve` (web app and REST API, uploads) |
| `parquet` | pyarrow | Parquet sources, sinks and uploads |
| `sql` | sqlalchemy | databases other than SQLite (SQLite works without it) |
| `all` | all of the above | |

`anomalyguard doctor` shows which extras are installed.

## uv

With [uv](https://docs.astral.sh/uv/) you can add AnomalyGuard to a project or run it as a tool:

```bash
uv add "anomalyguard[server] @ git+https://github.com/Manas-thakur/anomalyguard@v0.3.1"

# or run the CLI without adding it to a project
uvx --from "anomalyguard[server] @ git+https://github.com/Manas-thakur/anomalyguard@v0.3.1" anomalyguard serve
```

### Development setup

```bash
git clone https://github.com/Manas-thakur/anomalyguard
cd anomalyguard
uv sync --all-extras          # .venv with dev tools (pytest, ruff) and all extras
uv run anomalyguard --version
```

Inside the clone, prefix commands with `uv run`. See [Contributing](/anomalyguard/docs/contributing/) for tests, linting and the web app build.

## Docker

The image has the CLI with the `server`, `parquet` and `sql` extras. Its working directory is `/data`, state goes to `/data/.anomalyguard`, and the default command starts the web app on port 8765 (`serve --host 0.0.0.0 --port 8765`).

```bash
# the published multi-arch image
docker pull ghcr.io/manas-thakur/anomalyguard

# or build it from a clone
docker build -t anomalyguard .
```

```bash
# web app on http://localhost:8765, state kept on the host
docker run --rm -p 8765:8765 \
  -e ANOMALYGUARD_API_KEY=change-me \
  -v "$PWD/.anomalyguard:/data/.anomalyguard" \
  ghcr.io/manas-thakur/anomalyguard

# the bundled example data
docker run --rm ghcr.io/manas-thakur/anomalyguard detect examples/data/orders.csv --group-by region

# your own pipeline (mounts the current folder as /data)
docker run --rm -v "$PWD:/data" ghcr.io/manas-thakur/anomalyguard run pipeline.yaml
```

The `/data/.anomalyguard` volume holds everything the server writes: the database, uploads, analyses and the pipelines you create in the web app (saved to `/data/.anomalyguard/pipelines`), so they survive a container restart. The release workflow tags images `X.Y.Z`, `X.Y` and `latest`. The container runs as an unprivileged user (uid 1000) and has a health check on `/health`. Mounting your own folder over `/data` hides the bundled `examples/`.

See [Deployment](/anomalyguard/docs/guides/deployment/) for API keys, CORS and reverse proxies.
