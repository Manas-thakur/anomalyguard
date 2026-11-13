// Command palette (Ctrl/Cmd+K): jump to a page, open a run by number, analyze a
// sample dataset, run a pipeline or switch the theme, all from the keyboard.

import { api, waitForJob } from "./api.js";
import { clear, fmtInt, fmtPct, h, icon, runLabel, toast } from "./ui.js";

const dialog = document.getElementById("palette");
const input = document.getElementById("palette-input");
const list = document.getElementById("palette-list");
let commands = [];
let shown = [];
let active = 0;
let dynamic = { runs: [], pipelines: [] };
let opener = null;
let ctx = {};

/** Score a fuzzy (subsequence) match; higher is better, -1 for no match. */
export function fuzzy(query, text) {
  const q = query.toLowerCase().trim();
  if (!q) return 0;
  const t = text.toLowerCase();
  const at = t.indexOf(q);
  if (at >= 0) return 100 - at + (at === 0 || t[at - 1] === " " ? 20 : 0);
  let i = 0;
  let score = 0;
  let prev = -2;
  for (let k = 0; k < t.length && i < q.length; k += 1) {
    if (t[k] === q[i]) { score += k === prev + 1 ? 3 : 1; prev = k; i += 1; }
  }
  return i === q.length ? score : -1;
}

function go(hash) { return () => { location.hash = hash; }; }

async function analyzeSample(kind) {
  const label = kind === "orders" ? "orders" : "sensor readings";
  const t = toast(`Generating the ${label} sample and analyzing it…`, { timeout: 0 });
  try {
    const meta = await api.post("/api/datasets/sample", { kind });
    const body = kind === "orders"
      ? { dataset_id: meta.id, detectors: ["mad", "iforest"], group_by: "region" }
      : { dataset_id: meta.id, detectors: ["mad", "seasonal", "cusum"], time_column: "timestamp" };
    const res = await api.post("/api/analyses", body);
    const job = await waitForJob(res.job.id);
    t.remove();
    if (job.status !== "success") throw new Error(job.error || `Job ${job.status}`);
    location.hash = `#/analyze/a/${res.analysis.id}`;
  } catch (err) {
    t.remove();
    toast(err.message, { kind: "error" });
  }
}

async function runPipeline(p) {
  const t = toast(`Running ${p.name}…`, { timeout: 0 });
  try {
    const { job } = await api.post(`/api/pipelines/${p.id}/run`);
    const done = await waitForJob(job.id, { interval: 700 });
    t.remove();
    if (done.status === "success") {
      const r = done.result;
      toast(`${p.name}: run #${r.run_id}, ${fmtInt(r.metrics.n_anomalies)} anomalous rows (${fmtPct(r.metrics.anomaly_rate)}).`, {
        action: { label: "Open run", run: () => { location.hash = `#/runs/${r.run_id}`; } }, timeout: 9000,
      });
      window.dispatchEvent(new CustomEvent("ag:data-changed"));
    } else toast(`${p.name} failed: ${done.error}`, { kind: "error", timeout: 12000 });
  } catch (err) {
    t.remove();
    toast(err.message, { kind: "error" });
  }
}

function baseCommands() {
  const nav = [
    ["Health", "#/health", "pulse", "g h"],
    ["Runs", "#/runs", "runs", "g r"],
    ["Review inbox", "#/review", "inbox", "g i"],
    ["Analyze a file", "#/analyze", "upload", "g a"],
    ["Pipelines", "#/pipelines", "pipeline", "g p"],
    ["Settings", "#/settings", "settings", "g s"],
  ].map(([label, hash, ic, keys]) => ({ id: `go:${hash}`, group: "Go to", label, icon: ic, keys, run: go(hash) }));
  const theme = (ctx.theme && ctx.theme()) || "system";
  return [
    ...nav,
    { id: "sample:orders", group: "Actions", label: "Analyze sample dataset: orders", hint: "1,000 rows, grouped by region", icon: "play", run: () => analyzeSample("orders") },
    { id: "sample:sensor", group: "Actions", label: "Analyze sample dataset: sensor readings", hint: "hourly series, seasonal + level shift", icon: "play", run: () => analyzeSample("sensor") },
    { id: "upload", group: "Actions", label: "Upload a file to analyze", icon: "upload", run: go("#/analyze") },
    { id: "new-pipeline", group: "Actions", label: "Create a pipeline", icon: "plus", run: go("#/pipelines?new=1") },
    { id: "theme", group: "Preferences", label: theme === "dark" ? "Switch to light theme" : "Switch to dark theme", icon: theme === "dark" ? "sun" : "moon", run: () => ctx.setTheme(theme === "dark" ? "light" : "dark") },
    { id: "theme-system", group: "Preferences", label: "Follow the system theme", icon: "flat", run: () => ctx.setTheme("system") },
    { id: "shortcuts", group: "Help", label: "Keyboard shortcuts", icon: "keyboard", keys: "?", run: () => ctx.showShortcuts() },
  ];
}

function dynamicCommands(q) {
  const out = [];
  const m = /^#?\s*(\d+)$/.exec(q.trim());
  if (m) out.push({ id: `run:${m[1]}`, group: "Runs", label: `Open run #${m[1]}`, icon: "hash", run: go(`#/runs/${m[1]}`), pin: true });
  for (const p of dynamic.pipelines) {
    out.push({ id: `pipe:${p.id}`, group: "Pipelines", label: `Run pipeline: ${p.name || p.file}`, hint: p.description || p.file, icon: "play", run: () => runPipeline(p), disabled: !p.valid });
  }
  for (const r of dynamic.runs.slice(0, 6)) {
    out.push({ id: `recent:${r.id}`, group: "Recent runs", label: `Open run #${r.id} · ${runLabel(r.pipeline)}`, hint: r.status, icon: "runs", run: go(`#/runs/${r.id}`) });
  }
  return out;
}

function render() {
  const q = input.value;
  const all = [...dynamicCommands(q), ...commands];
  shown = q.trim()
    ? all.map((c) => ({ c, score: c.pin ? 1000 : fuzzy(q, `${c.label} ${c.hint || ""} ${c.group}`) }))
      .filter((x) => x.score >= 0).sort((a, b) => b.score - a.score).map((x) => x.c).slice(0, 30)
    : all.slice(0, 40);
  active = Math.min(active, Math.max(0, shown.length - 1));
  clear(list);
  if (!shown.length) {
    list.append(h("li", { class: "empty", role: "presentation" }, "No matching commands. Type a run number to open it."));
    input.removeAttribute("aria-activedescendant");
    return;
  }
  let group = null;
  shown.forEach((c, i) => {
    if (!q.trim() && c.group !== group) {
      group = c.group;
      list.append(h("li", { class: "group", role: "presentation" }, group));
    }
    const li = h("li", { id: `pal-${i}`, role: "option", class: ["item", i === active && "is-active", c.disabled && "is-disabled"], "aria-selected": String(i === active), "aria-disabled": c.disabled ? "true" : null },
      icon(c.icon || "right"),
      h("span", { class: "grow" }, h("span", { class: "label" }, c.label), c.hint ? h("span", { class: "hint" }, c.hint) : null),
      c.keys ? h("span", { class: "keys" }, c.keys.split(" ").map((k) => h("kbd", null, k))) : null);
    li.addEventListener("pointermove", () => { if (active !== i) { active = i; mark(); } });
    li.addEventListener("click", () => choose(i));
    list.append(li);
  });
  mark();
}

function mark() {
  for (const el of list.querySelectorAll("[role=option]")) {
    const on = el.id === `pal-${active}`;
    el.classList.toggle("is-active", on);
    el.setAttribute("aria-selected", String(on));
    if (on) el.scrollIntoView({ block: "nearest" });
  }
  input.setAttribute("aria-activedescendant", `pal-${active}`);
}

function choose(i) {
  const c = shown[i];
  if (!c || c.disabled) return;
  close();
  c.run();
}

export function close() {
  if (dialog.open) dialog.close();
}

export function open() {
  if (dialog.open) return;
  opener = document.activeElement;
  commands = baseCommands();
  input.value = "";
  active = 0;
  render();
  dialog.showModal();
  input.focus();
  Promise.all([api.get("/api/pipelines").catch(() => null), api.list("/api/runs", { limit: 8 }).catch(() => null)]).then(([p, r]) => {
    dynamic = { pipelines: p ? p.pipelines : [], runs: r ? r.items : [] };
    if (dialog.open) render();
  });
}

export function initPalette(context) {
  ctx = context;
  input.addEventListener("input", () => { active = 0; render(); });
  input.addEventListener("keydown", (e) => {
    if (e.key === "ArrowDown" || (e.ctrlKey && e.key === "n")) { e.preventDefault(); active = (active + 1) % Math.max(1, shown.length); mark(); }
    else if (e.key === "ArrowUp" || (e.ctrlKey && e.key === "p")) { e.preventDefault(); active = (active - 1 + shown.length) % Math.max(1, shown.length); mark(); }
    else if (e.key === "Enter") { e.preventDefault(); choose(active); }
  });
  dialog.addEventListener("click", (e) => { if (e.target === dialog) close(); });
  dialog.addEventListener("close", () => { if (opener && opener.focus && document.contains(opener)) opener.focus(); });
  for (const b of document.querySelectorAll("[data-open-palette]")) b.addEventListener("click", open);
}
