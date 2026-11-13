// Health: KPI strip, one row per monitored source (status, quality trend, open
// incidents, last run) and a feed of recent incidents.

import { api } from "../api.js";
import { sparkline } from "../bandcharts.js";
import { colorFor, lineChart, MAX_SERIES } from "../charts.js";
import {
  add, clear, emptyState, errorState, fmtAgo, fmtInt, fmtPct, h, icon, kpis, loading, pageHead,
  panel, runLabel, segmented, setTitle, timeEl,
} from "../ui.js";
import { currentRoute, setQuery } from "../app.js";

const STATUS = {
  failing: "Last run failed",
  degraded: "High-severity incident or quality below 90%",
  warning: "Open incidents",
  healthy: "No open incidents",
};

function statusDot(status) {
  return h("span", { class: ["health-dot", status], title: STATUS[status] }, h("span", { class: "sr-only" }, status));
}

function trendCell(trend) {
  if (trend === null || trend === undefined) return h("span", { class: "muted" }, "-");
  const pts = trend * 100;
  if (Math.abs(pts) < 0.05) return h("span", { class: "trend flat", title: "No change since the previous run" }, icon("flat"), "0.0");
  const up = pts > 0;
  return h("span", { class: ["trend", up ? "up" : "down"], title: `Quality ${up ? "up" : "down"} ${Math.abs(pts).toFixed(1)} points since the previous run` },
    icon(up ? "up" : "down"), `${up ? "+" : "−"}${Math.abs(pts).toFixed(1)}`);
}

export function render(root) {
  setTitle("Health");
  const q = currentRoute().query;
  const state = { metric: q.metric === "anomaly_rate" ? "anomaly_rate" : "quality_score" };
  const kpiSlot = h("div", null, loading(2));
  const tableSlot = h("div", null, loading(5));
  const feedSlot = h("div", null, loading(4));
  const trendSlot = h("div", null, loading(4));
  const cleanups = [];

  root.append(
    pageHead({
      title: "Health",
      lede: "Every monitored pipeline and analysed file: is it healthy, what changed, and what needs a decision.",
      actions: [
        h("a", { class: "btn", href: "#/pipelines" }, "Run a pipeline"),
        h("a", { class: "btn primary", href: "#/analyze" }, icon("upload"), "Analyze a file"),
      ],
    }),
    kpiSlot,
    h("div", { class: "grid grid-wide-narrow" },
      h("div", { class: "stack" },
        panel({ title: "Sources", sub: "Latest successful run of each source. Click a row to open it.", body: tableSlot, flush: true }),
        panel({
          title: "Trends",
          actions: [segmented([{ value: "quality_score", label: "Quality" }, { value: "anomaly_rate", label: "Anomaly rate" }], state.metric, (v) => { state.metric = v; setQuery({ metric: v === "quality_score" ? "" : v }); loadTrend(); }, "Metric")],
          body: trendSlot,
        })),
      panel({ title: "Recent incidents", actions: [h("a", { href: "#/runs", class: "small" }, "All runs")], body: feedSlot, flush: true })),
  );

  async function loadHealth() {
    try {
      const data = await api.get("/api/health/overview");
      const k = data.kpis;
      add(clear(kpiSlot), kpis([
        { label: "Open incidents", value: fmtInt(k.open_incidents), sub: k.high_incidents ? `${fmtInt(k.high_incidents)} high severity` : "none high", alert: k.high_incidents > 0 },
        { label: "Sources monitored", value: fmtInt(k.monitored), sub: k.unhealthy ? `${fmtInt(k.unhealthy)} need attention` : `${fmtInt(k.runs)} runs` },
        { label: "Avg quality", value: k.avg_quality === null ? "-" : fmtPct(k.avg_quality), sub: "latest run of each source" },
        { label: "Rows scanned", value: fmtInt(k.rows_scanned), sub: "all successful runs" },
      ]));
      if (!data.sources.length) {
        add(clear(tableSlot), emptyState({
          title: "Nothing monitored yet",
          text: "Analyze a file or run a pipeline; each one shows up here with its quality trend and open incidents.",
          actions: [h("a", { class: "btn primary", href: "#/analyze" }, "Analyze a file"), h("a", { class: "btn", href: "#/pipelines" }, "See pipelines")],
        }));
        return;
      }
      add(clear(tableSlot), h("div", { class: "table-wrap" }, h("table", { class: "data health" },
        h("caption", { class: "sr-only" }, "Monitored sources"),
        h("thead", null, h("tr", null,
          h("th", null, "Source"), h("th", null, "Quality"), h("th", { class: "r hide-sm" }, "Trend"),
          h("th", { class: "r" }, "Open"), h("th", { class: "hide-sm" }, "Last run"))),
        h("tbody", null, data.sources.map((src) => {
          const target = src.latest_success || src.last_run.id;
          const tr = h("tr", { class: "clickable", onClick: (e) => { if (!e.target.closest("a")) location.hash = `#/runs/${target}`; } },
            h("td", null, h("div", { class: "src" }, statusDot(src.status),
              h("div", { style: { minWidth: "0" } },
                h("a", { href: `#/runs/${target}`, class: "name" }, src.name),
                h("div", { class: "meta" }, src.kind === "analysis" ? "analysis" : "pipeline", ` · ${fmtInt(src.runs)} ${src.runs === 1 ? "run" : "runs"}`)))),
            h("td", null, h("div", { class: "q" }, sparkline(src.quality_series, { label: `Quality over the last ${src.quality_series.length} runs` }),
              h("span", { class: "num" }, src.quality === null ? "-" : fmtPct(src.quality)))),
            h("td", { class: "r hide-sm" }, trendCell(src.trend)),
            h("td", { class: "r" }, src.open_incidents
              ? h("span", { class: ["open-count", src.high_incidents && "high"] }, fmtInt(src.open_incidents))
              : h("span", { class: "muted" }, "0")),
            h("td", { class: "nowrap hide-sm" }, h("span", { class: ["run-status", src.last_run.status] }, src.last_run.status === "success" ? "" : `${src.last_run.status} · `), timeEl(src.last_run.started_at)));
          return tr;
        })))));
    } catch (err) {
      add(clear(kpiSlot), errorState(err, loadHealth));
      clear(tableSlot);
    }
  }

  async function loadFeed() {
    try {
      const items = await api.get("/api/incidents", { limit: 12 });
      if (!items.length) {
        add(clear(feedSlot), emptyState({ title: "No incidents", text: "Incidents from your latest runs appear here." }));
        return;
      }
      add(clear(feedSlot), h("ul", { class: "feed" }, items.map((i) => h("li", { class: ["feed-item", i.status !== "open" && "is-triaged"] },
        h("span", { class: ["sev-dot", i.severity], title: `${i.severity} severity`, "aria-hidden": "true" }),
        h("a", { class: "grow", href: `#/runs/${i.run_id}?incident=${i.id}` },
          h("span", { class: "title" }, i.title, i.status !== "open" ? h("span", { class: "tag" }, i.status === "normal" ? "normal" : "confirmed") : null),
          h("span", { class: "meta" }, [i.column ? i.entity.slice(0, -(i.column.length + 1)) : i.entity, i.column, fmtAgo(i.started_at)].filter(Boolean).join(" · ")))))));
    } catch (err) {
      add(clear(feedSlot), errorState(err, loadFeed));
    }
  }

  async function loadTrend() {
    try {
      const { series } = await api.get("/api/metrics/series");
      const keys = series.map((x) => x.pipeline).sort();
      const shown = series.slice().sort((a, b) => b.points.length - a.points.length).slice(0, MAX_SERIES).sort((a, b) => a.pipeline.localeCompare(b.pipeline));
      const isQ = state.metric === "quality_score";
      while (cleanups.length) cleanups.pop()();
      cleanups.push(lineChart(trendSlot, shown.map((sr) => ({
        key: sr.pipeline,
        label: runLabel(sr.pipeline),
        color: colorFor(sr.pipeline, keys),
        points: sr.points.filter((p) => p.status !== "failed").map((p) => ({ t: p.started_at, v: p[state.metric], meta: `run #${p.id} · ${fmtInt(p.rows)} rows`, id: p.id })),
      })), isQ
        ? { yFormat: (v) => fmtPct(v, 0), yMax: 1, yFloor: 0, yMin: 0.8, height: 200, label: "Quality score over time", emptyText: "No finished runs yet.", onPointClick: (p) => { location.hash = `#/runs/${p.id}`; } }
        : { yFormat: (v) => fmtPct(v, v < 0.1 ? 1 : 0), height: 200, label: "Anomaly rate over time", emptyText: "No finished runs yet.", onPointClick: (p) => { location.hash = `#/runs/${p.id}`; } }));
    } catch (err) {
      add(clear(trendSlot), errorState(err, loadTrend));
    }
  }

  const reload = () => { loadHealth(); loadFeed(); loadTrend(); };
  reload();
  window.addEventListener("ag:data-changed", reload);
  return () => {
    window.removeEventListener("ag:data-changed", reload);
    while (cleanups.length) cleanups.pop()();
  };
}
