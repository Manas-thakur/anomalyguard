// Incident cards: a status tag in plain language, the entity, one sentence,
// expected vs actual with the change, a chart with the expected band, and
// inline triage (Mark as normal, Confirm, Mute 24h). Used by run detail and
// analysis results.

import { api } from "./api.js";
import { distributionChart, historyChart, seriesBandChart } from "./bandcharts.js";
import {
  add, busy, button, clear, emptyState, segmented, errorState, fmtInt, fmtNum, fmtValue, h, icon, loading,
  timeEl, toast,
} from "./ui.js";
import { refreshBadge } from "./app.js";

const KIND_HELP = {
  outlier: "Robust range: median ± 3.5 robust standard deviations (MAD) of the column.",
  pattern: "Expected = trend + daily/weekly seasonality, ± 3.5 robust standard deviations of the residual.",
  level_shift: "Expected = the level before the shift plus seasonality, ± 3.5 robust standard deviations.",
  missing: "Expected = the empty values in the previous run of this source (0 if there is none).",
  duplicates: "A clean load has no repeated rows.",
  invalid: "Rows that break the inferred or configured schema.",
  multivariate: "Rows whose combination of values is rare, even if each value looks normal.",
};

export function fmtDelta(d) {
  if (d === null || d === undefined) return null;
  if (d === 0) return "within range";
  const pct = Math.abs(d) * 100;
  const text = pct >= 1000 ? `${fmtInt(pct)}%` : pct >= 10 ? `${pct.toFixed(0)}%` : `${pct.toFixed(1)}%`;
  return `${d > 0 ? "+" : "−"}${text} ${d > 0 ? "above" : "below"} range`;
}

const fmtShort = (v) => (typeof v === "number" ? (Math.abs(v) >= 100 ? fmtInt(v) : fmtNum(v, 4)) : fmtValue(v));

/** Lazily fetch and draw an incident's chart when its card scrolls into view. */
function chartSlot(inc) {
  const slot = h("div", { class: "incident-chart" }, h("div", { class: "chart-skel", "aria-hidden": "true" }));
  let started = false;
  const load = async () => {
    if (started) return;
    started = true;
    try {
      const data = await api.get(`/api/runs/${inc.run_id}/incidents/${inc.id}/chart`);
      clear(slot);
      if (data.type === "distribution") slot.append(distributionChart(data, fmtShort));
      else if (data.type === "series") slot.append(seriesChartWithFocus(data));
      else if (data.type === "history" && data.points.length) slot.append(historyChart(data, fmtShort));
      else slot.remove();
      if (data.type && slot.isConnected) slot.append(legend(data, inc));
    } catch (err) {
      clear(slot).append(h("p", { class: "muted small" }, `Chart unavailable: ${err.message}`));
    }
  };
  if ("IntersectionObserver" in window) {
    const io = new IntersectionObserver((entries) => {
      if (entries.some((e) => e.isIntersecting)) { io.disconnect(); load(); }
    }, { rootMargin: "200px" });
    requestAnimationFrame(() => io.observe(slot));
  } else load();
  return slot;
}

/** Series chart with a toggle between a window around the anomaly and the full history. */
function seriesChartWithFocus(data) {
  if (!data.focus) return seriesBandChart(data, fmtShort);
  const wrap = h("div", { class: "series-wrap" });
  const slot = h("div");
  const [a, b] = data.focus;
  const cut = (arr) => arr.slice(a, b + 1);
  const focused = {
    ...data, x: cut(data.x), y: cut(data.y), expected: cut(data.expected), low: cut(data.low), high: cut(data.high),
    flagged: data.flagged.filter((i) => i >= a && i <= b).map((i) => i - a),
  };
  const showView = (v) => slot.replaceChildren(seriesBandChart(v === "focus" ? focused : data, fmtShort));
  wrap.append(h("div", { class: "chart-tools" }, segmented([{ value: "focus", label: "Around the anomaly" }, { value: "all", label: "Full history" }], "focus", showView, "Chart range")), slot);
  showView("focus");
  return wrap;
}

function legend(data, inc) {
  const type = data.type;
  const item = (cls, text) => h("span", { class: "lg" }, h("span", { class: `key ${cls}`, "aria-hidden": "true" }), text);
  const band = data.band || {};
  if (type === "distribution" && band.low !== null && band.low !== undefined && data.marks.some((m) => m.v >= band.low && m.v <= band.high)) {
    return h("div", { class: "chart-legend" }, item("band", "expected range"), item("bar", "rows"), item("anomaly", "flagged, outside the range"),
      item("anomaly in-band", inc.grouped && inc.grouped.length ? `flagged within its ${inc.grouped.join(", ")}` : "flagged in context"));
  }
  if (type === "history") return h("div", { class: "chart-legend" }, item("band", "expected"), item("bar", "earlier runs"), item("anomaly", "this run"));
  if (type === "series") return h("div", { class: "chart-legend" }, item("band", "expected range"), item("line", "actual"), item("anomaly", "flagged"));
  return h("div", { class: "chart-legend" }, item("band", "expected range"), item("bar", "rows"), item("anomaly", "flagged value"));
}

function stat(label, value, sub, cls) {
  return h("div", { class: ["stat", cls] }, h("div", { class: "label" }, label), h("div", { class: "v" }, value), sub ? h("div", { class: "sub" }, sub) : null);
}

/**
 * One incident card. `onChange(updated)` runs after a triage action so the list
 * can re-sort or hide it; `onFilter(column)` opens the data table on that column.
 */
export function incidentCard(inc, { onChange, onFilter, showSource = false } = {}) {
  const card = h("article", { class: ["incident", `sev-${inc.severity}`, inc.status !== "open" && "is-triaged", inc.muted_until && "is-muted"], id: `incident-${inc.id}`, tabindex: "-1", "aria-labelledby": `inc-title-${inc.id}` });
  const exp = inc.expected;
  const act = inc.actual;
  const delta = fmtDelta(inc.delta_pct);
  const tag = h("span", { class: ["status-tag", inc.severity] }, h("span", { class: "dot", "aria-hidden": "true" }), inc.title);
  const meta = h("div", { class: "meta" },
    h("span", { class: "sev" }, `${inc.severity[0].toUpperCase()}${inc.severity.slice(1)} severity`),
    showSource ? [" · ", h("a", { href: `#/runs/${inc.run_id}` }, `run #${inc.run_id}`), " · ", timeEl(inc.started_at)] : null);
  const actions = h("div", { class: "triage", role: "group", "aria-label": "Triage" });

  function drawActions() {
    clear(actions);
    if (inc.muted_until) {
      const until = new Date(inc.muted_until);
      const unmute = button("Unmute", { small: true, kind: "ghost" });
      unmute.addEventListener("click", () => busy(unmute, async () => {
        try {
          await api.del(`/api/incidents/mutes/${inc.mute_id}`);
          inc.muted_until = null;
          inc.mute_id = null;
          toast(`Unmuted ${inc.entity}.`);
          update();
        } catch (err) { toast(err.message, { kind: "error" }); }
      }));
      actions.append(h("span", { class: "state-note" }, icon("bell-off"), `Muted until ${until.toLocaleString(undefined, { weekday: "short", hour: "2-digit", minute: "2-digit" })}`), unmute);
      return;
    }
    if (inc.status !== "open") {
      const undo = button("Reopen", { small: true, kind: "ghost" });
      undo.addEventListener("click", () => busy(undo, () => triage("reopen")));
      actions.append(h("span", { class: ["state-note", inc.status] }, icon(inc.status === "normal" ? "check" : "flag"), inc.status === "normal" ? "Marked as normal" : "Confirmed"), undo);
      return;
    }
    const normal = button("Mark as normal", { small: true, icon: "check", title: "Not a problem: record false positives so the detector learns" });
    const confirm = button("Confirm", { small: true, kind: "primary", icon: "flag", title: inc.column && inc.kind !== "missing" ? "A real problem: record true positives and send the flagged cells to review" : "A real problem: record it as confirmed" });
    const mute = button("Mute 24h", { small: true, kind: "ghost", icon: "bell-off", title: `Hide ${inc.title.toLowerCase()} on ${inc.entity} for 24 hours` });
    normal.addEventListener("click", () => busy(normal, () => triage("normal")));
    confirm.addEventListener("click", () => busy(confirm, () => triage("confirm")));
    mute.addEventListener("click", () => busy(mute, async () => {
      try {
        const m = await api.post(`/api/runs/${inc.run_id}/incidents/${inc.id}/mute`, { hours: 24 });
        inc.muted_until = m.until;
        inc.mute_id = m.id;
        toast(`Muted ${inc.entity} for 24 hours.`, {
          action: { label: "Undo", run: async () => { await api.del(`/api/incidents/mutes/${m.id}`); inc.muted_until = null; inc.mute_id = null; update(); } },
        });
        update();
      } catch (err) { toast(err.message, { kind: "error" }); }
    }));
    actions.append(normal, confirm, mute);
  }

  async function triage(action) {
    try {
      const r = await api.post(`/api/runs/${inc.run_id}/incidents/${inc.id}/triage`, { action });
      Object.assign(inc, r.incident);
      if (action === "normal") toast(r.feedback ? `Marked as normal: ${fmtInt(r.feedback)} findings recorded as false positives${r.rejected ? `, ${fmtInt(r.rejected)} review items rejected` : ""}. Tune thresholds in Settings.` : "Marked as normal.");
      if (action === "confirm") {
        toast(r.queued ? `Confirmed. ${fmtInt(r.queued)} flagged values are in the review queue.` : "Confirmed.", r.queued ? { action: { label: "Open review", run: () => { location.hash = `#/review?run=${inc.run_id}&column=${encodeURIComponent(inc.column || "")}`; } } } : {});
        refreshBadge();
      }
      if (action === "normal") refreshBadge();
      update();
    } catch (err) { toast(err.message, { kind: "error" }); }
  }

  function update() {
    card.classList.toggle("is-triaged", inc.status !== "open");
    card.classList.toggle("is-muted", Boolean(inc.muted_until));
    drawActions();
    if (onChange) onChange(inc);
  }

  const stats = h("div", { class: "stats" },
    stat("Expected", exp ? exp.text : "-", exp && inc.kind !== "missing" && inc.kind !== "duplicates" && inc.kind !== "invalid" ? `median ${fmtShort(exp.center)}` : exp && exp.basis ? exp.basis : null),
    stat("Actual", act ? act.text : "-", act && act.at ? act.at : act && act.row !== undefined && act.row !== null ? `row ${act.row}` : null, "actual"),
    delta ? stat("Change", delta, null, inc.delta_pct > 0 ? "up" : inc.delta_pct < 0 ? "down" : null) : null,
    stat("Scope", `${fmtInt(inc.n_rows)} ${inc.n_rows === 1 ? "row" : "rows"}`, inc.detectors.join(", ")));

  const sample = inc.sample && inc.sample.length
    ? h("details", { class: "sample" }, h("summary", null, `Top findings (${fmtInt(inc.n_findings)})`),
      h("ul", { class: "list" }, inc.sample.map((f) => h("li", null,
        h("div", { class: "grow" },
          h("div", { class: "row" }, h("span", { class: "mono small" }, `row ${f.row_index}`), f.value !== null && f.value !== undefined ? h("span", { class: "mono small strong" }, fmtValue(f.value)) : null, h("span", { class: "mono small muted" }, f.detector)),
          h("p", { class: "small muted" }, f.reason))))),
      onFilter && inc.column ? h("button", { class: "link-btn small", type: "button", onClick: () => onFilter(inc.column) }, `Show ${inc.column} in the data table`) : null)
    : null;

  add(card,
    h("header", { class: "incident-head" }, tag, meta),
    h("h3", { class: "entity", id: `inc-title-${inc.id}` }, inc.entity),
    h("p", { class: "explain" }, inc.explanation),
    stats,
    inc.chart ? chartSlot(inc) : null,
    h("footer", { class: "incident-foot" }, actions, h("span", { class: "help", title: KIND_HELP[inc.kind] || "" }, KIND_HELP[inc.kind] || "")),
    sample,
  );
  drawActions();
  return card;
}

/**
 * Incident list for one run: open first, triaged after, muted hidden behind a toggle.
 * Returns { el, reload }.
 */
export function incidentList(runId, { onFilter, onCount, focus } = {}) {
  const state = { showMuted: false, showTriaged: true };
  const head = h("div", { class: "incident-toolbar" });
  const listEl = h("div", { class: "incident-list" }, loading(4));
  const el = h("section", { class: "incidents", "aria-label": "Incidents" }, head, listEl);
  let items = [];
  let muted = 0;

  function drawHead() {
    clear(head);
    if (state.showMuted) muted = items.filter((i) => i.muted_until).length;
    const open = items.filter((i) => i.status === "open" && !i.muted_until).length;
    const triaged = items.filter((i) => i.status !== "open" && !i.muted_until).length;
    head.append(
      h("p", { class: "summary" }, h("strong", null, `${fmtInt(open)} open`), triaged ? ` · ${fmtInt(triaged)} triaged` : "", muted ? ` · ${fmtInt(muted)} muted` : ""),
      h("div", { class: "row" },
        muted || state.showMuted ? h("label", { class: "check small" }, h("input", { type: "checkbox", checked: state.showMuted, onChange: (e) => { state.showMuted = e.target.checked; load(); } }), `Show muted (${fmtInt(muted)})`) : null));
  }

  // Triage updates a card in place (no re-sort, so nothing jumps under the pointer);
  // a newly muted incident leaves the list unless muted ones are shown.
  function changed(inc, card) {
    if (inc.muted_until && !state.showMuted) {
      muted += 1;
      items = items.filter((x) => x !== inc);
      card.remove();
      if (!items.length) draw();
    }
    drawHead();
    if (onCount) onCount(count());
  }

  function draw() {
    drawHead();
    clear(listEl);
    if (!items.length) {
      listEl.append(emptyState({ title: muted ? "Every incident is muted" : "No incidents", text: muted ? "Show muted incidents to review them." : "Nothing in this run needs attention." }));
      return;
    }
    const rank = (i) => (i.muted_until ? 2 : i.status === "open" ? 0 : 1);
    const sorted = items.slice().sort((a, b) => rank(a) - rank(b));
    for (const inc of sorted) {
      const card = incidentCard(inc, { onFilter, onChange: () => changed(inc, card) });
      listEl.append(card);
    }
    if (focus) {
      const target = listEl.querySelector(`#incident-${CSS.escape(focus)}`);
      if (target) { target.scrollIntoView({ block: "center" }); target.focus({ preventScroll: true }); target.classList.add("is-focus"); }
      focus = null;
    }
  }
  const count = () => items.filter((i) => i.status === "open" && !i.muted_until).length;

  async function load() {
    try {
      const r = await api.get(`/api/runs/${runId}/incidents`, { include_muted: state.showMuted ? "true" : undefined });
      items = r.incidents;
      muted = r.muted;
      draw();
      if (onCount) onCount(r.open);
    } catch (err) {
      clear(listEl).append(errorState(err, load));
    }
  }
  load();
  return { el, reload: load };
}
