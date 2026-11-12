// Review queue: server-side paging and filters, select-all, bulk actions and a detail drawer.

import { api } from "../api.js";
import {
  busy, button, chip, clear, closeDrawer, debounce, drawer, emptyState, errorState, fmtInt, fmtNum,
  fmtValue, h, loading, pageHead, pager, parseTyped, runLabel, segmented, select, setTitle,
  timeEl, toast,
} from "../ui.js";
import { add } from "../ui.js";
import { currentRoute, refreshBadge, setQuery } from "../app.js";

const STATUSES = [
  { value: "pending", label: "Pending" },
  { value: "approved", label: "Approved" },
  { value: "applied", label: "Applied" },
  { value: "rejected", label: "Rejected" },
  { value: "all", label: "All" },
];

export function render(root) {
  setTitle("Review queue");
  const q = currentRoute().query;
  const state = {
    status: q.status || "pending", pipeline: q.pipeline || "", column: q.column || "", detector: q.detector || "",
    run: q.run || "", q: q.q || "", offset: Number(q.offset) || 0, limit: Number(q.limit) || 25,
  };
  const selected = new Set();
  let allMatching = false;
  let lastTotal = 0;
  let pageIds = [];

  const counts = h("div", { class: "muted small" });
  const statusSeg = h("div");
  const pipeSel = select([{ value: "", label: "All sources" }], { value: state.pipeline, label: "Source", onChange: (v) => { state.pipeline = v; reset(); } });
  const colSel = select([{ value: "", label: "All columns" }], { value: state.column, label: "Column", onChange: (v) => { state.column = v; reset(); } });
  const detSel = select([{ value: "", label: "All detectors" }], { value: state.detector, label: "Detector", onChange: (v) => { state.detector = v; reset(); } });
  const search = h("input", { class: "input search", type: "search", placeholder: "Search reason, value or row", value: state.q, "aria-label": "Search review items" });
  search.addEventListener("input", debounce(() => { state.q = search.value.trim(); reset(); }, 300));
  const runNote = h("div");
  const bulkSlot = h("div");
  const tableSlot = h("div", null, loading(6));

  root.append(
    pageHead({ title: "Review queue", lede: "Values the remediation could not fix safely. Approve a suggested or edited value, reject to keep the original, or mark a false positive to teach the detector." }),
    h("section", { class: "panel" },
      h("div", { class: "panel-body stack", style: { gap: "12px" } },
        h("div", { class: "row spread" }, statusSeg, counts),
        h("div", { class: "filters", role: "toolbar", "aria-label": "Review filters" }, pipeSel, colSel, detSel, search),
        runNote),
      bulkSlot,
      tableSlot));

  function filters() {
    return { status: state.status, pipeline: state.pipeline, column: state.column, detector: state.detector, run_id: state.run || undefined, q: state.q };
  }
  function reset() { state.offset = 0; selected.clear(); allMatching = false; load(); }

  async function loadFacets() {
    try {
      const f = await api.get("/api/review/facets", { status: state.status });
      const c = f.counts;
      add(clear(statusSeg), segmented(STATUSES.map((s) => ({ value: s.value, label: s.value === "all" ? "All" : `${s.label} ${fmtInt(c[s.value] || 0)}` })), state.status, (v) => { state.status = v; reset(); loadFacets(); }, "Status"));
      counts.textContent = `${fmtInt(Object.values(c).reduce((a, b) => a + b, 0))} items in total`;
      const fill = (sel, items, cur, label) => {
        add(clear(sel), h("option", { value: "" }, label));
        for (const it of items) sel.append(h("option", { value: it.value, selected: it.value === cur }, `${it.value.startsWith("analysis:") ? `${runLabel(it.value)} (analysis)` : it.value} · ${fmtInt(it.count)}`));
        if (cur && !items.some((i) => i.value === cur)) sel.append(h("option", { value: cur, selected: true }, cur.startsWith("analysis:") ? `${runLabel(cur)} (analysis)` : cur));
      };
      fill(pipeSel, f.pipelines, state.pipeline, "All sources");
      fill(colSel, f.columns, state.column, "All columns");
      fill(detSel, f.detectors, state.detector, "All detectors");
    } catch { /* filters stay usable with what they have */ }
  }

  function bulkBar() {
    clear(bulkSlot);
    const n = allMatching ? lastTotal : selected.size;
    if (!n) return;
    const allOnPage = pageIds.length && pageIds.every((id) => selected.has(id));
    const act = (action, label, kind) => {
      const b = button(label, { small: true, kind });
      b.addEventListener("click", () => busy(b, () => runBulk(action)));
      return b;
    };
    bulkSlot.append(h("div", { class: "bulkbar", role: "region", "aria-label": "Bulk actions" },
      h("span", { class: "grow" },
        h("strong", null, `${fmtInt(n)} selected`),
        allOnPage && !allMatching && lastTotal > pageIds.length
          ? h("span", null, " · ", h("button", { class: "link-btn", type: "button", onClick: () => {
            allMatching = true;
            for (const cb of tableSlot.querySelectorAll("tbody input[type=checkbox]")) { cb.checked = true; cb.closest("tr").classList.add("is-selected"); }
            bulkBar();
          } }, `Select all ${fmtInt(lastTotal)} matching`))
          : null,
        allMatching ? h("span", null, " · every item matching the filters · ", h("button", { class: "link-btn", type: "button", onClick: () => { allMatching = false; selected.clear(); load(); } }, "Clear")) : null),
      act("approve", "Approve", "primary"),
      act("reject", "Reject"),
      act("apply", "Apply to cleaned data"),
      act("false_positive", "Mark false positive")));
  }

  async function runBulk(action) {
    const body = { action };
    if (allMatching) { body.all_matching = true; body.filter = filters(); } else body.ids = [...selected];
    try {
      const r = await api.post("/api/review/bulk", body);
      const parts = [`${fmtInt(r.updated)} updated`];
      if (r.applied) parts.push(`${fmtInt(r.applied)} written to cleaned data`);
      if (r.not_applicable) parts.push(`${fmtInt(r.not_applicable)} not written (row-level flags, dropped rows, or a run without a cleaned file)`);
      if (r.skipped) parts.push(`${fmtInt(r.skipped)} skipped (not pending)`);
      toast(`${action.replace("_", " ")}: ${parts.join(", ")}.`);
      selected.clear();
      allMatching = false;
      load();
      loadFacets();
      refreshBadge();
    } catch (err) {
      toast(err.message, { kind: "error" });
    }
  }

  async function load() {
    setQuery({ status: state.status === "pending" ? "" : state.status, pipeline: state.pipeline, column: state.column, detector: state.detector, run: state.run, q: state.q, offset: state.offset || "", limit: state.limit === 25 ? "" : state.limit });
    clear(runNote);
    if (state.run) runNote.append(h("div", { class: "notice" }, h("span", { class: "grow" }, `Showing items from run #${state.run}. `), h("button", { class: "btn sm", type: "button", onClick: () => { state.run = ""; reset(); } }, "Show all runs")));
    tableSlot.setAttribute("aria-busy", "true");
    try {
      const { items, total } = await api.list("/api/review", { ...filters(), offset: state.offset, limit: state.limit });
      lastTotal = total;
      pageIds = items.map((i) => i.id);
      if (!total) {
        add(clear(tableSlot), state.status === "pending" && !state.pipeline && !state.column && !state.detector && !state.q && !state.run
          ? emptyState({ title: "Nothing to review", text: "Flagged values from pipelines and analyses appear here.", actions: [h("a", { class: "btn", href: "#/analyze" }, "Analyze a file")] })
          : emptyState({ title: "No items match these filters" }));
        bulkBar();
        return;
      }
      const headCheck = h("input", { type: "checkbox", "aria-label": "Select every item on this page" });
      const syncHead = () => {
        const on = pageIds.filter((id) => selected.has(id)).length;
        headCheck.checked = allMatching || (on === pageIds.length && on > 0);
        headCheck.indeterminate = !allMatching && on > 0 && on < pageIds.length;
      };
      headCheck.addEventListener("change", () => {
        allMatching = false;
        for (const id of pageIds) { if (headCheck.checked) selected.add(id); else selected.delete(id); }
        for (const cb of tableSlot.querySelectorAll("tbody input[type=checkbox]")) { cb.checked = headCheck.checked; cb.closest("tr").classList.toggle("is-selected", cb.checked); }
        bulkBar();
      });
      const rows = items.map((it) => {
        const cb = h("input", { type: "checkbox", checked: allMatching || selected.has(it.id), "aria-label": `Select item ${it.id}` });
        const tr = h("tr", { class: ["clickable", (allMatching || selected.has(it.id)) && "is-selected"] },
          h("td", { class: "check-cell" }, cb),
          h("td", { class: "mono muted" }, `#${it.id}`),
          h("td", null, chip(it.status)),
          h("td", { class: "truncate", style: { maxWidth: "180px" }, title: it.pipeline || "" }, runLabel(it.pipeline || "-")),
          h("td", { class: "mono" }, String(it.row_index ?? "-")),
          h("td", { class: "mono" }, it.column || "(row)"),
          h("td", { class: "value-cell" }, fmtValue(it.value)),
          h("td", { class: "value-cell" }, it.status === "pending" ? (it.suggestion === null || it.suggestion === undefined ? h("span", { class: "muted" }, "-") : fmtValue(it.suggestion)) : fmtValue(it.resolved_value)),
          h("td", { class: "mono small nowrap" }, it.detector || "-"),
          h("td", { class: "reason" }, h("span", { class: "text", title: it.reason }, it.reason)));
        cb.addEventListener("click", (e) => e.stopPropagation());
        cb.addEventListener("change", () => {
          if (allMatching) { allMatching = false; for (const id of pageIds) selected.add(id); }
          if (cb.checked) selected.add(it.id); else selected.delete(it.id);
          tr.classList.toggle("is-selected", cb.checked);
          syncHead();
          bulkBar();
        });
        tr.addEventListener("click", () => openItem(it.id));
        return tr;
      });
      add(clear(tableSlot), 
        h("div", { class: "table-wrap" }, h("table", { class: "data" },
          h("thead", null, h("tr", null, h("th", { class: "check-cell" }, headCheck), ...["Id", "Status", "Source", "Row", "Column", "Value", "Suggested / final", "Detector", "Reason"].map((t) => h("th", null, t)))),
          h("tbody", null, rows))),
        pager({ offset: state.offset, limit: state.limit, total, noun: "items", sizes: [25, 50, 100], onChange: (o, l) => { state.offset = o; state.limit = l; if (!allMatching) selected.clear(); load(); } }));
      syncHead();
      bulkBar();
    } catch (err) {
      add(clear(tableSlot), errorState(err, load));
    } finally {
      tableSlot.removeAttribute("aria-busy");
    }
  }

  async function openItem(id) {
    const content = h("div", { class: "stack" }, loading(5));
    const d = drawer({ title: `Review item #${id}`, body: content });
    try {
      const data = await api.get(`/api/review/${id}`);
      const it = data.item;
      const initial = it.status === "pending" ? (it.suggestion ?? it.value) : it.resolved_value;
      const input = h("input", { class: "input mono", value: initial === null || initial === undefined ? "" : String(initial), "aria-describedby": "final-hint" });
      const note = h("input", { class: "input", placeholder: "Optional note", "aria-label": "Reviewer note" });
      const pending = it.status === "pending";
      add(clear(content), 
        h("div", { class: "row" }, chip(it.status), it.detector ? chip(it.detector, "accent") : null),
        h("dl", { class: "kv" },
          h("dt", null, "Source"), h("dd", null, it.run_id ? h("a", { href: `#/runs/${it.run_id}` }, `${runLabel(it.pipeline)} · run #${it.run_id}`) : runLabel(it.pipeline || "-")),
          h("dt", null, "Row"), h("dd", { class: "mono" }, String(it.row_index ?? "-")),
          h("dt", null, "Column"), h("dd", { class: "mono" }, it.column || "(whole row)"),
          h("dt", null, "Value"), h("dd", { class: "mono" }, fmtValue(it.value)),
          h("dt", null, "Suggestion"), h("dd", { class: "mono" }, it.suggestion === null || it.suggestion === undefined ? "none" : `${fmtValue(it.suggestion)}${it.suggestion_confidence ? ` (confidence ${fmtNum(it.suggestion_confidence, 2)})` : ""}`),
          h("dt", null, "Created"), h("dd", null, timeEl(it.created_at)),
          it.resolved_at ? [h("dt", null, "Resolved"), h("dd", null, timeEl(it.resolved_at), it.reviewer_note ? ` · ${it.reviewer_note}` : "")] : null),
        h("div", { class: "stack", style: { gap: "4px" } }, h("div", { class: "label" }, "Reason"), h("p", null, it.reason)),
        it.column ? h("label", { class: "field" }, h("span", null, "Final value"), input, h("span", { class: "hint", id: "final-hint" }, pending ? "Approve writes this value. Numbers are stored as numbers; leave empty for null." : "Already resolved.")) : null,
        pending ? note : null,
        data.findings.length ? h("div", { class: "stack", style: { gap: "6px" } }, h("div", { class: "label" }, "Findings on this row"),
          h("ul", { class: "list panel" }, data.findings.map((f) => h("li", null, h("div", { class: "grow" },
            h("div", { class: "row" }, h("span", { class: "mono small" }, f.detector), chip(f.severity), h("span", { class: "mono small muted" }, f.column || "(row)")),
            h("p", { class: "small", style: { marginTop: "4px" } }, f.reason)))))) : null,
        data.row ? h("div", { class: "stack", style: { gap: "6px" } }, h("div", { class: "label" }, "Full row"),
          h("div", { class: "table-wrap panel" }, h("table", { class: "data" }, h("tbody", null, Object.entries(data.row).map(([k, v]) => h("tr", { class: k === it.column ? "is-selected" : null }, h("td", { class: "mono" }, k), h("td", { class: "value-cell" }, fmtValue(v)))))))) : null,
      );
      if (pending) {
        const approve = button("Approve", { kind: "primary", icon: "check" });
        const reject = button("Reject (keep original)", { icon: "x" });
        const fp = button("False positive", { icon: "thumbsdown" });
        const after = (msg) => { selected.delete(id); toast(msg); d.close(); load(); loadFacets(); refreshBadge(); };
        approve.addEventListener("click", () => busy(approve, async () => {
          try { await api.post(`/api/review/${id}/approve`, { value: it.column ? parseTyped(input.value) : null, note: note.value || null }); after(`Approved #${id}.`); } catch (err) { toast(err.message, { kind: "error" }); }
        }));
        reject.addEventListener("click", () => busy(reject, async () => {
          try { await api.post(`/api/review/${id}/reject`, { note: note.value || null }); after(`Rejected #${id}; the original value stays.`); } catch (err) { toast(err.message, { kind: "error" }); }
        }));
        fp.addEventListener("click", () => busy(fp, async () => {
          try {
            const r = await api.post(`/api/review/${id}/false-positive`, { note: note.value || null });
            after(r.feedback.length ? `Recorded a false positive for ${it.detector}.` : `Rejected #${id}. ${it.detector || "This check"} is not a tunable detector, so no feedback was recorded.`);
          } catch (err) { toast(err.message, { kind: "error" }); }
        }));
        d.el.append(h("div", { class: "drawer-foot" }, approve, reject, fp));
      } else if (it.status === "approved") {
        const apply = button("Apply to cleaned data", { kind: "primary" });
        apply.addEventListener("click", () => busy(apply, async () => {
          try {
            const r = await api.post("/api/review/bulk", { action: "apply", ids: [id] });
            toast(r.applied ? `Wrote #${id} into the cleaned file.` : "This item's run has no cleaned file to write to.");
            d.close(); load(); loadFacets();
          } catch (err) { toast(err.message, { kind: "error" }); }
        }));
        d.el.append(h("div", { class: "drawer-foot" }, apply));
      }
    } catch (err) {
      add(clear(content), errorState(err, () => openItem(id)));
    }
  }

  loadFacets();
  load();
  return () => closeDrawer();
}

