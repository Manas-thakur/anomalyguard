import { api } from "../api.js";
import { colorFor, lineChart, MAX_SERIES } from "../charts.js";
import {
  chip, clear, emptyState, errorState, fmtInt, fmtMs, fmtPct, h, kpis, loading, pageHead,
  panel, runLabel, segmented, setTitle, timeEl,
} from "../ui.js";
import { add } from "../ui.js";
import { currentRoute, setQuery } from "../app.js";

const RANGES = [
  { value: "1", label: "24 h" },
  { value: "7", label: "7 days" },
  { value: "30", label: "30 days" },
  { value: "all", label: "All" },
];
const KINDS = [
  { value: "", label: "All runs" },
  { value: "pipeline", label: "Pipelines" },
  { value: "analysis", label: "Analyses" },
];

export function render(root) {
  setTitle("Overview");
  const q = currentRoute().query;
  const state = { range: q.range || "all", kind: q.kind || "" };
  const cleanups = [];
  const kpiSlot = h("div", null, loading(2));
  const rateSlot = h("div", null, loading(4));
  const qualitySlot = h("div", null, loading(4));
  const alertsSlot = h("div", null, loading(3));
  const runsSlot = h("div", null, loading(3));

  root.append(
    pageHead({
      title: "Overview",
      lede: "Data quality across every pipeline run and ad-hoc analysis.",
      actions: [
        h("a", { class: "btn", href: "#/pipelines" }, "Run a pipeline"),
        h("a", { class: "btn primary", href: "#/analyze" }, "Analyze a file"),
      ],
    }),
    kpiSlot,
    h("div", { class: "filters", role: "toolbar", "aria-label": "Chart filters" },
      segmented(RANGES, state.range, (v) => { state.range = v; sync(); loadSeries(); }, "Time range"),
      segmented(KINDS, state.kind, (v) => { state.kind = v; sync(); loadSeries(); }, "Run type")),
    h("div", { class: "grid grid-2" },
      panel({ title: "Anomaly rate", sub: "Share of rows flagged per run", body: rateSlot }),
      panel({ title: "Quality score", sub: "Completeness, validity, uniqueness and freshness combined", body: qualitySlot })),
    h("div", { class: "grid grid-wide-narrow" },
      panel({ title: "Recent runs", actions: [h("a", { href: "#/runs", class: "small" }, "All runs")], body: runsSlot, flush: true }),
      panel({ title: "Recent alerts", body: alertsSlot, flush: true })),
  );

  function sync() { setQuery({ range: state.range === "all" ? "" : state.range, kind: state.kind }); }

  async function loadSummary() {
    try {
      const s = await api.get("/api/summary");
      add(clear(kpiSlot), kpis([
        { label: "Runs", value: fmtInt(s.runs + s.failed_runs), sub: `${fmtInt(s.analyses)} ${s.analyses === 1 ? "analysis" : "analyses"}` },
        { label: "Rows scanned", value: fmtInt(s.rows_processed) },
        { label: "Anomalies", value: fmtInt(s.anomalies_found), sub: s.rows_processed ? `${fmtPct(s.anomalies_found / s.rows_processed)} of rows` : null },
        { label: "Avg quality", value: s.avg_quality_score === null ? "-" : fmtPct(s.avg_quality_score) },
        { label: "Pending review", value: fmtInt(s.review.pending), sub: h("a", { href: "#/review" }, "Open queue") },
        { label: "Failed runs", value: fmtInt(s.failed_runs), alert: s.failed_runs > 0, sub: s.failed_runs ? h("a", { href: "#/runs?status=failed" }, "Show") : null },
      ]));
      if (!s.runs && !s.failed_runs) {
        add(clear(runsSlot), emptyState({
          title: "No runs yet",
          text: "Upload a CSV, JSON or Parquet file to profile it and find anomalies, or run one of the example pipelines.",
          actions: [h("a", { class: "btn primary", href: "#/analyze" }, "Analyze a file"), h("a", { class: "btn", href: "#/pipelines" }, "See pipelines")],
        }));
      }
      return s;
    } catch (err) {
      add(clear(kpiSlot), errorState(err, loadSummary));
      return null;
    }
  }

  async function loadSeries() {
    add(clear(rateSlot), loading(4));
    add(clear(qualitySlot), loading(4));
    try {
      const params = { kind: state.kind || undefined, days: state.range === "all" ? undefined : state.range };
      const { series } = await api.get("/api/metrics/series", params);
      const keys = series.map((s) => s.pipeline).sort();
      const shown = series
        .slice()
        .sort((a, b) => b.points.length - a.points.length)
        .slice(0, MAX_SERIES)
        .sort((a, b) => a.pipeline.localeCompare(b.pipeline));
      const extra = series.length - shown.length;
      const build = (field) => shown.map((sr) => ({
        key: sr.pipeline,
        label: runLabel(sr.pipeline) + (sr.pipeline.startsWith("analysis:") ? " (analysis)" : ""),
        color: colorFor(sr.pipeline, keys),
        points: sr.points.filter((p) => p.status !== "failed").map((p) => ({
          t: p.started_at, v: p[field], meta: `run #${p.id} · ${fmtInt(p.rows)} rows`, id: p.id,
        })),
      }));
      const goRun = (p) => { location.hash = `#/runs/${p.id}`; };
      while (cleanups.length) cleanups.pop()();
      cleanups.push(lineChart(rateSlot, build("anomaly_rate"), { yFormat: (v) => fmtPct(v, v < 0.1 ? 1 : 0), label: "Anomaly rate over time", emptyText: "No finished runs in this range.", onPointClick: goRun }));
      cleanups.push(lineChart(qualitySlot, build("quality_score"), { yFormat: (v) => fmtPct(v, 0), yMax: 1, yFloor: 0, yMin: 0.8, label: "Quality score over time", emptyText: "No finished runs in this range.", onPointClick: goRun }));
      if (extra > 0) rateSlot.append(h("p", { class: "muted small" }, `${extra} more series hidden; pick a run type to narrow it down.`));
    } catch (err) {
      add(clear(rateSlot), errorState(err, loadSeries));
      clear(qualitySlot);
    }
  }

  async function loadAlerts() {
    try {
      const alerts = await api.get("/api/alerts", { limit: 8 });
      if (!alerts.length) {
        add(clear(alertsSlot), emptyState({ title: "No alerts", text: "Alert rules in a pipeline fire here when a run crosses a threshold." }));
        return;
      }
      add(clear(alertsSlot), h("ul", { class: "list" }, alerts.map((a) => h("li", null,
        h("div", { class: "grow" },
          h("div", { class: "row" }, chip(a.severity || "info"), h("span", { class: "small muted" }, a.pipeline ? runLabel(a.pipeline) : "")),
          h("div", { style: { marginTop: "4px", color: "var(--color-ink)" } }, a.title),
          h("div", { class: "small muted" }, timeEl(a.created_at), a.channels ? ` · ${a.channels}` : "", ` · ${a.status || ""}`)),
        a.run_id ? h("a", { class: "small nowrap", href: `#/runs/${a.run_id}` }, `Run #${a.run_id}`) : null))));
    } catch (err) {
      add(clear(alertsSlot), errorState(err, loadAlerts));
    }
  }

  async function loadRuns() {
    try {
      const { items } = await api.list("/api/runs", { limit: 6 });
      if (!items.length) return;
      add(clear(runsSlot), h("div", { class: "table-wrap" }, h("table", { class: "data" },
        h("thead", null, h("tr", null, ["Run", "Source", "Status", "Rows", "Anomaly rate", "Quality", "Duration", "Started"].map((t, i) => h("th", { class: i >= 3 && i <= 6 ? "r" : null }, t)))),
        h("tbody", null, items.map((r) => {
          const tr = h("tr", { class: "clickable", onClick: () => { location.hash = `#/runs/${r.id}`; } },
            h("td", null, h("a", { href: `#/runs/${r.id}` }, `#${r.id}`)),
            h("td", { class: "truncate", style: { maxWidth: "220px" } }, runLabel(r.pipeline), r.pipeline.startsWith("analysis:") ? h("span", { class: "muted small" }, " · analysis") : null),
            h("td", null, chip(r.status)),
            h("td", { class: "r" }, fmtInt(r.rows)),
            h("td", { class: "r" }, fmtPct(r.anomaly_rate)),
            h("td", { class: "r" }, r.quality_score === null ? "-" : fmtPct(r.quality_score)),
            h("td", { class: "r" }, fmtMs(r.duration_ms)),
            h("td", { class: "nowrap" }, timeEl(r.started_at)));
          return tr;
        })))));
    } catch (err) {
      add(clear(runsSlot), errorState(err, loadRuns));
    }
  }

  loadSummary().then(() => loadRuns());
  loadSeries();
  loadAlerts();
  return () => { while (cleanups.length) cleanups.pop()(); };
}
