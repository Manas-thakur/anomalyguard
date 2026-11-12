// Pipelines: list YAML files, create from a template, view/edit/validate, run now.

import { api, waitForJob } from "../api.js";
import {
  busy, button, chip, clear, drawer, emptyState, errorState, fmtInt, fmtMs, fmtPct, h, loading,
  pageHead, panel, select, setTitle, timeEl, toast,
} from "../ui.js";
import { add } from "../ui.js";

export function render(root, params) {
  if (params.id) return renderDetail(root, params.id);
  return renderList(root);
}

function schedule(p) {
  if (!p.interval_seconds) return "manual";
  const s = p.interval_seconds;
  if (s % 86400 === 0) return `every ${s / 86400} d`;
  if (s % 3600 === 0) return `every ${s / 3600} h`;
  if (s % 60 === 0) return `every ${s / 60} min`;
  return `every ${s} s`;
}

/** Run a pipeline as a background job, reflecting progress on the button. */
async function runNow(p, btn, onDone) {
  return busy(btn, async () => {
    try {
      const { job } = await api.post(`/api/pipelines/${p.id}/run`);
      toast(`Started ${p.name}. You can leave this page; the run continues.`);
      const done = await waitForJob(job.id, { interval: 700 });
      if (done.status === "success") {
        const r = done.result;
        toast(`${p.name}: run #${r.run_id} finished, ${fmtInt(r.metrics.n_anomalies)} anomalous rows (${fmtPct(r.metrics.anomaly_rate)}).`, {
          action: { label: "Open run", run: () => { location.hash = `#/runs/${r.run_id}`; } }, timeout: 9000,
        });
      } else {
        toast(`${p.name} failed: ${done.error}`, { kind: "error", timeout: 12000 });
      }
      if (onDone) onDone(done);
    } catch (err) {
      toast(err.message, { kind: "error" });
    }
  });
}

// ---------------------------------------------------------------- list
function renderList(root) {
  setTitle("Pipelines");
  const slot = h("div", null, loading(5));
  const newBtn = button("New pipeline", { kind: "primary", icon: "plus" });
  const head = pageHead({ title: "Pipelines", lede: "Declarative YAML pipelines: source, schema, detectors, remediation, alerts and sink.", actions: [newBtn] });
  root.append(head, slot);
  let dirs = null;
  newBtn.addEventListener("click", () => createDrawer(dirs, load));

  async function load() {
    try {
      const data = await api.get("/api/pipelines");
      dirs = data;
      const list = data.pipelines;
      const where = h("p", { class: "muted small" }, "Scanning ", data.dirs.map((d, i) => [i ? ", " : "", h("code", null, d.path), d.exists ? "" : " (missing)"]), `. New pipelines are written to `, h("code", null, data.write_dir), ".");
      if (!list.length) {
        add(clear(slot), panel({ body: h("div", null, emptyState({ title: "No pipelines found", text: "Create one from a template, or point ANOMALYGUARD_PIPELINE_DIRS (or serve --pipeline-dir) at a folder of pipeline YAML files.", actions: [button("New pipeline", { kind: "primary", icon: "plus", onClick: () => createDrawer(dirs, load) })] }), where) }));
        return;
      }
      add(clear(slot), h("section", { class: "panel" },
        h("div", { class: "table-wrap" }, h("table", { class: "data" },
          h("thead", null, h("tr", null, ["Pipeline", "File", "Detectors", "Schedule", "Last run", "Runs", ""].map((t, i) => h("th", { class: i === 5 ? "r" : null }, t)))),
          h("tbody", null, list.map((p) => {
            const run = button("Run now", { small: true, icon: "play", disabled: !p.valid });
            run.addEventListener("click", (e) => { e.stopPropagation(); runNow(p, run, load); });
            const last = p.last_run;
            return h("tr", { class: "clickable", onClick: () => { location.hash = `#/pipelines/${p.id}`; } },
              h("td", null, h("a", { href: `#/pipelines/${p.id}` }, p.name || p.file), p.description ? h("div", { class: "small muted truncate", style: { maxWidth: "320px" } }, p.description) : null,
                p.valid ? null : h("div", { class: "small", style: { color: "var(--color-high)" } }, p.error)),
              h("td", { class: "mono small" }, p.file, h("div", { class: "muted" }, p.dir)),
              h("td", { class: "small" }, (p.detectors || []).join(", ")),
              h("td", { class: "nowrap" }, p.valid ? schedule(p) : chip("invalid", "failed")),
              h("td", { class: "nowrap" }, last ? h("span", { class: "row" }, chip(last.status), h("a", { href: `#/runs/${last.id}`, onClick: (e) => e.stopPropagation() }, timeEl(last.started_at))) : h("span", { class: "muted" }, "never")),
              h("td", { class: "r" }, fmtInt(p.runs || 0)),
              h("td", { class: "r" }, run));
          })))),
        h("div", { class: "panel-body" }, where)));
    } catch (err) {
      add(clear(slot), errorState(err, load));
    }
  }
  load();
}

// ---------------------------------------------------------------- create
async function createDrawer(dirs, onCreated) {
  const content = h("div", { class: "stack" }, loading(4));
  const createBtn = button("Create pipeline", { kind: "primary" });
  const d = drawer({ title: "New pipeline", sub: dirs ? `Written to ${dirs.write_dir}/<name>.yaml` : null, body: content, foot: [createBtn] });
  let templates;
  let datasets;
  try {
    [templates, datasets] = await Promise.all([api.get("/api/pipelines/templates"), api.get("/api/datasets")]);
  } catch (err) {
    add(clear(content), errorState(err));
    return;
  }
  const form = { template: "csv_quality", name: "", source: datasets[0] ? `dataset:${datasets[0].id}` : "", group_by: "", value_column: "", table: "", cursor: "" };
  const fieldsSlot = h("div", { class: "stack" });
  const err = h("div", { role: "alert" });
  const nameInput = h("input", { class: "input", placeholder: "orders_daily", required: true, pattern: "[A-Za-z0-9][A-Za-z0-9_.-]*", "aria-describedby": "name-hint" });
  nameInput.addEventListener("input", () => { form.name = nameInput.value.trim(); nameInput.removeAttribute("aria-invalid"); });

  function drawFields() {
    const t = templates.find((x) => x.name === form.template);
    clear(fieldsSlot);
    fieldsSlot.append(h("p", { class: "muted small" }, t.description));
    for (const f of t.fields) {
      if (f === "source") {
        const pathInput = h("input", { class: "input mono", placeholder: t.defaults.source || "data.csv", value: form.source.startsWith("dataset:") ? "" : form.source });
        const dsSel = select([{ value: "", label: "Type a path instead" }, ...datasets.map((x) => ({ value: `dataset:${x.id}`, label: `${x.name} (uploaded, ${fmtInt(x.rows)} rows)` }))], {
          value: form.source.startsWith("dataset:") ? form.source : "", label: "Uploaded dataset",
          onChange: (v) => { form.source = v || pathInput.value.trim(); pathInput.disabled = Boolean(v); },
        });
        pathInput.disabled = form.source.startsWith("dataset:");
        pathInput.addEventListener("input", () => { form.source = pathInput.value.trim(); });
        fieldsSlot.append(h("div", { class: "field" }, h("span", null, form.template === "database_quality" ? "Database" : "Source"),
          form.template === "database_quality" ? null : dsSel, pathInput,
          h("span", { class: "hint" }, form.template === "database_quality" ? "SQLite file path or a SQLAlchemy URL." : "Pick an uploaded file, or give a path relative to the pipeline file (or absolute).")));
      } else {
        const labels = { group_by: "Group by (optional)", value_column: "Value column", table: "Table", cursor: "Cursor column" };
        const inp = h("input", { class: "input mono", placeholder: t.defaults[f] || "", value: form[f] });
        inp.addEventListener("input", () => { form[f] = inp.value.trim(); });
        fieldsSlot.append(h("label", { class: "field" }, h("span", null, labels[f] || f), inp));
      }
    }
  }

  add(clear(content), 
    h("label", { class: "field" }, h("span", null, "Name"), nameInput, h("span", { class: "hint", id: "name-hint" }, "Letters, digits, dot, dash or underscore. Also the run and metrics key.")),
    h("label", { class: "field" }, h("span", null, "Template"), select(templates.map((t) => ({ value: t.name, label: t.name.replace("_", " ") })), { value: form.template, label: "Template", onChange: (v) => { form.template = v; drawFields(); } })),
    fieldsSlot, err);
  drawFields();
  if (!form.name) nameInput.focus();

  createBtn.addEventListener("click", () => busy(createBtn, async () => {
    clear(err);
    if (!form.name) { nameInput.setAttribute("aria-invalid", "true"); err.append(h("div", { class: "notice error" }, "Give the pipeline a name.")); nameInput.focus(); return; }
    try {
      const p = await api.post("/api/pipelines", { ...form, source: form.source || undefined });
      toast(`Created ${p.file}.`);
      d.close();
      if (onCreated) onCreated();
      location.hash = `#/pipelines/${p.id}`;
    } catch (e) {
      err.append(h("div", { class: "notice error" }, e.message));
    }
  }));
}

// ---------------------------------------------------------------- detail
function renderDetail(root, id) {
  setTitle("Pipeline");
  const body = h("div", { class: "stack" }, loading(6));
  root.append(body);
  let alive = true;

  async function load() {
    try {
      const p = await api.get(`/api/pipelines/${id}`);
      if (alive) draw(p);
    } catch (err) {
      add(clear(body), err.status === 404 ? emptyState({ title: "Pipeline not found", text: "The file may have been moved or renamed.", actions: [h("a", { class: "btn", href: "#/pipelines" }, "All pipelines")] }) : errorState(err, load));
    }
  }

  function draw(p) {
    setTitle(p.name || p.file);
    const runBtn = button("Run now", { kind: "primary", icon: "play", disabled: !p.valid });
    const jobSlot = h("div");
    runBtn.addEventListener("click", () => {
      add(clear(jobSlot), h("div", { class: "notice row" }, h("span", { class: "spinner" }), `Running ${p.name}`));
      runNow(p, runBtn, (job) => {
        clear(jobSlot);
        if (job.status !== "success") jobSlot.append(h("div", { class: "notice error", role: "alert" }, job.error));
        load();
      });
    });
    const editor = h("textarea", { class: "textarea", spellcheck: "false", rows: Math.min(40, Math.max(14, p.yaml.split("\n").length + 1)), "aria-label": "Pipeline YAML" });
    editor.value = p.yaml;
    const check = h("div", { "aria-live": "polite" });
    const validateBtn = button("Validate", {});
    const saveBtn = button("Save", { kind: "primary", disabled: true });
    const resetBtn = button("Discard changes", { kind: "ghost", disabled: true });
    editor.addEventListener("input", () => {
      const dirty = editor.value !== p.yaml;
      saveBtn.disabled = !dirty;
      resetBtn.disabled = !dirty;
      editor.removeAttribute("aria-invalid");
    });
    editor.addEventListener("keydown", (e) => {
      if (e.key === "Tab" && !e.shiftKey) { e.preventDefault(); editor.setRangeText("  ", editor.selectionStart, editor.selectionEnd, "end"); editor.dispatchEvent(new Event("input")); }
    });
    validateBtn.addEventListener("click", () => busy(validateBtn, async () => {
      try {
        const r = await api.post("/api/pipelines/validate", { yaml: editor.value });
        add(clear(check), r.valid
          ? h("div", { class: "notice" }, h("span", null, h("strong", null, "Valid. "), r.warnings && r.warnings.length ? `Warnings: ${r.warnings.join("; ")}` : "The pipeline config parses and every detector, rule and policy is known."))
          : h("div", { class: "notice error", role: "alert" }, r.error));
        if (!r.valid) editor.setAttribute("aria-invalid", "true");
      } catch (err) { toast(err.message, { kind: "error" }); }
    }));
    saveBtn.addEventListener("click", () => busy(saveBtn, async () => {
      try {
        await api.put(`/api/pipelines/${id}`, { yaml: editor.value });
        toast(`Saved ${p.file}.`);
        load();
      } catch (err) {
        add(clear(check), h("div", { class: "notice error", role: "alert" }, err.message));
        editor.setAttribute("aria-invalid", "true");
      }
    }));
    resetBtn.addEventListener("click", () => { editor.value = p.yaml; editor.dispatchEvent(new Event("input")); clear(check); });

    const runs = p.recent_runs || [];
    add(clear(body), 
      pageHead({
        title: p.name || p.file,
        crumbs: [{ label: "Pipelines", href: "#/pipelines" }, { label: p.file }],
        lede: p.description || p.path,
        actions: [runBtn],
      }),
      p.valid ? null : h("div", { class: "notice error", role: "alert" }, h("div", null, h("strong", null, "Invalid configuration. "), p.error)),
      jobSlot,
      h("div", { class: "grid grid-main-side" },
        panel({ title: "Configuration", sub: p.path, body: h("div", { class: "stack" }, editor, check, h("div", { class: "row" }, validateBtn, saveBtn, resetBtn)) }),
        h("div", { class: "stack" },
          panel({ title: "Summary", body: h("dl", { class: "kv" },
            h("dt", null, "Source"), h("dd", { class: "mono small" }, p.source || "-"),
            h("dt", null, "Detectors"), h("dd", null, (p.detectors || []).join(", ") || "-"),
            h("dt", null, "Remediation"), h("dd", null, p.remediation ? "on" : "report only"),
            h("dt", null, "Notifiers"), h("dd", null, (p.notifiers || []).join(", ") || "console (default)"),
            h("dt", null, "Schedule"), h("dd", null, p.valid ? schedule(p) : "-", h("div", { class: "small muted" }, "Scheduled runs need ", h("code", null, `anomalyguard run ${p.file} --schedule`))),
            h("dt", null, "Runs"), h("dd", null, fmtInt(p.runs || 0))) }),
          panel({ title: "Recent runs", flush: true, body: runs.length ? h("ul", { class: "list" }, runs.map((r) => h("li", null,
            h("div", { class: "grow" }, h("div", { class: "row" }, h("a", { href: `#/runs/${r.id}` }, `#${r.id}`), chip(r.status)),
              h("div", { class: "small muted" }, timeEl(r.started_at), ` · ${fmtInt(r.rows)} rows · ${fmtPct(r.anomaly_rate)} anomalous · ${fmtMs(r.duration_ms)}`))))) : emptyState({ title: "Never run", text: "Run it now, or from the CLI." }) }),
          (p.jobs || []).length ? panel({ title: "Jobs started here", flush: true, body: h("ul", { class: "list" }, p.jobs.map((j) => h("li", null,
            h("div", { class: "grow" }, h("div", { class: "row" }, chip(j.status), h("span", { class: "small" }, timeEl(j.created_at))),
              j.error ? h("div", { class: "small", style: { color: "var(--color-high)" } }, j.error) : j.result ? h("div", { class: "small muted" }, h("a", { href: `#/runs/${j.result.run_id}` }, `run #${j.result.run_id}`)) : null)))) }) : null)),
    );
    if (runs.some((r) => r.status === "running")) setTimeout(() => alive && load(), 2000);
  }

  load();
  return () => { alive = false; };
}


