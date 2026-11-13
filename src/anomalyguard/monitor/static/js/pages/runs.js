// Runs: filterable list and a run detail page.

import { api } from "../api.js";
import { barList } from "../charts.js";
import { incidentList } from "../incidents.js";
import {
  busy, button, chip, clear, tabBar, debounce, emptyState, errorState, fmtInt, fmtMs, fmtNum, fmtPct,
  fmtTime, fmtValue, h, isAnalysis, kpis, loading, pageHead, pager, panel, runLabel, select,
  segmented, setTitle, timeEl, toast,
} from "../ui.js";
import { add } from "../ui.js";
import { currentRoute, setQuery } from "../app.js";

export function render(root, params) {
  if (params.id) return renderRun(root, params.id);
  return renderList(root);
}

// ---------------------------------------------------------------- list
function renderList(root) {
  setTitle("Runs");
  const q = currentRoute().query;
  const state = { kind: q.kind || "", status: q.status || "", pipeline: q.pipeline || "", q: q.q || "", offset: Number(q.offset) || 0, limit: Number(q.limit) || 25 };
  const tableSlot = h("div", null, loading(6));
  const pipeSel = select([{ value: "", label: "All sources" }], { value: state.pipeline, label: "Source", onChange: (v) => { state.pipeline = v; state.offset = 0; load(); } });
  const statusSel = select([{ value: "", label: "Any status" }, "success", "failed", "empty", "running"].map((o) => (typeof o === "string" ? { value: o, label: o } : o)), { value: state.status, label: "Status", onChange: (v) => { state.status = v; state.offset = 0; load(); } });
  const search = h("input", { class: "input search", type: "search", placeholder: "Search source, run id or error", value: state.q, "aria-label": "Search runs" });
  search.addEventListener("input", debounce(() => { state.q = search.value.trim(); state.offset = 0; load(); }, 300));

  root.append(
    pageHead({ title: "Runs", lede: "Every pipeline run and every analysis, newest first." }),
    h("section", { class: "panel" },
      h("div", { class: "panel-body" }, h("div", { class: "filters", role: "toolbar", "aria-label": "Run filters" },
        segmented([{ value: "", label: "All" }, { value: "pipeline", label: "Pipelines" }, { value: "analysis", label: "Analyses" }], state.kind, (v) => { state.kind = v; state.offset = 0; load(); }, "Run type"),
        pipeSel, statusSel, search)),
      tableSlot));

  api.get("/api/summary").then((s) => {
    for (const p of s.pipelines) pipeSel.append(h("option", { value: p, selected: p === state.pipeline }, isAnalysis(p) ? `${runLabel(p)} (analysis)` : p));
  }).catch(() => {});

  async function load() {
    setQuery({ kind: state.kind, status: state.status, pipeline: state.pipeline, q: state.q, offset: state.offset || "", limit: state.limit === 25 ? "" : state.limit });
    tableSlot.setAttribute("aria-busy", "true");
    try {
      const { items, total } = await api.list("/api/runs", { limit: state.limit, offset: state.offset, kind: state.kind, status: state.status, pipeline: state.pipeline, q: state.q });
      if (!total) {
        add(clear(tableSlot), state.kind || state.status || state.pipeline || state.q
          ? emptyState({ title: "No runs match these filters" })
          : emptyState({ title: "No runs yet", text: "Analyses and pipeline runs are recorded here.", actions: [h("a", { class: "btn primary", href: "#/analyze" }, "Analyze a file"), h("a", { class: "btn", href: "#/pipelines" }, "Run a pipeline")] }));
        return;
      }
      add(clear(tableSlot), 
        h("div", { class: "table-wrap" }, h("table", { class: "data" },
          h("thead", null, h("tr", null, ["Run", "Source", "Type", "Status", "Rows", "Anomalous", "Rate", "Quality", "Fixed", "Flagged", "Alerts", "Duration", "Started"].map((t, i) => h("th", { class: i >= 4 && i <= 11 ? "r" : null }, t)))),
          h("tbody", null, items.map((r) => h("tr", { class: "clickable", onClick: () => { location.hash = `#/runs/${r.id}`; } },
            h("td", null, h("a", { href: `#/runs/${r.id}` }, `#${r.id}`)),
            h("td", { class: "truncate", style: { maxWidth: "240px" }, title: r.error || runLabel(r.pipeline) }, runLabel(r.pipeline)),
            h("td", { class: "muted" }, isAnalysis(r.pipeline) ? "analysis" : "pipeline"),
            h("td", null, chip(r.status)),
            h("td", { class: "r" }, fmtInt(r.rows)),
            h("td", { class: "r" }, fmtInt(r.n_anomalies)),
            h("td", { class: "r" }, fmtPct(r.anomaly_rate)),
            h("td", { class: "r" }, r.quality_score === null ? "-" : fmtPct(r.quality_score)),
            h("td", { class: "r" }, fmtInt(r.cells_changed)),
            h("td", { class: "r" }, fmtInt(r.flagged_for_review)),
            h("td", { class: "r" }, fmtInt(r.alerts_sent)),
            h("td", { class: "r" }, fmtMs(r.duration_ms)),
            h("td", { class: "nowrap" }, timeEl(r.started_at))))))),
        pager({ offset: state.offset, limit: state.limit, total, noun: "runs", onChange: (o, l) => { state.offset = o; state.limit = l; load(); } }));
    } catch (err) {
      add(clear(tableSlot), errorState(err, load));
    } finally {
      tableSlot.removeAttribute("aria-busy");
    }
  }
  load();
}

// ---------------------------------------------------------------- detail
function renderRun(root, runId) {
  setTitle(`Run #${runId}`);
  const body = h("div", { class: "stack" }, loading(6));
  root.append(body);

  async function load() {
    try {
      const run = await api.get(`/api/runs/${runId}`);
      draw(run);
    } catch (err) {
      add(clear(body), err.status === 404
        ? emptyState({ title: `Run #${runId} does not exist`, actions: [h("a", { class: "btn", href: "#/runs" }, "All runs")] })
        : errorState(err, load));
    }
  }

  function draw(run) {
    const m = run.metrics || {};
    const bd = run.breakdown;
    const analysisId = m.analysis_id;
    const rem = m.remediation;
    const q = currentRoute().query;
    const actions = [];
    if (analysisId) actions.push(h("a", { class: "btn", href: `#/analyze/a/${analysisId}` }, "Open in Analyze"));
    if (run.review) actions.push(h("a", { class: "btn", href: `#/review?run=${run.id}&status=all` }, `Review items (${fmtInt(run.review)})`));
    setTitle(`${runLabel(run.pipeline)} · run #${run.id}`);

    const tabDefs = [
      { id: "incidents", label: "Incidents" },
      { id: "findings", label: `Findings (${fmtInt(bd.findings)})` },
      { id: "details", label: "Remediation & outputs" },
    ];
    const state = { tab: tabDefs.some((t) => t.id === q.tab) ? q.tab : "incidents" };
    const panels = {};
    let table = null;
    const tabs = tabBar(tabDefs, state.tab, (id) => { state.tab = id; show(); });
    const countBadge = h("span", { class: "tab-count" });
    tabs.buttons.incidents.append(countBadge);

    const incidents = incidentList(run.id, {
      focus: q.incident || null,
      onCount: (n) => { countBadge.textContent = n ? String(n) : ""; countBadge.hidden = !n; },
      onFilter: (column) => { state.tab = "findings"; tabs.select("findings"); show(); table.filter("column", column, true); },
    });
    panels.incidents = h("div", { class: "stack" }, incidents.el);
    table = anomalyTable(run);
    panels.findings = h("div", { class: "stack" },
      h("div", { class: "grid grid-2" },
        panel({ title: "Findings by column", sub: `${fmtInt(bd.findings)} stored findings on ${fmtInt(bd.rows)} rows`, body: barList(Object.entries(bd.by_column).map(([k, v]) => ({ label: k, value: v, onClick: () => table.filter("column", k) })), { format: fmtInt, empty: "No findings stored for this run." }) }),
        panel({ title: "Findings by detector", sub: severityLine(bd.by_severity), body: barList(Object.entries(bd.by_detector).map(([k, v]) => ({ label: k, value: v, onClick: () => table.filter("detector", k) })), { format: fmtInt, empty: "No findings stored for this run." }) })),
      table.el);
    panels.details = h("div", { class: "stack" },
      h("div", { class: "grid grid-2" },
        panel({ title: "Remediation", body: remediationSummary(run, rem) }),
        panel({ title: "Alerts sent", body: alertsList(run.alerts), flush: true })),
      panel({ title: "Artifacts", sub: "Outputs written by this run", body: artifactList(run) }));
    const content = h("div", { role: "tabpanel", "aria-labelledby": "" });

    function show() {
      setQuery({ tab: state.tab === "incidents" ? "" : state.tab });
      content.setAttribute("aria-labelledby", `tab-${state.tab}`);
      content.replaceChildren(panels[state.tab]);
    }

    add(clear(body),
      pageHead({
        title: `${runLabel(run.pipeline)} · run #${run.id}`,
        crumbs: [{ label: "Runs", href: "#/runs" }, { label: `#${run.id}` }],
        lede: `${run.kind === "analysis" ? "Analysis" : "Pipeline run"} started ${fmtTime(run.started_at)}, took ${fmtMs(run.duration_ms)}.${m.source ? ` Source: ${m.source.split(/[\\/]/).pop()}` : ""}`,
        actions,
      }),
      run.error ? h("div", { class: "notice error", role: "alert" }, h("div", null, h("strong", null, "Run failed. "), run.error)) : null,
      kpis([
        { label: "Status", value: chip(run.status) },
        { label: "Rows", value: fmtInt(run.rows) },
        { label: "Anomalous rows", value: fmtInt(run.n_anomalies), sub: fmtPct(run.anomaly_rate) },
        { label: "Quality", value: run.quality_score === null ? "-" : fmtPct(run.quality_score), sub: run.validity !== null && run.validity !== undefined ? `validity ${fmtPct(run.validity)}` : null },
        { label: "Fixed / flagged", value: `${fmtInt(run.cells_changed)} / ${fmtInt(run.flagged_for_review)}`, sub: `${fmtInt(run.rows_dropped)} rows dropped` },
        { label: "Alerts", value: fmtInt(run.alerts_sent), alert: run.alerts_sent > 0 },
      ], { compact: true }),
      tabs.el,
      content,
    );
    show();
  }

  load();
}

function severityLine(sev) {
  if (!sev) return null;
  return `high ${fmtInt(sev.high)} · medium ${fmtInt(sev.medium)} · low ${fmtInt(sev.low)}`;
}

function remediationSummary(run, rem) {
  if (!rem && !run.cells_changed && !run.rows_dropped && !run.flagged_for_review) {
    return emptyState({ title: "No remediation", text: run.kind === "analysis" ? "Open the analysis and use Fix & export to preview fixes." : "This pipeline has remediation turned off, or nothing needed fixing." });
  }
  const rows = [
    ["Cells changed", fmtInt(run.cells_changed)],
    ["Rows dropped", fmtInt(run.rows_dropped)],
    ["Rows flagged", fmtInt(run.flagged_for_review)],
  ];
  if (rem) {
    rows.push(["Rows in / out", `${fmtInt(rem.rows_in)} / ${fmtInt(rem.rows_out)}`]);
    for (const [k, v] of Object.entries(rem.changes_by_strategy || {})) rows.push([`by ${k}`, fmtInt(v)]);
  }
  return h("dl", { class: "kv" }, rows.flatMap(([k, v]) => [h("dt", null, k), h("dd", { class: "num" }, v)]));
}

function alertsList(alerts) {
  if (!alerts || !alerts.length) return emptyState({ title: "No alerts", text: "No alert rule fired for this run." });
  return h("ul", { class: "list" }, alerts.map((a) => h("li", null,
    h("div", { class: "grow" }, h("div", { class: "row" }, chip(a.severity || "info"), h("strong", null, a.title)),
      h("div", { class: "small muted" }, `${a.status || ""} · ${a.channels || "no channels"} · `, timeEl(a.created_at))))));
}

function artifactList(run) {
  if (!run.artifacts.length) return h("p", { class: "muted small" }, run.kind === "analysis" ? "Preview fixes in Analyze to create the cleaned file and reports." : "This pipeline has no sink configured, or its outputs were moved.");
  return h("div", { class: "row" }, run.artifacts.map((name) => {
    const b = button(name, { icon: "download" });
    b.addEventListener("click", () => busy(b, async () => {
      try { await api.download(`/api/runs/${run.id}/artifacts/${encodeURIComponent(name)}`); } catch (err) { toast(err.message, { kind: "error" }); }
    }));
    return b;
  }));
}

function anomalyTable(run) {
  const state = { offset: 0, limit: 25, sort: "score", order: "desc", column: "", detector: "", severity: "" };
  const slot = h("div", null, loading(5));
  const bd = run.breakdown;
  const colSel = select([{ value: "", label: "All columns" }, ...Object.keys(bd.by_column).map((c) => ({ value: c, label: c }))], { value: "", label: "Column", onChange: (v) => { state.column = v; state.offset = 0; load(); } });
  const detSel = select([{ value: "", label: "All detectors" }, ...Object.keys(bd.by_detector).map((c) => ({ value: c, label: c }))], { value: "", label: "Detector", onChange: (v) => { state.detector = v; state.offset = 0; load(); } });
  const sevSel = select([{ value: "", label: "Any severity" }, { value: "high", label: "High" }, { value: "medium", label: "Medium" }, { value: "low", label: "Low" }], { value: "", label: "Severity", onChange: (v) => { state.severity = v; state.offset = 0; load(); } });

  function header(label, key, right) {
    if (!key) return h("th", { class: right ? "r" : null }, label);
    const active = state.sort === key;
    const b = h("button", { class: "sort", type: "button", "aria-sort": active ? (state.order === "asc" ? "ascending" : "descending") : null }, label);
    b.addEventListener("click", () => {
      if (state.sort === key) state.order = state.order === "asc" ? "desc" : "asc";
      else { state.sort = key; state.order = key === "score" ? "desc" : "asc"; }
      state.offset = 0;
      load();
    });
    return h("th", { class: right ? "r" : null, "aria-sort": active ? (state.order === "asc" ? "ascending" : "descending") : null }, b);
  }

  async function load() {
    slot.setAttribute("aria-busy", "true");
    try {
      const { items, total } = await api.list(`/api/runs/${run.id}/anomalies`, { offset: state.offset, limit: state.limit, sort: state.sort, order: state.order, column: state.column, detector: state.detector, severity: state.severity });
      if (!total) { add(clear(slot), emptyState({ title: "No findings", text: state.column || state.detector || state.severity ? "Nothing matches these filters." : "This run stored no findings." })); return; }
      add(clear(slot), 
        h("div", { class: "table-wrap" }, h("table", { class: "data" },
          h("thead", null, h("tr", null, header("Score", "score", true), header("Row", "row"), header("Column", "column"), header("Detector", "detector"), h("th", null, "Value"), h("th", null, "Reason"), h("th", null, "Feedback"))),
          h("tbody", null, items.map((a) => {
            const fp = button("False positive", { small: true });
            const tp = button("Confirm", { small: true, kind: "ghost" });
            const send = (label, btn) => busy(btn, async () => {
              try {
                await api.post("/api/feedback", { anomaly_id: a.id, label });
                fp.disabled = true; tp.disabled = true;
                btn.textContent = label === "false_positive" ? "Marked" : "Confirmed";
              } catch (err) { toast(err.message, { kind: "error" }); }
            });
            fp.addEventListener("click", () => send("false_positive", fp));
            tp.addEventListener("click", () => send("true_positive", tp));
            return h("tr", null,
              h("td", { class: "r" }, h("span", { class: "row", style: { justifyContent: "flex-end", flexWrap: "nowrap" } }, chip(a.severity), h("span", { class: "num" }, fmtNum(a.score, 3)))),
              h("td", { class: "mono" }, String(a.row_index)),
              h("td", { class: "mono" }, a.column || "(row)"),
              h("td", { class: "mono small nowrap" }, a.detector),
              h("td", { class: "value-cell" }, fmtValue(a.value)),
              h("td", { class: "reason" }, h("span", { class: "text", title: a.reason }, a.reason)),
              h("td", null, h("div", { class: "row", style: { flexWrap: "nowrap" } }, fp, tp)));
          })))),
        pager({ offset: state.offset, limit: state.limit, total, noun: "findings", onChange: (o, l) => { state.offset = o; state.limit = l; load(); } }));
    } catch (err) {
      add(clear(slot), errorState(err, load));
    } finally {
      slot.removeAttribute("aria-busy");
    }
  }
  load();
  const el = h("section", { class: "panel", id: "anomalies" },
    h("div", { class: "panel-head" }, h("div", null, h("h2", null, "Anomalies"), h("p", null, "Sort by any underlined header. Feedback adjusts detector thresholds when you tune them in Settings."))),
    h("div", { class: "panel-body" }, h("div", { class: "filters" }, colSel, detSel, sevSel)),
    slot);
  return {
    el,
    filter(key, value, force = false) {
      state[key] = state[key] === value && !force ? "" : value;
      state.offset = 0;
      if (key === "column") colSel.value = state.column;
      if (key === "detector") detSel.value = state.detector;
      load();
      el.scrollIntoView({ behavior: "smooth", block: "start" });
    },
  };
}
