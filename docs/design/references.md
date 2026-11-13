# Design references

The web app borrows interaction patterns from three data and issue tools. We
took the patterns, not the look: no logos, colours, type or assets were copied.
AnomalyGuard keeps its own cobalt accent, Inter and JetBrains Mono (self-hosted),
and its own chart design.

## 0. The component kit (0.3.0)

**Choice.** React 19 + TypeScript, built with Vite, styled with Tailwind CSS v4 and
[shadcn/ui](https://ui.shadcn.com) components (Radix primitives underneath). Charts
use shadcn's chart wrapper around Recharts; tables use shadcn's data-table pattern
on TanStack Table. A few [AI Elements](https://ui.shadcn.com/docs/ai-elements)
patterns (Task, Queue, Shimmer and Confirmation) show work in progress: the
analysis job's steps, the background-job queue in the header, and the inline
confirmation before flagged values go to review or approved values are written
into cleaned data. The source is in `web/`; the build is committed into
`src/anomalyguard/monitor/static/` so the Python package still runs without Node.

**Why this kit.**

- **The UX needed components we were hand-rolling badly.** The 0.2 app had its
  own dialog, popover, combobox, tab, toast and drawer code. Radix gives these with
  correct focus management, keyboard support and ARIA roles (dialog, listbox,
  tablist, menu), which is where most of the remaining accessibility bugs were.
- **shadcn/ui is code we own, not a dependency we style around.** Components are
  copied into `web/src/components/ui/` and edited freely (the command dialog
  forwards a custom fuzzy filter; the checkbox shows an indeterminate state; the
  sidebar inset is not a second `<main>`). There is no theme layer to fight, and
  the design tokens are plain CSS variables in `web/src/index.css`.
- **Tailwind v4 tokens map one-to-one onto the old design tokens** (one accent,
  severity hues, band and anomaly colours), so the visual system carried over and
  both themes are defined in one place.
- **Recharts through the shadcn chart container** themes charts with the same CSS
  variables, gives tooltips and responsive sizing, and was enough for every chart
  we draw: the distribution with its expected band and overflow lane, the series
  band chart with its "around the anomaly" window, run-history bars, sparklines
  and the trend chart.
- **TanStack Table** is headless, so server-side paging, sorting and filters (which
  the API already had) plug in without a client-side data model.
- **Vite** builds in about a second and emits content-hashed assets that FastAPI
  serves under `/static/` with long-lived caching; every other GET path returns
  the app so client-side routes can be bookmarked.

**Not adopted.** A component library with its own theme (MUI, Ant, Mantine): heavier,
and the look is theirs. Next.js: the app is a single-page client of an existing
API, so server rendering would add a Node runtime for nothing. A chart library
with canvas rendering: our charts are small, and SVG keeps them accessible and
crisp in screenshots.

## 1. Metaplane: incident view

**What we saw.** An incident opens with a status tag in plain language ("Metric
higher than expected"), the entity, and a one-line explanation ("Freshness is
later than expected"). Expected and actual values sit side by side with a percent
difference. The chart shades the expected range and the actual series breaks
out of it, with the anomalous point in red. Triage buttons (mark as normal, mark
as anomaly, mute) sit on the card, and lineage follows below.

**What AnomalyGuard adopted.**

- **Incidents instead of findings.** A run can store thousands of findings, so
  `GET /api/runs/{id}/incidents` groups them by source, column and kind (outlier,
  pattern, level shift, unusual combination, missing values, duplicates, schema
  violations). Run detail and analysis results open on these cards, most severe
  first. The cell-level table moves to a *Data* / *Findings* tab.
- **Plain-language tags and one sentence.** Each tag says what happened, for example
  "Values higher than expected", "Missing values spiked", "Duplicate rows" or
  "Level shift detected". The sentence gives the count, the most extreme value
  and the range it was compared with. It also says when a value is unusual only
  within its group (for example `group_by: region`), so a red mark inside the band
  is not a surprise.
- **Expected vs actual with the change.** For a column, *expected* is a robust
  band: the median ± 3.5 × 1.4826 × MAD, the same cut-off the MAD detector uses.
  For a time series it is trend + seasonality ± the same band of the residual.
  For a level shift it is the level before the shift. The change is measured from
  the nearest band edge, so "+46% above range" means past the band, not past the
  median.
- **A band chart on every card that has one.** Tabular columns get a histogram
  with the band shaded, flagged values marked on a strip below it, and values far
  outside collected in an overflow lane, so a single 3,000 does not flatten the
  chart. Time series get a line with a shaded band, the expected line dashed, and
  flagged readings in red. The view opens on a window around the anomaly, with a
  toggle to the full history. Missing values, duplicates and schema violations get
  a short run-history chart.
- **Inline triage wired into what already existed.** *Mark as normal* records
  every finding as a false positive, so the existing feedback loop raises the
  detector's threshold, and it rejects matching review items. *Confirm* records
  true positives and sends the flagged cells to the review queue, suggesting the
  value capped to the band when that makes sense. *Mute 24h* is stored per source,
  column and kind, so the next run of the same feed stays quiet too. Muted
  incidents are hidden behind a "Show muted" toggle.
- **Not adopted:** lineage. AnomalyGuard has no lineage graph to show, and a fake
  one would be worse than none.

## 2. Monte Carlo and Metaplane: health table

**What we saw.** An overview table of monitored tables with a health indicator, a
small trend line, open incidents, last update and a direction arrow, over a
handful of totals.

**What AnomalyGuard adopted.**

- **Health replaces Overview.** A KPI strip shows open incidents (with the high
  ones called out), sources monitored, average quality of each source's latest
  run, and rows scanned.
- **One row per source**, whether it is a pipeline or an analysed file. Each row
  has a status dot (failing, degraded, warning or healthy, with the reason in a
  tooltip and in text for screen readers), a quality sparkline over recent runs,
  a trend arrow showing the change in points since the previous run, the open
  incident count and the last run time. The whole row opens the latest run.
- **A recent-incidents feed** in the style of an activity list: a title in normal
  contrast and one low-contrast line of metadata
  (`orders_quality · unit_price · 3 min ago`). Clicking an item opens the run and
  scrolls to that incident.
- **Why:** the old overview put multi-series charts first. These answered "how
  are things trending" but not "what needs me now". The charts are still there,
  in a *Trends* panel under the table.

## 3. Linear: triage inbox and app shell

**What we saw.** A list on the left and the open item on the right. The keyboard
drives everything (j/k, single-key actions, x to select, Shift+click for ranges),
a bulk bar appears while items are selected, Cmd/Ctrl+K opens a command palette,
and a compact sidebar groups pages under small section headers.

**What AnomalyGuard adopted.**

- **The review queue became a split-pane inbox.** Server-side paging, the status,
  source, column and detector filters, search and the bulk API are unchanged.
  `j`/`k` (or the arrow keys) move, `a` approves, `r` rejects, `m` marks as normal
  (false positive), `e` jumps to the final-value field (Enter approves), and `x`
  selects. Shift+click selects a range and Esc clears the selection. With a
  selection, `a`, `r` and `m` act on all of it through the bulk bar, which also
  offers "Select all N matching". After a decision the cursor stays in place, so
  the next item comes up. On a phone the list is full width and the item opens as
  a bottom sheet.
- **App shell.** Ctrl/Cmd+K opens a palette that can go to any page, analyze
  either sample dataset in one step, run any valid pipeline, open a run by
  number, create a pipeline and switch the theme. `?` lists the shortcuts, and
  `g` followed by a letter jumps between pages. The sidebar groups pages under
  *Monitor*, *Triage* and *Configure*.
- **A calmer visual system.** One accent. Hairline borders, with elevation kept
  for things that float (palette, toasts, sheets). Inter for text, JetBrains Mono for data.
  Spacing on a 4/8 px grid. Motion is 200 ms or less and is cut almost entirely
  under `prefers-reduced-motion`.
- **Not adopted:** issue states, assignees and cycles. AnomalyGuard's review items
  have one owner (whoever runs the server) and four states.

## Accessibility and colour

Every text and chart token was checked for WCAG contrast in both themes: text is
at least 4.5:1, and chart marks, the focus ring and status dots are at least
3:1 (`web/scripts/contrast.mjs` recomputes this from `web/src/index.css`). The flagged-value colour also passes against the shaded band. Identity is
never carried by colour alone: tags carry text, status dots have text
alternatives, charts have legends and a text summary for screen readers, and
values far outside a chart's range are listed as text in its overflow lane. Focus is always visible, and the tab bars,
palette and inbox follow the usual ARIA patterns (tablist, combobox + listbox,
listbox with `aria-activedescendant`).
