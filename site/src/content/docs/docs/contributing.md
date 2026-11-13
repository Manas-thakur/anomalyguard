---
title: Contributing
description: Set up the Python package, the web app and this documentation site for development.
---

The repository has three parts:

| Folder | What | Tooling |
|---|---|---|
| `src/anomalyguard/`, `tests/` | The Python package: library, CLI and server | uv, pytest, ruff |
| `web/` | The web app (React + shadcn/ui), built into `src/anomalyguard/monitor/static/` | Node.js, pnpm, Vite |
| `site/` | This landing page and documentation (Astro + Starlight) | Node.js, pnpm |

Issues and pull requests go to [github.com/Manas-thakur/anomalyguard](https://github.com/Manas-thakur/anomalyguard).

## Python package

```bash
git clone https://github.com/Manas-thakur/anomalyguard
cd anomalyguard
uv sync --all-extras                 # .venv with all extras and the dev tools (pytest, ruff)

uv run pytest -q                     # offline: HTTP and SMTP are mocked
uv run ruff check .
uv run ruff format --check .         # or `uv run ruff format .` to fix
uv run anomalyguard demo benchmark   # if you touched a detector
```

Run anything that writes state (`run`, `serve`, `fix --review-db`) from a scratch folder, or point it at one with `--db`, so `.anomalyguard/` and `out/` do not land in the repository (both are gitignored anyway).

Layout of `src/anomalyguard/`:

```
ingest/      sources (files, SQL, REST, streams), schema inference, checkpoints
schema/      schema registry, validation, type coercion, quality score
detect/      statistical, ml, timeseries, contextual, ensemble detectors; registry, runner, report
remediate/   strategies, policy pipeline, review queue, LLM suggester, report
alert/       rules, notifiers, rate limiter, manager
monitor/     metrics store, feedback loop, FastAPI app, workspace (uploads, analyses), jobs,
             pipeline catalog, incidents, settings, doctor, static/ (the built web app)
pipeline/    YAML config, executor, scheduler, state, sinks, templates
demo/        synthetic data generator and benchmark
api.py       read / profile / detect / fix
cli.py       the anomalyguard command
```

CI runs ruff, pytest and a CLI smoke test on Python 3.10, 3.11 and 3.12, checks that the wheel contains the web app, and builds the Docker image.

## Web app

The web app source is in `web/`. The built files are written to `src/anomalyguard/monitor/static/` and **committed**, so the Python package ships the app and users never need Node.js.

```bash
cd web
pnpm install
pnpm dev          # Vite dev server; proxies /api to a running `anomalyguard serve`
```

Run the API in another terminal (from a scratch folder):

```bash
uv run anomalyguard serve
```

Before committing:

```bash
pnpm typecheck
pnpm lint
pnpm test
pnpm build        # writes into src/anomalyguard/monitor/static; commit the result
```

## Documentation site

This site lives in `site/` and is deployed to GitHub Pages by `.github/workflows/pages.yml` on pushes to `main` that touch `site/`, `docs/` or `CHANGELOG.md`.

```bash
cd site
pnpm install
pnpm dev          # http://localhost:4321/anomalyguard/
pnpm build        # static site in site/dist, then a link check
pnpm preview
```

- Pages are Markdown/MDX in `site/src/content/docs/docs/`; the landing page is `site/src/pages/index.astro`.
- `scripts/sync-assets.mjs` runs before `dev` and `build`. It copies `docs/screenshots/*.png` into `site/public/screenshots/` and generates the Changelog page from `CHANGELOG.md`; both outputs are gitignored, so edit the sources, not the copies.
- The build fails on broken internal links: `starlight-links-validator` checks the docs, and `scripts/check-links.mjs` checks every built page, including the landing page.
- Keep the docs in step with the code: CLI flags, defaults, endpoints and environment variables are documented from the source.

## Releasing

1. Update the version in `pyproject.toml` and `src/anomalyguard/__init__.py`, and move the `Unreleased` notes in `CHANGELOG.md` under the new version.
2. Commit, tag and push: `git tag v0.3.0 && git push origin v0.3.0`.

The release workflow checks that the tag matches the package version, runs lint and tests, builds the sdist and wheel, creates a GitHub Release with both attached (the CHANGELOG section becomes the notes), and pushes a multi-arch image to `ghcr.io/manas-thakur/anomalyguard` tagged `X.Y.Z`, `X.Y` and `latest`. Tags with a hyphen (`v0.4.0-rc1`) become pre-releases and do not move `latest`. Publishing to PyPI is opt-in (trusted publishing, enabled by the `PYPI_PUBLISH` repository variable).
