// Analyze: upload -> profile -> choose detectors -> results -> remediation + export.

import { api, waitForJob } from "../api.js";
import { barList, histogram } from "../charts.js";
import { incidentList } from "../incidents.js";
import {
  busy, button, chip, clear, closePopover, emptyState, errorState, fmtBytes, fmtInt, fmtNum,
  fmtPct, fmtValue, h, icon, kpis, loading, pageHead, pager, panel, popover, segmented, select,
  setTitle, tabBar, timeEl, toast,
} from "../ui.js";
import { add } from "../ui.js";
import { currentRoute, refreshBadge, setQuery } from "../app.js";

const STEP_NAMES = ["Upload", "Profile", "Detect", "Results", "Fix & export"];
const ACCEPT = ".csv,.tsv,.json,.jsonl,.ndjson,.parquet,.pq,.gz";
const OUTLIER = ["cap", "winsorize", "median", "mean", "null", "flag", "drop", "keep"];
const MISSING = ["auto", "median", "mean", "mode", "ffill", "bfill", "interpolate", "flag", "drop", "keep"];
const INVALID = ["coerce", "flag", "drop", "keep"];
const STRATEGY_HELP = {
  cap: "clip to robust fences (median ± 3.5 MAD); values it cannot move go to review",
  winsorize: "clip to the 1st and 99th percentiles",
  median: "replace with the column median",
  mean: "replace with the column mean",
  null: "blank the value",
  flag: "leave the value, send it to the review queue",
  drop: "drop the whole row",
  keep: "do nothing",
};

function steps(current, links = {}) {
  return h("ol", { class: "steps", "aria-label": "Analysis steps" }, STEP_NAMES.map((name, i) => {
    const n = i + 1;
    const cls = n < current ? "done" : n === current ? "current" : "";
    const label = h("span", null, name);
    return h("li", { class: cls, "aria-current": n === current ? "step" : null }, links[n] ? h("a", { href: links[n] }, label) : label);
  }));
}

export function render(root, params) {
  if (params.kind === "d") return renderDataset(root, params.id);
  if (params.kind === "a") return renderAnalysis(root, params.id);
  return renderUpload(root);
}

// ---------------------------------------------------------------- 1. upload
function renderUpload(root) {
  setTitle("Analyze");
  const input = h("input", { type: "file", accept: ACCEPT, hidden: true });
  const status = h("div", { class: "stack", "aria-live": "polite" });
  const zone = h("div", { class: "dropzone", tabindex: "0", role: "button", "aria-label": "Upload a data file" },
    icon("upload", "icon"),
    h("div", { class: "big" }, "Drop a data file here"),
    h("p", { class: "muted" }, "or click to choose one. The file is stored on this server under the state directory, profiled, and kept until you delete it."),
    h("div", { class: "formats" }, ["CSV", "TSV", "JSON", "JSONL", "Parquet", ".gz"].map((f) => chip(f, "plain"))));
  zone.addEventListener("click", () => input.click());
  zone.addEventListener("keydown", (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); input.click(); } });
  zone.addEventListener("dragover", (e) => { e.preventDefault(); zone.classList.add("is-over"); });
  zone.addEventListener("dragleave", () => zone.classList.remove("is-over"));
  zone.addEventListener("drop", (e) => {
    e.preventDefault();
    zone.classList.remove("is-over");
    if (e.dataTransfer.files.length) start(e.dataTransfer.files[0]);
  });
  input.addEventListener("change", () => { if (input.files.length) start(input.files[0]); });

  async function start(file) {
    const bar = h("span", { style: { transform: "scaleX(0)" } });
    add(clear(status), h("div", { class: "panel panel-body stack" },
      h("div", { class: "row spread" }, h("strong", null, file.name), h("span", { class: "muted small" }, fmtBytes(file.size))),
      h("div", { class: "progress", role: "progressbar", "aria-label": "Upload progress" }, bar),
      h("span", { class: "muted small", id: "upload-msg" }, "Uploading")));
    try {
      const meta = await api.upload(file, (f) => { bar.style.transform = `scaleX(${f})`; });
      bar.style.transform = "scaleX(1)";
      location.hash = `#/analyze/d/${meta.id}`;
    } catch (err) {
      add(clear(status), h("div", { class: "notice error", role: "alert" }, h("div", null, h("strong", null, "Upload failed. "), err.message)));
    } finally {
      input.value = "";
    }
  }

  async function useSample(kind, btn) {
    btn.disabled = true;
    add(clear(status), h("div", { class: "panel panel-body muted small", "aria-live": "polite" }, "Generating sample data…"));
    try {
      const meta = await api.post("/api/datasets/sample", { kind });
      location.hash = `#/analyze/d/${meta.id}`;
    } catch (err) {
      add(clear(status), h("div", { class: "notice error", role: "alert" }, h("div", null, h("strong", null, "Could not create the sample. "), err.message)));
    } finally {
      btn.disabled = false;
    }
  }
  const sampleBtn = (kind, label, hint) => {
    const b = button(label, { small: true, icon: "file", title: hint });
    b.addEventListener("click", () => useSample(kind, b));
    return b;
  };
  const samples = h("div", { class: "row sample-row" },
    h("span", { class: "muted small" }, "No file handy? Try a sample with known anomalies:"),
    sampleBtn("orders", "Orders · 1,000 rows", "E-commerce orders with price, quantity, delivery and data-entry anomalies"),
    sampleBtn("sensor", "Sensor readings · 1,440 rows", "Hourly sensor readings with spikes, a level shift and seasonal drift"));

  const recent = h("div", null, loading(3));
  root.append(
    pageHead({ title: "Analyze a file", lede: "Profile a dataset, find anomalies with a reason for each one, preview fixes and export the cleaned file." }),
    steps(1),
    zone, samples, input, status,
    panel({ title: "Uploaded datasets", body: recent, flush: true }),
  );

  async function loadRecent() {
    try {
      const [datasets, analyses] = await Promise.all([api.get("/api/datasets"), api.get("/api/analyses", { limit: 200 })]);
      if (!datasets.length) {
        add(clear(recent), emptyState({ title: "No uploads yet", text: "Drop a file above, or start with one of the sample datasets to see how detection and fixes work." }));
        return;
      }
      const latest = {};
      for (const a of analyses) if (!latest[a.dataset_id]) latest[a.dataset_id] = a;
      add(clear(recent), h("div", { class: "table-wrap" }, h("table", { class: "data" },
        h("thead", null, h("tr", null, ["File", "Rows", "Columns", "Size", "Uploaded", "Latest analysis", ""].map((t, i) => h("th", { class: i > 0 && i < 4 ? "r" : null }, t)))),
        h("tbody", null, datasets.map((d) => {
          const a = latest[d.id];
          const del = button("", { small: true, kind: "ghost", icon: "trash", title: `Delete ${d.name}` });
          del.classList.add("icon-only");
          del.setAttribute("aria-label", `Delete ${d.name}`);
          del.addEventListener("click", async (e) => {
            e.stopPropagation();
            await busy(del, async () => {
              try { await api.del(`/api/datasets/${d.id}`); toast(`Deleted ${d.name}`); loadRecent(); } catch (err) { toast(err.message, { kind: "error" }); }
            });
          });
          return h("tr", { class: "clickable", onClick: () => { location.hash = `#/analyze/d/${d.id}`; } },
            h("td", null, h("a", { href: `#/analyze/d/${d.id}` }, d.name)),
            h("td", { class: "r" }, fmtInt(d.rows)),
            h("td", { class: "r" }, fmtInt(d.columns.length)),
            h("td", { class: "r" }, fmtBytes(d.size)),
            h("td", { class: "nowrap" }, timeEl(d.created_at)),
            h("td", null, a ? h("a", { href: `#/analyze/a/${a.id}`, onClick: (e) => e.stopPropagation() }, a.summary ? `${fmtInt(a.summary.n_anomalies)} anomalous rows` : a.status) : h("span", { class: "muted" }, "none")),
            h("td", { class: "r" }, del));
        })))));
    } catch (err) {
      add(clear(recent), errorState(err, loadRecent));
    }
  }
  loadRecent();
}

// ---------------------------------------------------------------- 2-3. profile + detector setup
function renderDataset(root, datasetId) {
  setTitle("Profile");
  const body = h("div", { class: "stack" }, loading(5));
  root.append(body);
  let aborted = false;

  async function load() {
    try {
      const [prof, detectors] = await Promise.all([
        api.get(`/api/datasets/${datasetId}/profile`),
        api.get("/api/detectors"),
      ]);
      if (aborted) return;
      draw(prof, detectors);
    } catch (err) {
      add(clear(body), errorState(err, load));
    }
  }

  function draw(prof, detectors) {
    const ds = prof.dataset;
    const q = prof.quality;
    setTitle(`Profile ${ds.name}`);
    clear(body);
    const config = configPanel(prof, detectors);
    // The detector setup sits beside the column cards on wide screens but below
    // all of them on narrow ones, so give the next step a visible entry point.
    const next = button("Set up detection", { kind: "primary", icon: "right" });
    next.addEventListener("click", () => {
      config.scrollIntoView({ behavior: "smooth", block: "start" });
      const run = [...config.querySelectorAll("button")].find((b) => b.textContent.trim() === "Run analysis");
      if (run) setTimeout(() => run.focus({ preventScroll: true }), 400);
    });
    body.append(
      pageHead({
        title: ds.name,
        crumbs: [{ label: "Analyze", href: "#/analyze" }, { label: "Profile" }],
        lede: `${fmtInt(ds.rows)} rows · ${ds.columns.length} columns · ${fmtBytes(ds.size)} · uploaded ${new Date(ds.created_at).toLocaleString()}`,
        actions: [next],
      }),
      steps(2, { 1: "#/analyze" }),
      kpis([
        { label: "Quality score", value: fmtPct(q.score) },
        { label: "Completeness", value: fmtPct(q.completeness), sub: `${fmtInt(Object.values(q.null_counts || {}).reduce((a, b) => a + b, 0))} missing cells` },
        { label: "Validity", value: fmtPct(q.validity), sub: `${fmtInt(prof.validation.invalid_rows)} rows break the inferred schema` },
        { label: "Uniqueness", value: fmtPct(q.uniqueness), sub: `${fmtInt(q.duplicate_rows)} duplicate rows` },
        { label: "Freshness", value: q.freshness === null ? "-" : fmtPct(q.freshness), sub: q.newest_timestamp ? `newest ${q.newest_timestamp.slice(0, 16)}` : "no timestamp column" },
      ]),
    );
    const grid = h("div", { class: "grid grid-main-side" });
    grid.append(
      panel({ title: "Columns", sub: "Inferred type, statistics and distribution. Red bars count values beyond the 1st/99th percentile.", body: columnCards(prof), flush: true }),
      config,
    );
    body.append(grid);
  }

  function columnCards(prof) {
    return h("div", { class: "colgrid" }, prof.columns.map((c) => {
      const stats = c.mean !== null && c.mean !== undefined
        ? [["mean", fmtNum(c.mean)], ["median", fmtNum(c.median)], ["min", fmtNum(c.min)], ["max", fmtNum(c.max)]]
        : c.min !== null && c.min !== undefined ? [["min", String(c.min).slice(0, 19)], ["max", String(c.max).slice(0, 19)]] : [];
      return h("article", { class: "colcard" },
        h("div", { class: "row spread" }, h("span", { class: "name" }, c.name), chip(c.dtype, "plain")),
        c.histogram ? histogram(c.histogram, fmtNum) : null,
        c.top_values && c.top_values.length && !c.histogram ? h("div", { class: "topvals" }, c.top_values.slice(0, 5).map(([v, n]) => h("div", { class: "tv" }, h("span", { title: v }, v), h("span", null, fmtInt(n))))) : null,
        h("dl", null, [["nulls", `${fmtInt(c.nulls)} (${c.null_pct}%)`], ["unique", fmtInt(c.unique)], c.invalid ? ["invalid", fmtInt(c.invalid)] : null, ...stats]
          .filter(Boolean).flatMap(([k, v]) => [h("dt", null, k), h("dd", { title: v }, v)])));
    }));
  }

  function configPanel(prof, detectors) {
    const sug = prof.suggestions;
    // a time-ordered file without natural groups is most likely a series: start
    // with the seasonal and level-shift detectors as well
    const series = sug.time_columns.length > 0 && sug.group_by.length === 0;
    const chosen = new Set(series ? ["mad", "seasonal", "cusum"] : ["mad", "iforest"]);
    const opts = { group_by: sug.group_by.includes("region") ? "region" : "", sensitivity: "medium", combine: "any", time_column: sug.time_columns[0] || "", columns: [] };
    const byCat = {};
    for (const d of detectors) (byCat[d.category] ||= []).push(d);
    const detList = h("div", { class: "stack" }, Object.entries(byCat).map(([cat, list]) => h("div", { class: "stack", style: { gap: "6px" } },
      h("div", { class: "label" }, cat === "ml" ? "Machine learning" : cat === "timeseries" ? "Time series" : "Statistical"),
      h("div", { class: "detector-list" }, list.map((d) => h("label", { class: "det-option" },
        h("input", { type: "checkbox", checked: chosen.has(d.name), onChange: (e) => { if (e.target.checked) chosen.add(d.name); else chosen.delete(d.name); validate(); } }),
        h("span", null, h("b", null, d.name), h("small", null, d.description))))))));
    const groupSel = select([{ value: "", label: "No grouping" }, ...sug.group_by.map((c) => ({ value: c, label: c })), ...prof.dataset.columns.filter((c) => !sug.group_by.includes(c)).map((c) => ({ value: c, label: `${c} (high cardinality)` }))],
      { value: opts.group_by, label: "Group by", onChange: (v) => { opts.group_by = v; } });
    const timeSel = select([{ value: "", label: "None" }, ...prof.dataset.columns.map((c) => ({ value: c, label: c }))], { value: opts.time_column, label: "Time column", onChange: (v) => { opts.time_column = v; } });
    const colChecks = h("div", { class: "row" }, sug.numeric_columns.map((c) => h("label", { class: "check" },
      h("input", { type: "checkbox", checked: true, value: c }), h("span", { class: "mono small" }, c))));
    const combineSel = select([{ value: "any", label: "Any detector flags it" }, { value: "vote", label: "At least 2 detectors agree" }, { value: "all", label: "Every detector agrees" }], { value: "any", label: "Combine", onChange: (v) => { opts.combine = v; } });
    const runBtn = button("Run analysis", { kind: "primary", icon: "play" });
    const progress = h("div", { class: "stack", "aria-live": "polite" });
    const err = h("p", { class: "small", style: { color: "var(--color-high)" }, hidden: true });
    function validate() {
      runBtn.disabled = chosen.size === 0;
      err.hidden = chosen.size > 0;
      err.textContent = chosen.size ? "" : "Pick at least one detector.";
    }
    runBtn.addEventListener("click", () => busy(runBtn, async () => {
      const cols = [...colChecks.querySelectorAll("input:checked")].map((i) => i.value);
      const body = {
        dataset_id: datasetId,
        detectors: [...chosen],
        group_by: opts.group_by || null,
        time_column: opts.time_column || null,
        sensitivity: opts.sensitivity,
        combine: opts.combine,
        columns: cols.length && cols.length < sug.numeric_columns.length ? cols : null,
      };
      const bar = h("span", { style: { transform: "scaleX(0.02)" } });
      const msg = h("span", { class: "muted small" }, "Queued");
      add(clear(progress), h("div", { class: "progress", role: "progressbar", "aria-label": "Analysis progress" }, bar), msg);
      try {
        const res = await api.post("/api/analyses", body);
        const job = await waitForJob(res.job.id, { onUpdate: (j) => { bar.style.transform = `scaleX(${Math.max(0.02, j.progress || 0)})`; msg.textContent = j.message || j.status; } });
        if (job.status !== "success") throw new Error(job.error || `Job ${job.status}`);
        location.hash = `#/analyze/a/${res.analysis.id}`;
      } catch (e) {
        add(clear(progress), h("div", { class: "notice error", role: "alert" }, e.message));
      }
    }));
    validate();
    return panel({
      title: "Detect anomalies",
      sub: "Choose detectors and options. Scores are normalised so 1.0 is each detector's threshold.",
      cls: "config",
      body: h("div", { class: "stack" },
        detList,
        h("label", { class: "field" }, h("span", null, "Group by"), groupSel, h("span", { class: "hint" }, "Fits each detector within groups, so a west-region price on a north order stands out (contextual anomalies).")),
        h("div", { class: "field" }, h("span", null, "Sensitivity"), segmented([{ value: "low", label: "Low" }, { value: "medium", label: "Medium" }, { value: "high", label: "High" }], "medium", (v) => { opts.sensitivity = v; }, "Sensitivity"),
          h("span", { class: "hint" }, "Low raises every threshold 1.5x, high lowers it to 0.7x. Feedback-tuned thresholds still apply.")),
        h("div", { class: "field" }, h("span", null, "Columns to score"), colChecks, h("span", { class: "hint" }, "Numeric columns; id-like columns are excluded.")),
        h("details", null, h("summary", { class: "small" }, "More options"),
          h("div", { class: "stack", style: { marginTop: "12px" } },
            h("label", { class: "field" }, h("span", null, "Combine detectors"), combineSel),
            h("label", { class: "field" }, h("span", null, "Time column"), timeSel, h("span", { class: "hint" }, "Rows are sorted by it before time-series detectors run.")))),
        err, runBtn, progress),
    });
  }

  load();
  return () => { aborted = true; };
}

// ---------------------------------------------------------------- 4-5. results + remediation
function renderAnalysis(root, analysisId) {
  setTitle("Analysis");
  const q = currentRoute().query;
  const state = {
    tab: ["fix", "data"].includes(q.tab) ? q.tab : "incidents",
    offset: Number(q.offset) || 0,
    limit: Number(q.limit) || 50,
    column: q.column || "",
    detector: q.detector || "",
    severity: q.severity || "",
    all: q.all === "1",
    sort: q.sort || "score",
  };
  const body = h("div", { class: "stack" }, loading(5));
  root.append(body);
  let alive = true;
  let meta = null;

  async function load() {
    try {
      meta = await api.get(`/api/analyses/${analysisId}`);
      if (!alive) return;
      if (meta.status === "queued" || meta.status === "running") {
        add(clear(body), pageHead({ title: meta.dataset, crumbs: [{ label: "Analyze", href: "#/analyze" }, { label: "Running" }] }),
          h("div", { class: "panel panel-body row" }, h("span", { class: "spinner" }), "Analysis running. This page updates when it finishes."));
        setTimeout(() => alive && load(), 900);
        return;
      }
      if (meta.status === "failed") {
        add(clear(body), pageHead({ title: meta.dataset, crumbs: [{ label: "Analyze", href: "#/analyze" }, { label: "Failed" }] }),
          h("div", { class: "notice error", role: "alert" }, meta.error || "The analysis failed."),
          h("div", null, h("a", { class: "btn", href: `#/analyze/d/${meta.dataset_id}` }, "Change options and retry")));
        return;
      }
      draw();
    } catch (err) {
      add(clear(body), errorState(err, load));
    }
  }

  function sync() {
    setQuery({
      tab: state.tab === "incidents" ? "" : state.tab, offset: state.offset || "", limit: state.limit === 50 ? "" : state.limit,
      column: state.column, detector: state.detector, severity: state.severity, all: state.all ? "1" : "", sort: state.sort === "score" ? "" : state.sort,
    });
  }

  function draw() {
    const sm = meta.summary;
    const o = meta.options;
    setTitle(`Analysis of ${meta.dataset}`);
    const content = h("div", { role: "tabpanel" });
    const incidents = meta.run_id ? incidentList(meta.run_id, {
      focus: q.incident || null,
      onCount: (n) => { badge.textContent = n ? String(n) : ""; badge.hidden = !n; },
      onFilter: (column) => { state.column = column; state.offset = 0; tabs.select("data"); select_("data"); },
    }) : null;
    const badge = h("span", { class: "tab-count", hidden: true });
    const select_ = (t) => {
      state.tab = t;
      sync();
      stepSlot.replaceChildren(steps(t === "fix" ? 5 : 4, { 1: "#/analyze", 2: `#/analyze/d/${meta.dataset_id}`, 3: `#/analyze/d/${meta.dataset_id}` }));
      content.setAttribute("aria-labelledby", `tab-${t}`);
      if (t === "incidents") content.replaceChildren(incidents ? incidents.el : emptyState({ title: "No run recorded" }));
      else add(clear(content), t === "fix" ? fixView() : anomaliesView());
    };
    const tabs = tabBar([
      { id: "incidents", label: "Incidents" },
      { id: "data", label: "Data" },
      { id: "fix", label: "Fix & export" },
    ], state.tab, select_);
    tabs.buttons.incidents.append(badge);
    const stepSlot = h("div");
    add(clear(body), 
      pageHead({
        title: meta.dataset,
        crumbs: [{ label: "Analyze", href: "#/analyze" }, { label: meta.dataset, href: `#/analyze/d/${meta.dataset_id}` }, { label: "Results" }],
        lede: `Detectors: ${o.detectors.join(", ")}${o.group_by ? ` by ${o.group_by}` : ""} · sensitivity ${o.sensitivity} · combine ${o.combine}`,
        actions: [
          h("a", { class: "btn", href: `#/analyze/d/${meta.dataset_id}` }, "Re-run with other options"),
          meta.run_id ? h("a", { class: "btn", href: `#/runs/${meta.run_id}` }, `Run #${meta.run_id}`) : null,
        ],
      }),
      stepSlot,
      kpis([
        { label: "Rows", value: fmtInt(sm.rows) },
        { label: "Anomalous rows", value: fmtInt(sm.n_anomalies), sub: fmtPct(sm.anomaly_rate) },
        { label: "Findings", value: fmtInt(sm.n_findings), sub: "cell and row flags" },
        { label: "High severity", value: fmtInt(meta.breakdown?.by_severity?.high ?? 0), sub: "score at least 3x threshold" },
        { label: "Columns affected", value: fmtInt(Object.keys(sm.anomalies_by_column || {}).filter((c) => c !== "(row)").length) },
      ]),
      tabs.el,
      content,
    );
    select_(state.tab);
  }

  // -------------------------------------------------- anomalies tab
  function anomaliesView() {
    const bd = meta.breakdown || { by_column: {}, by_detector: {} };
    const tableSlot = h("div", null, loading(6));
    const colSel = select([{ value: "", label: "All columns" }, ...Object.keys(bd.by_column).map((c) => ({ value: c, label: `${c} (${bd.by_column[c]})` }))], { value: state.column, label: "Column", onChange: (v) => { state.column = v; state.offset = 0; reload(); } });
    const detSel = select([{ value: "", label: "All detectors" }, ...Object.keys(bd.by_detector).map((c) => ({ value: c, label: `${c} (${bd.by_detector[c]})` }))], { value: state.detector, label: "Detector", onChange: (v) => { state.detector = v; state.offset = 0; reload(); } });
    const sevSel = select([{ value: "", label: "Any severity" }, { value: "high", label: "High" }, { value: "medium", label: "Medium" }, { value: "low", label: "Low" }], { value: state.severity, label: "Severity", onChange: (v) => { state.severity = v; state.offset = 0; reload(); } });
    const sortSel = select([{ value: "score", label: "Highest score first" }, { value: "row", label: "Row order" }], { value: state.sort, label: "Sort", onChange: (v) => { state.sort = v; state.offset = 0; reload(); } });
    const allChk = h("label", { class: "check" }, h("input", { type: "checkbox", checked: state.all, onChange: (e) => { state.all = e.target.checked; state.offset = 0; reload(); } }), "Show every row");
    function setFilter(key, value) {
      state[key] = state[key] === value ? "" : value;
      state.offset = 0;
      if (key === "column") colSel.value = state.column;
      if (key === "detector") detSel.value = state.detector;
      reload();
    }
    async function reload() {
      sync();
      tableSlot.setAttribute("aria-busy", "true");
      try {
        const data = await api.get(`/api/analyses/${analysisId}/rows`, {
          offset: state.offset, limit: state.limit, only_anomalous: !state.all,
          column: state.column, detector: state.detector, severity: state.severity, sort: state.sort,
        });
        add(clear(tableSlot), grid(data));
      } catch (err) {
        add(clear(tableSlot), errorState(err, reload));
      } finally {
        tableSlot.removeAttribute("aria-busy");
      }
    }
    function grid(data) {
      if (!data.rows.length) {
        return emptyState({ title: "No rows match", text: "Clear a filter or include every row." });
      }
      const cols = data.columns;
      const table = h("table", { class: "data grid-data" },
        h("thead", null, h("tr", null, h("th", null, "row"), cols.map((c) => h("th", { class: state.column === c ? "is-filtered" : null }, c)), h("th", null, "row flags"))),
        h("tbody", null, data.rows.map((r) => h("tr", null,
          h("td", { class: "idx" }, String(r.index)),
          cols.map((c) => {
            const v = r.values[c];
            const fs = r.cells[c];
            if (!fs) return h("td", { class: v === null ? "null" : null }, v === null ? "null" : fmtValue(v));
            const worst = fs.reduce((a, b) => (b.score > a.score ? b : a));
            const td = h("td", {
              class: ["flag", worst.severity], tabindex: "0", role: "button",
              title: fs.map((f) => `${f.detector}: ${f.reason}`).join("\n"),
              "aria-label": `${c} = ${fmtValue(v)}, ${fs.length} finding${fs.length > 1 ? "s" : ""}, ${worst.severity} severity`,
            }, v === null ? "null" : fmtValue(v));
            const open = () => cellPopover(td, c, v, fs);
            td.addEventListener("click", open);
            td.addEventListener("keydown", (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); open(); } });
            return td;
          }),
          h("td", { class: "rowflag" }, r.row_findings.length ? (() => {
            const b = h("button", { class: "btn sm", type: "button" }, `${r.row_findings.length} row-level`);
            b.addEventListener("click", () => cellPopover(b, "(whole row)", null, r.row_findings));
            return b;
          })() : "")))));
      return h("div", null,
        h("div", { class: "table-wrap" }, table),
        pager({ offset: state.offset, limit: state.limit, total: data.total, noun: "rows", onChange: (off, lim) => { state.offset = off; state.limit = lim; reload(); } }));
    }
    reload();
    const toBars = (obj, key) => Object.entries(obj).sort((a, b) => b[1] - a[1]).map(([k, v]) => ({ label: k, value: v, onClick: () => setFilter(key, k) }));
    return h("div", { class: "stack" },
      h("div", { class: "grid grid-2" },
        panel({ title: "Findings by column", sub: "Click a bar to filter the table", body: barList(toBars(bd.by_column, "column"), { format: fmtInt }) }),
        panel({ title: "Findings by detector", sub: "Grouped detectors are fitted per group", body: barList(toBars(bd.by_detector, "detector"), { format: fmtInt }) })),
      h("section", { class: "panel" },
        h("div", { class: "panel-head" },
          h("div", null, h("h2", null, "Data"), h("p", null, "Flagged cells are tinted by severity. Hover for the reason, click for details and feedback.")),
          h("div", { class: "row small" }, chip("high", "high"), chip("medium", "medium"), chip("low", "low"))),
        h("div", { class: "panel-body" }, h("div", { class: "filters" }, colSel, detSel, sevSel, sortSel, allChk)),
        tableSlot));
  }

  function cellPopover(anchor, column, value, findings) {
    const list = h("div", null, findings.map((f) => {
      const fp = h("button", { class: "btn sm", type: "button" }, "False positive");
      const tp = h("button", { class: "btn sm ghost", type: "button" }, "Confirm");
      const send = (label, b) => busy(b, async () => {
        try {
          await api.post("/api/feedback", { anomaly_id: f.id, label });
          toast(label === "false_positive" ? `Recorded a false positive for ${f.detector}. Tune thresholds in Settings.` : `Confirmed ${f.detector} finding.`);
          closePopover();
        } catch (err) { toast(err.message, { kind: "error" }); }
      });
      fp.addEventListener("click", () => send("false_positive", fp));
      tp.addEventListener("click", () => send("true_positive", tp));
      return h("div", { class: "finding" },
        h("div", { class: "row spread" }, h("span", { class: "mono" }, f.detector), h("span", { class: "row" }, chip(f.severity), h("span", { class: "num small muted" }, `score ${fmtNum(f.score, 3)}`))),
        h("p", null, f.reason),
        h("div", { class: "row" }, fp, tp));
    }));
    popover(anchor, h("div", { class: "stack", style: { gap: "4px" } },
      h("div", { class: "label" }, column),
      value !== null && value !== undefined ? h("div", { class: "mono", style: { color: "var(--color-ink)", fontWeight: "600" } }, fmtValue(value)) : null,
      list));
  }

  // -------------------------------------------------- fix tab
  function fixView() {
    const bd = meta.breakdown || { by_column: {} };
    const existing = meta.remediation;
    const policy = existing?.policy || { default: { missing: "auto", outlier: "cap", invalid: "coerce" }, columns: {}, dedupe: true };
    policy.default = { missing: "auto", outlier: "cap", invalid: "coerce", ...(policy.default || {}) };
    policy.columns ||= {};
    const flaggedCols = Object.keys(bd.by_column).filter((c) => c !== "(row)");
    const resultSlot = h("div", { class: "stack" });
    const perCol = h("tbody", null, flaggedCols.map((c) => {
      const cur = policy.columns[c] || {};
      return h("tr", null,
        h("td", { class: "mono" }, c),
        h("td", { class: "r num" }, fmtInt(bd.by_column[c])),
        h("td", null, select([{ value: "", label: `default (${policy.default.outlier})` }, ...OUTLIER.map((v) => ({ value: v, label: v }))], {
          value: cur.outlier || "", cls: "select sm", label: `Outlier strategy for ${c}`,
          onChange: (v) => { policy.columns[c] = { ...(policy.columns[c] || {}) }; if (v) policy.columns[c].outlier = v; else delete policy.columns[c].outlier; },
        })),
        h("td", null, select([{ value: "", label: `default (${policy.default.missing})` }, ...MISSING.map((v) => ({ value: v, label: v }))], {
          value: cur.missing || "", cls: "select sm", label: `Missing-value strategy for ${c}`,
          onChange: (v) => { policy.columns[c] = { ...(policy.columns[c] || {}) }; if (v) policy.columns[c].missing = v; else delete policy.columns[c].missing; },
        })));
    }));
    const defaults = h("div", { class: "grid", style: { gridTemplateColumns: "repeat(auto-fit, minmax(180px, 1fr))" } },
      h("label", { class: "field" }, h("span", null, "Outliers"), select(OUTLIER, { value: policy.default.outlier, label: "Default outlier strategy", onChange: (v) => { policy.default.outlier = v; } }), h("span", { class: "hint" }, "cap: robust fences; unmovable values go to review")),
      h("label", { class: "field" }, h("span", null, "Missing values"), select(MISSING, { value: policy.default.missing, label: "Default missing-value strategy", onChange: (v) => { policy.default.missing = v; } }), h("span", { class: "hint" }, "auto: median for numbers, mode for categories, flag ids and text")),
      h("label", { class: "field" }, h("span", null, "Type errors"), select(INVALID, { value: policy.default.invalid, label: "Type error strategy", onChange: (v) => { policy.default.invalid = v; } }), h("span", { class: "hint" }, "coerce: unparseable values become missing, then imputed")),
      h("label", { class: "check", style: { alignSelf: "center" } }, h("input", { type: "checkbox", checked: policy.dedupe !== false, onChange: (e) => { policy.dedupe = e.target.checked; } }), "Drop duplicate rows"));
    const previewBtn = button(existing ? "Preview again" : "Preview fixes", { kind: "primary", icon: "play" });
    previewBtn.addEventListener("click", () => busy(previewBtn, async () => {
      const cleaned = { ...policy, columns: Object.fromEntries(Object.entries(policy.columns).filter(([, v]) => Object.keys(v).length)) };
      try {
        const res = await api.post(`/api/analyses/${analysisId}/remediate`, cleaned);
        meta.remediation = res;
        previewBtn.lastChild.textContent = "Preview again";
        meta.artifacts = [...new Set([...(meta.artifacts || []), "cleaned.csv", "remediation.md", "remediation.json"])];
        showResult(res);
      } catch (err) {
        add(clear(resultSlot), h("div", { class: "notice error", role: "alert" }, err.message));
      }
    }));
    if (existing) showResult(existing);

    function showResult(res) {
      const sm = res.summary;
      const diffSlot = h("div", null, loading(4));
      const dstate = { offset: 0, limit: 25, column: "" };
      async function loadDiff() {
        try {
          const d = await api.get(`/api/analyses/${analysisId}/changes`, { offset: dstate.offset, limit: dstate.limit, column: dstate.column });
          if (!d.total) { add(clear(diffSlot), emptyState({ title: "No cell changes", text: "This policy only flags or drops. Flagged values can go to the review queue." })); return; }
          add(clear(diffSlot), h("div", { class: "table-wrap" }, h("table", { class: "data" },
            h("thead", null, h("tr", null, ["Row", "Column", "Before", "", "After", "Strategy", "Reason"].map((t) => h("th", null, t)))),
            h("tbody", null, d.items.map((c) => h("tr", null,
              h("td", { class: "mono" }, String(c.index)),
              h("td", { class: "mono" }, c.column),
              h("td", { class: "value-cell" }, h("span", { class: "diff-before" }, fmtValue(c.before))),
              h("td", { class: "arrow", "aria-hidden": "true" }, "→"),
              h("td", { class: "value-cell" }, h("span", { class: "diff-after" }, fmtValue(c.after))),
              h("td", null, chip(c.strategy, "plain")),
              h("td", { class: "reason" }, h("span", { class: "text", title: c.reason }, c.reason))))))),
          pager({ offset: dstate.offset, limit: dstate.limit, total: d.total, noun: "changes", sizes: [25, 50, 100], onChange: (off, lim) => { dstate.offset = off; dstate.limit = lim; loadDiff(); } }));
        } catch (err) { add(clear(diffSlot), errorState(err, loadDiff)); }
      }
      const changedCols = Object.keys(sm.changes_by_column || {});
      const diffFilter = select([{ value: "", label: "All columns" }, ...changedCols.map((c) => ({ value: c, label: `${c} (${sm.changes_by_column[c]})` }))], { value: "", cls: "select sm", label: "Filter changes by column", onChange: (v) => { dstate.column = v; dstate.offset = 0; loadDiff(); } });
      const dl = (name, label) => {
        const b = button(label, { icon: "download" });
        b.addEventListener("click", () => busy(b, async () => {
          try { await api.download(`/api/analyses/${analysisId}/download/${name}`); } catch (err) { toast(err.message, { kind: "error" }); }
        }));
        return b;
      };
      const queueBtn = button(res.n_flagged ? `Send ${fmtInt(res.n_flagged)} flagged values to review` : "Nothing to review", { icon: "flag", disabled: !res.n_flagged });
      queueBtn.addEventListener("click", () => busy(queueBtn, async () => {
        try {
          const out = await api.post(`/api/analyses/${analysisId}/review`);
          toast(`${fmtInt(out.queued)} items are in the review queue.`, { action: { label: "Open queue", run: () => { location.hash = `#/review?run=${meta.run_id}`; } } });
          refreshBadge();
        } catch (err) { toast(err.message, { kind: "error" }); }
      }));
      const statsRows = Object.entries(res.column_stats || {});
      add(clear(resultSlot), 
        kpis([
          { label: "Rows out", value: fmtInt(sm.rows_out), sub: `of ${fmtInt(sm.rows_in)} in` },
          { label: "Cells changed", value: fmtInt(sm.cells_changed) },
          { label: "Rows dropped", value: fmtInt(sm.rows_dropped), sub: Object.entries(sm.drop_reasons || {}).map(([k, v]) => `${v} ${k}`).join(", ") || null },
          { label: "Flagged for review", value: fmtInt(sm.rows_flagged_for_review), sub: `${fmtInt(res.n_flagged)} values` },
        ]),
        panel({
          title: "Export",
          sub: "The cleaned CSV and both reports reflect the policy previewed above.",
          body: h("div", { class: "row" }, dl("cleaned.csv", "Cleaned CSV"), dl("remediation.md", "Report (Markdown)"), dl("remediation.json", "Report (JSON)"), dl("anomalies.json", "Anomalies (JSON)"), queueBtn),
        }),
        statsRows.length ? panel({
          title: "Column statistics, before and after", flush: true,
          body: h("div", { class: "table-wrap" }, h("table", { class: "data" },
            h("thead", null, h("tr", null, ["Column", "Nulls", "Mean", "Std", "Min", "Max"].map((t, i) => h("th", { class: i ? "r" : null }, t)))),
            h("tbody", null, statsRows.map(([c, st]) => h("tr", null, h("td", { class: "mono" }, c),
              ["nulls", "mean", "std", "min", "max"].map((k) => h("td", { class: "r num nowrap" },
                h("span", { class: "muted" }, fmtNum(st.before[k])), h("span", { class: "arrow" }, "→"), fmtNum(st.after[k])))))))),
        }) : null,
        panel({ title: "Changed cells", sub: Object.entries(sm.changes_by_strategy || {}).map(([k, v]) => `${k} ${v}`).join(" · "), actions: [diffFilter], body: diffSlot, flush: true }),
      );
      loadDiff();
    }

    return h("div", { class: "stack" },
      panel({
        title: "Remediation policy",
        sub: "Choose what happens to each kind of problem. Only cells a detector attributed to a column are treated as outliers.",
        body: h("div", { class: "stack" },
          defaults,
          flaggedCols.length ? h("div", { class: "table-wrap" }, h("table", { class: "data" },
            h("thead", null, h("tr", null, h("th", null, "Column"), h("th", { class: "r" }, "Findings"), h("th", null, "Outliers"), h("th", null, "Missing values"))),
            perCol)) : null,
          h("p", { class: "muted small" }, Object.entries(STRATEGY_HELP).map(([k, v]) => `${k}: ${v}`).join(" · ")),
          h("div", null, previewBtn)),
      }),
      resultSlot);
  }

  load();
  return () => { alive = false; closePopover(); };
}
