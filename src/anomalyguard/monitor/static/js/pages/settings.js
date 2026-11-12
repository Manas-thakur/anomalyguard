// Settings: server configuration, API key, detector thresholds, notifiers, environment.

import { api, hasKey, setKey } from "../api.js";
import {
  busy, button, chip, clear, emptyState, errorState, fmtInt, fmtPct, h, loading, pageHead, panel,
  setTitle, timeEl, toast,
} from "../ui.js";
import { add } from "../ui.js";

export function render(root) {
  setTitle("Settings");
  const body = h("div", { class: "stack" }, loading(6));
  root.append(pageHead({ title: "Settings", lede: "Server configuration, detector thresholds and notifier status. Configuration is read from environment variables at start-up." }), body);

  async function load() {
    try {
      const s = await api.get("/api/settings");
      draw(s);
    } catch (err) {
      add(clear(body), errorState(err, load));
    }
  }

  function draw(s) {
    const srv = s.server;
    const st = s.state;
    add(clear(body), 
      h("div", { class: "grid grid-2" },
        panel({ title: "Server", body: h("dl", { class: "kv" },
          h("dt", null, "Version"), h("dd", null, s.version),
          h("dt", null, "State directory"), h("dd", { class: "mono small" }, st.state_dir),
          h("dt", null, "Database"), h("dd", { class: "mono small" }, st.db),
          h("dt", null, "Working directory"), h("dd", { class: "mono small" }, s.cwd),
          h("dt", null, "Uploads"), h("dd", null, `${fmtInt(st.uploads)} datasets, limit ${srv.max_upload_mb} MB per file`),
          h("dt", null, "Pipeline folders"), h("dd", { class: "mono small" }, srv.pipeline_dirs.join(", ")),
          h("dt", null, "Job workers"), h("dd", null, String(srv.workers)),
          h("dt", null, "CORS origins"), h("dd", null, srv.cors_origins.length ? srv.cors_origins.join(", ") : "same origin only")) }),
        apiKeyPanel(srv)),
      thresholdsPanel(s),
      h("div", { class: "grid grid-2" }, notifierPanel(s.notifiers), extrasPanel(s.extras)),
      envPanel(s.env),
    );
  }

  function apiKeyPanel(srv) {
    const forget = button("Forget the key in this browser", { small: true, disabled: !hasKey() });
    forget.addEventListener("click", () => { setKey(""); forget.disabled = true; toast("Key removed from this browser. You will be asked again on the next request."); });
    return panel({
      title: "API key",
      body: h("div", { class: "stack" },
        h("div", { class: "row" }, srv.auth_enabled ? chip("required", "accent") : chip("not required", "low")),
        h("p", { class: "small" }, srv.auth_enabled
          ? "Every /api request must send the key in the X-API-Key header (or Authorization: Bearer). The browser asks once and keeps it in local storage."
          : "Anyone who can reach this server can use the API. Set ANOMALYGUARD_API_KEY before exposing it beyond localhost."),
        srv.auth_enabled ? h("div", null, forget) : null),
    });
  }

  function thresholdsPanel(s) {
    const thr = Object.fromEntries((s.thresholds || []).map((t) => [t.detector, t]));
    const prec = s.precision || {};
    const names = [...new Set([...Object.keys(thr), ...Object.keys(prec)])].sort();
    const tune = button("Tune from feedback", { kind: "primary" });
    tune.addEventListener("click", () => busy(tune, async () => {
      try {
        const r = await api.post("/api/feedback/tune");
        toast(r.changes.length ? r.changes.map((c) => `${c.detector}: x${c.old.toFixed(2)} to x${c.new.toFixed(2)}`).join("; ") : "No changes: each detector needs at least 3 new reviews, and precision below 80% (or at least 95% to relax).", { timeout: 9000 });
        load();
      } catch (err) { toast(err.message, { kind: "error" }); }
    }));
    const addName = h("input", { class: "input sm mono", placeholder: "detector, e.g. mad", "aria-label": "Detector name", style: { width: "220px", maxWidth: "100%" } });
    const addVal = h("input", { class: "input sm num", type: "number", step: "0.05", min: "0.1", max: "10", value: "1.2", "aria-label": "Multiplier", style: { width: "90px" } });
    const addBtn = button("Set", { small: true });
    addBtn.addEventListener("click", () => busy(addBtn, async () => {
      const name = addName.value.trim();
      if (!name) { addName.setAttribute("aria-invalid", "true"); addName.focus(); return; }
      try { await api.put(`/api/thresholds/${encodeURIComponent(name)}`, { multiplier: Number(addVal.value) }); toast(`${name} threshold set to x${Number(addVal.value).toFixed(2)}.`); load(); } catch (err) { toast(err.message, { kind: "error" }); }
    }));
    const rows = names.map((name) => {
      const t = thr[name];
      const p = prec[name];
      const input = h("input", { class: "input sm num", type: "number", step: "0.05", min: "0.1", max: "10", value: t ? t.multiplier : 1, "aria-label": `Threshold multiplier for ${name}`, style: { width: "90px" } });
      const save = button("Save", { small: true });
      save.addEventListener("click", () => busy(save, async () => {
        try { await api.put(`/api/thresholds/${encodeURIComponent(name)}`, { multiplier: Number(input.value) }); toast(`${name} set to x${Number(input.value).toFixed(2)}.`); load(); } catch (err) { toast(err.message, { kind: "error" }); }
      }));
      const reset = button("Reset", { small: true, kind: "ghost", disabled: !t });
      reset.addEventListener("click", () => busy(reset, async () => {
        try { await api.del(`/api/thresholds/${encodeURIComponent(name)}`); toast(`${name} back to x1.00.`); load(); } catch (err) { toast(err.message, { kind: "error" }); }
      }));
      return h("tr", null,
        h("td", { class: "mono" }, name),
        h("td", null, h("div", { class: "row", style: { flexWrap: "nowrap" } }, input, save, reset)),
        h("td", { class: "r" }, p ? fmtInt(p.true_positive) : "-"),
        h("td", { class: "r" }, p ? fmtInt(p.false_positive) : "-"),
        h("td", { class: "r" }, p ? fmtPct(p.precision, 0) : "-"),
        h("td", { class: "small muted" }, t ? [t.reason || "", " · ", timeEl(t.updated_at)] : "default"));
    });
    return panel({
      title: "Detector thresholds",
      sub: "A multiplier above 1 makes a detector flag less. The next pipeline run and every new analysis apply it.",
      actions: [tune],
      flush: true,
      body: h("div", null,
        names.length ? h("div", { class: "table-wrap" }, h("table", { class: "data" },
          h("thead", null, h("tr", null, ["Detector", "Multiplier", "Confirmed", "False positives", "Precision", "Last change"].map((x, i) => h("th", { class: i >= 2 && i <= 4 ? "r" : null }, x)))),
          h("tbody", null, rows))) : emptyState({ title: "No feedback or overrides yet", text: "Mark findings as false positives on a run or in the review queue, then tune here." }),
        h("div", { class: "panel-body row" }, h("span", { class: "small muted" }, "Override a detector:"), addName, addVal, addBtn)),
    });
  }

  function notifierPanel(list) {
    const items = (list || []).flatMap((p) => (p.notifiers || []).map((n) => ({ ...n, pipeline: p.pipeline })).concat(p.error ? [{ pipeline: p.pipeline, type: "config", ok: false, detail: p.error }] : []));
    return panel({
      title: "Notifiers",
      sub: "Alert channels configured in the pipelines found on disk",
      flush: true,
      body: items.length ? h("ul", { class: "list" }, items.map((n) => h("li", null,
        h("div", { class: "grow" }, h("div", { class: "row" }, chip(n.ok ? "ok" : "check", n.ok ? "success" : "warning"), h("strong", null, n.type), h("span", { class: "muted small" }, n.pipeline)),
          n.detail ? h("div", { class: "small muted mono", style: { marginTop: "4px", overflowWrap: "anywhere" } }, n.detail) : null),
        n.min_severity ? h("span", { class: "small muted nowrap" }, `>= ${n.min_severity}`) : null))) : emptyState({ title: "No notifiers", text: "Add alerts.notifiers to a pipeline (console, file, webhook, slack, email)." }),
    });
  }

  function extrasPanel(extras) {
    return panel({
      title: "Optional extras",
      flush: true,
      body: h("ul", { class: "list" }, Object.entries(extras).map(([name, e]) => h("li", null,
        h("div", { class: "grow" }, h("strong", { class: "mono" }, name), h("div", { class: "small muted" }, { server: "web app and REST API", parquet: "Parquet sources, sinks and uploads", sql: "PostgreSQL, MySQL and other SQLAlchemy databases" }[name] || "")),
        e.installed ? chip("installed", "success") : h("span", { class: "small" }, chip("missing", "warning"), " ", h("code", null, `pip install "anomalyguard[${name}]"`))))),
    });
  }

  function envPanel(env) {
    return panel({
      title: "Environment variables",
      sub: "Secret values are never shown, only whether they are set.",
      flush: true,
      body: h("div", { class: "table-wrap" }, h("table", { class: "data" },
        h("thead", null, h("tr", null, ["Variable", "Status", "Used for"].map((x) => h("th", null, x)))),
        h("tbody", null, env.map((e) => h("tr", null,
          h("td", { class: "mono small" }, e.name),
          h("td", null, e.set ? (e.value ? h("span", { class: "mono small" }, e.value) : chip("set", "success")) : chip("not set", "low")),
          h("td", { class: "small" }, e.purpose)))))),
    });
  }

  load();
}
