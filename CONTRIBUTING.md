# Contributing to AnomalyGuard

Thanks for helping. Bug reports, documentation fixes, new detectors and UI improvements are all welcome. Please open an issue first for larger changes so we can agree on the approach.

## Repository layout

| Path | What it is | Tooling |
|---|---|---|
| `src/anomalyguard/` | The Python package: library, CLI, FastAPI server | Python 3.10+, uv, pytest, ruff |
| `src/anomalyguard/monitor/static/` | The **built** web app (generated, committed) | written by `pnpm build` in `web/` |
| `web/` | Web app source: React 19, TypeScript, Vite, Tailwind CSS v4, shadcn/ui | Node 24, pnpm 10 |
| `site/` | Landing page and documentation: Astro + Starlight | Node 24, pnpm 10 |
| `tests/` | pytest suite; offline (HTTP and SMTP are mocked) | |
| `examples/` | Sample data, pipelines and a schema used by docs and tests | |
| `docs/` | Design notes and the screenshots used by the README and the site | |

## Python

```bash
uv sync --all-extras            # .venv with every extra and the dev tools
uv run pytest -q
uv run ruff check .
uv run ruff format --check .    # `uv run ruff format .` to fix
uv run anomalyguard doctor
```

- Keep algorithms readable and in NumPy; SciPy is used only for distributions and KD-trees.
- Every flag should carry a reason a person can act on.
- New behaviour needs a test. Tests must stay offline and fast.

## Web app

The browser app is a client of the JSON API in `src/anomalyguard/monitor/api.py`.

```bash
uv run anomalyguard serve --port 8765         # in one terminal (any state directory)

cd web
pnpm install
AG_API=http://127.0.0.1:8765 pnpm dev        # Vite dev server with hot reload; proxies /api and /health
```

Before you push:

```bash
pnpm typecheck
pnpm lint
pnpm test          # Vitest: API client, formatters, keyboard reducer
pnpm contrast      # WCAG AA contrast of the design tokens in both themes
pnpm build         # writes src/anomalyguard/monitor/static/
```

**Commit the build output.** `pnpm build` regenerates `src/anomalyguard/monitor/static/` (hashed file names change when the code does). Commit those files with your change: the Python package ships them so `pip install` needs no Node, and CI fails if the committed build differs from a fresh one.

Conventions:

- Components from shadcn/ui live in `web/src/components/ui/` and are ours to edit. Add new ones with the shadcn CLI (`pnpm dlx shadcn@latest add <name>`), then adapt them.
- Colours come from the tokens in `web/src/index.css` (`bg-sev-high-soft`, `text-muted-foreground`, `var(--band)`, ...). Don't hard-code colours; run `pnpm contrast` after changing a token.
- Every page needs loading, empty and error states, must work at 375 px wide, and must be usable from the keyboard.
- Server state goes through the React Query hooks in `web/src/lib/queries.ts`; filters that should survive a reload live in the URL (`useUrlState`).

## Documentation site

```bash
cd site
pnpm install
pnpm dev           # http://localhost:4321/anomalyguard/
pnpm build         # also checks every internal link
```

Docs pages are Markdown in `site/src/content/docs/docs/`. The site copies `docs/screenshots/*.png` and generates the changelog page from `CHANGELOG.md` at build time, so edit those sources rather than the copies. Everything in the docs must match the code: run the commands and snippets you document.

## Screenshots

`docs/screenshots/` holds the images used by the README, the landing page and the web app guide. Capture them from a real `anomalyguard serve` with the sample datasets and both example pipelines, at 1440 px wide (and 375 px for `mobile.png`), and keep each file reasonably small.

## Pull requests

- Keep changes focused, and describe the user-facing effect.
- Add an entry under `## [Unreleased]` in `CHANGELOG.md`.
- Make sure `pytest`, `ruff`, and (for web changes) the `pnpm` checks above pass.

## Releasing (maintainers)

1. Bump the version in `pyproject.toml`, `src/anomalyguard/__init__.py` and `web/package.json`, run `uv lock`, and move the `Unreleased` notes in `CHANGELOG.md` under the new version.
2. Rebuild the web app (`pnpm build` in `web/`) and commit.
3. Tag and push: `git tag vX.Y.Z && git push origin vX.Y.Z`.

The release workflow checks that the tag matches the package version, runs the tests, builds the web app and the sdist and wheel, creates a GitHub Release with the changelog section as notes, and pushes a multi-arch image to `ghcr.io/manas-thakur/anomalyguard`. Publishing to PyPI uses trusted publishing and is enabled by setting the repository variable `PYPI_PUBLISH=true`.

## License

By contributing you agree that your contributions are licensed under the [MIT License](LICENSE).
