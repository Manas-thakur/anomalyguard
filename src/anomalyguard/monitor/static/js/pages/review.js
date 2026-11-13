// Review inbox: a keyboard-first split view. The list (server-side paging and
// filters) is on the left, the open item on the right; on a phone the item opens
// as a sheet. j/k move, a approve, r reject, m mark normal, e edit, x select,
// Shift+click selects a range, and a bulk bar appears while items are selected.

import { api } from "../api.js";
import {
  add, busy, button, chip, clear, debounce, emptyState, errorState, fmtInt, fmtNum, fmtValue, h,
  icon, loading, pageHead, parseTyped, runLabel, segmented, select, setTitle, timeEl, toast,
} from "../ui.js";
import { currentRoute, refreshBadge, setQuery, typingTarget } from "../app.js";

const STATUSES = [
  { value: "pending", label: "Pending" },
  { value: "approved", label: "Approved" },
  { value: "applied", label: "Applied" },
  { value: "rejected", label: "Rejected" },
  { value: "all", label: "All" },
];
const NARROW = "(max-width: 860px)";

const show = (v) => (v === null || v === undefined ? "null" : fmtValue(v));

export function render(root) {
  setTitle("Review inbox");
  const q = currentRoute().query;
  const state = {
    status: q.status || "pending", pipeline: q.pipeline || "", column: q.column || "", detector: q.detector || "",
    run: q.run || "", q: q.q || "", offset: Number(q.offset) || 0, limit: Number(q.limit) || 50,
  };
  const selected = new Set();
  let allMatching = false;
  let total = 0;
  let items = [];
  let active = -1;
  let anchor = -1;
  let detail = null; // { id, input, item }
  let seq = 0;

  const statusSlot = h("div");
  const pipeSel = select([{ value: "", label: "All sources" }], { value: state.pipeline, label: "Source", cls: "select sm", onChange: (v) => { state.pipeline = v; reset(); } });
  const colSel = select([{ value: "", label: "All columns" }], { value: state.column, label: "Column", cls: "select sm", onChange: (v) => { state.column = v; reset(); } });
  const detSel = select([{ value: "", label: "All detectors" }], { value: state.detector, label: "Detector", cls: "select sm", onChange: (v) => { state.detector = v; reset(); } });
  const search = h("input", { class: "input sm search", type: "search", placeholder: "Search  /", value: state.q, "aria-label": "Search review items" });
  search.addEventListener("input", debounce(() => { state.q = search.value.trim(); reset(); }, 300));
  const runNote = h("div");
  const headCheck = h("input", { type: "checkbox", "aria-label": "Select every item on this page" });
  const listCount = h("span", { class: "muted small num" });
  const listEl = h("ul", { class: "inbox-list", role: "listbox", "aria-label": "Review items", "aria-multiselectable": "true", tabindex: "0" });
  const pagerEl = h("div", { class: "inbox-pager" });
  const bulkSlot = h("div", { class: "bulk-slot" });
  const detailEl = h("section", { class: "inbox-detail", "aria-label": "Item details", tabindex: "-1" }, emptyDetail());
  const sheetClose = h("button", { class: "btn ghost icon-only sheet-close", type: "button", "aria-label": "Close item" }, icon("close"));
  sheetClose.addEventListener("click", () => closeSheet());
  const detailWrap = h("div", { class: "inbox-pane" }, sheetClose, detailEl);
  const scrim = h("div", { class: "sheet-scrim", "aria-hidden": "true" });
  scrim.addEventListener("click", () => closeSheet());

  root.classList.add("page-inbox");
  root.append(
    pageHead({ title: "Review inbox", lede: "Values a fix could not settle safely. Approve the suggested or edited value, reject to keep the original, or mark as normal to teach the detector. Press ? for shortcuts." }),
    h("div", { class: "inbox-filters", role: "toolbar", "aria-label": "Review filters" }, statusSlot, h("div", { class: "filters" }, pipeSel, colSel, detSel, search)),
    runNote,
    h("div", { class: "inbox" },
      h("div", { class: "inbox-col" },
        h("div", { class: "inbox-head" }, h("label", { class: "check" }, headCheck, h("span", { class: "sr-only" }, "Select page")), listCount),
        bulkSlot, listEl, pagerEl),
      detailWrap),
    scrim,
  );

  function filters() {
    return { status: state.status, pipeline: state.pipeline, column: state.column, detector: state.detector, run_id: state.run || undefined, q: state.q };
  }
  function reset() { state.offset = 0; selected.clear(); allMatching = false; active = -1; load(); }

  async function loadFacets() {
    try {
      const f = await api.get("/api/review/facets", { status: state.status });
      const c = f.counts;
      add(clear(statusSlot), segmented(STATUSES.map((st) => ({ value: st.value, label: st.value === "all" ? "All" : `${st.label} ${fmtInt(c[st.value] || 0)}` })), state.status, (v) => { state.status = v; reset(); loadFacets(); }, "Status"));
      const fill = (sel, list, cur, label) => {
        add(clear(sel), h("option", { value: "" }, label));
        for (const it of list) sel.append(h("option", { value: it.value, selected: it.value === cur }, `${runLabel(it.value)} · ${fmtInt(it.count)}`));
        if (cur && !list.some((i) => i.value === cur)) sel.append(h("option", { value: cur, selected: true }, runLabel(cur)));
      };
      fill(pipeSel, f.pipelines, state.pipeline, "All sources");
      fill(colSel, f.columns, state.column, "All columns");
      fill(detSel, f.detectors, state.detector, "All detectors");
    } catch { /* filters keep what they have */ }
  }

  // ------------------------------------------------------------ list
  async function load({ keep = false, quiet = false } = {}) {
    const mine = ++seq;
    setQuery({ status: state.status === "pending" ? "" : state.status, pipeline: state.pipeline, column: state.column, detector: state.detector, run: state.run, q: state.q, offset: state.offset || "", limit: state.limit === 50 ? "" : state.limit });
    clear(runNote);
    if (state.run) runNote.append(h("div", { class: "notice" }, h("span", { class: "grow" }, `Showing items from run #${state.run}.`), h("button", { class: "btn sm", type: "button", onClick: () => { state.run = ""; reset(); } }, "Show all runs")));
    listEl.setAttribute("aria-busy", "true");
    if (!keep && !quiet) add(clear(listEl), h("li", { class: "inbox-loading" }, loading(6)));
    try {
      const res = await api.list("/api/review", { ...filters(), offset: state.offset, limit: state.limit });
      if (mine !== seq) return;
      items = res.items;
      total = res.total;
      if (state.offset && !items.length && total) { state.offset = Math.max(0, state.offset - state.limit); load(); return; }
      if (active >= items.length) active = items.length - 1;
      if (active < 0 && items.length && !window.matchMedia(NARROW).matches) active = 0;
      drawList();
      if (active >= 0 && (!detail || detail.id !== items[active].id || keep)) openItem(active, { focusList: false });
      if (!items.length) setDetail(emptyDetail());
    } catch (err) {
      add(clear(listEl), h("li", null, errorState(err, load)));
    } finally {
      listEl.removeAttribute("aria-busy");
    }
  }

  function drawList() {
    clear(listEl);
    const from = total ? state.offset + 1 : 0;
    const to = Math.min(state.offset + state.limit, total);
    listCount.textContent = total ? `${fmtInt(from)}–${fmtInt(to)} of ${fmtInt(total)}` : "0 items";
    if (!items.length) {
      const filtered = state.pipeline || state.column || state.detector || state.q || state.run;
      listEl.append(h("li", { class: "inbox-empty" }, filtered || state.status !== "pending"
        ? emptyState({ title: "No items match these filters" })
        : emptyState({ title: "Inbox zero", text: "Values a fix could not settle appear here. Confirm an incident or preview a fix in Analyze to queue some.", actions: [h("a", { class: "btn", href: "#/health" }, "See incidents")] })));
    }
    items.forEach((it, i) => {
      const sel = allMatching || selected.has(it.id);
      const cb = h("input", { type: "checkbox", checked: sel, tabindex: "-1", "aria-label": `Select item ${it.id}` });
      const after = it.status === "pending" ? it.suggestion : it.resolved_value;
      const li = h("li", {
        id: `ri-${it.id}`, role: "option", "aria-selected": String(i === active),
        class: ["inbox-item", i === active && "is-active", sel && "is-selected", `st-${it.status}`],
      },
      h("span", { class: "cb" }, cb),
      h("span", { class: "body" },
        h("span", { class: "line1" },
          h("span", { class: "col mono" }, it.column || "whole row"),
          it.column ? h("span", { class: "val mono" }, show(it.value)) : h("span", { class: "val" }, "unusual combination"),
          it.column && after !== null && after !== undefined ? [h("span", { class: "arrow", "aria-hidden": "true" }, "→"), h("span", { class: "val after mono" }, show(after))] : null),
        h("span", { class: "line2" }, [runLabel(it.pipeline || "-"), `row ${it.row_index ?? "-"}`, it.detector].filter(Boolean).join(" · "))),
      it.status !== "pending" ? h("span", { class: ["st", it.status] }, it.status) : null);
      cb.addEventListener("click", (e) => { e.stopPropagation(); toggleSelect(i, e.shiftKey); });
      li.addEventListener("click", (e) => {
        if (e.shiftKey) { e.preventDefault(); toggleSelect(i, true); return; }
        if (e.metaKey || e.ctrlKey) { toggleSelect(i, false); return; }
        openItem(i, { sheet: true });
      });
      listEl.append(li);
    });
    if (active >= 0) listEl.setAttribute("aria-activedescendant", `ri-${items[active]?.id}`);
    syncHead();
    drawPager();
    drawBulk();
  }

  function drawPager() {
    clear(pagerEl);
    if (total <= state.limit) return;
    const page = Math.floor(state.offset / state.limit) + 1;
    const pages = Math.ceil(total / state.limit);
    pagerEl.append(
      h("button", { class: "btn sm icon-only", type: "button", "aria-label": "Previous page", disabled: state.offset <= 0, onClick: () => { state.offset = Math.max(0, state.offset - state.limit); active = 0; if (!allMatching) selected.clear(); load(); } }, icon("left")),
      h("span", { class: "num small muted" }, `Page ${page} of ${pages}`),
      h("button", { class: "btn sm icon-only", type: "button", "aria-label": "Next page", disabled: state.offset + state.limit >= total, onClick: () => { state.offset += state.limit; active = 0; if (!allMatching) selected.clear(); load(); } }, icon("right")));
  }

  function syncHead() {
    const on = items.filter((it) => selected.has(it.id)).length;
    headCheck.checked = allMatching || (on === items.length && on > 0);
    headCheck.indeterminate = !allMatching && on > 0 && on < items.length;
  }
  headCheck.addEventListener("change", () => {
    allMatching = false;
    for (const it of items) { if (headCheck.checked) selected.add(it.id); else selected.delete(it.id); }
    paintSelection();
  });

  function toggleSelect(i, range) {
    if (allMatching) { allMatching = false; for (const it of items) selected.add(it.id); }
    if (range && anchor >= 0) {
      const [a, b] = anchor < i ? [anchor, i] : [i, anchor];
      for (let k = a; k <= b; k += 1) selected.add(items[k].id);
    } else {
      const id = items[i].id;
      if (selected.has(id)) selected.delete(id); else selected.add(id);
      anchor = i;
    }
    paintSelection();
  }

  function paintSelection() {
    items.forEach((it) => {
      const li = document.getElementById(`ri-${it.id}`);
      if (!li) return;
      const on = allMatching || selected.has(it.id);
      li.classList.toggle("is-selected", on);
      li.querySelector("input").checked = on;
    });
    syncHead();
    drawBulk();
  }

  function drawBulk() {
    clear(bulkSlot);
    const n = allMatching ? total : selected.size;
    bulkSlot.hidden = !n;
    if (!n) return;
    const pending = state.status === "pending" || state.status === "all";
    const act = (action, label, kbd, kind) => {
      const b = h("button", { class: ["btn", "sm", kind], type: "button" }, label, kbd ? h("kbd", null, kbd) : null);
      b.addEventListener("click", () => busy(b, () => runBulk(action)));
      return b;
    };
    const allOnPage = items.length && items.every((it) => selected.has(it.id));
    bulkSlot.append(h("div", { class: "bulkbar", role: "region", "aria-label": "Bulk actions" },
      h("div", { class: "bulk-count" },
        h("strong", null, `${fmtInt(n)} selected`),
        allOnPage && !allMatching && total > items.length
          ? h("button", { class: "link-btn", type: "button", onClick: () => { allMatching = true; paintSelection(); } }, `Select all ${fmtInt(total)}`)
          : null,
        h("button", { class: "link-btn", type: "button", onClick: () => { allMatching = false; selected.clear(); paintSelection(); } }, "Clear")),
      h("div", { class: "bulk-actions" },
        pending ? act("approve", "Approve", "a", "primary") : null,
        pending ? act("reject", "Reject", "r") : null,
        pending ? act("false_positive", "Mark normal", "m") : null,
        act("apply", "Apply to cleaned data"))));
  }

  async function runBulk(action) {
    const body = { action };
    if (allMatching) { body.all_matching = true; body.filter = filters(); } else body.ids = [...selected];
    try {
      const r = await api.post("/api/review/bulk", body);
      const parts = [`${fmtInt(r.updated)} updated`];
      if (r.applied) parts.push(`${fmtInt(r.applied)} written to cleaned data`);
      if (r.not_applicable) parts.push(`${fmtInt(r.not_applicable)} not written (no cleaned file for that run)`);
      if (r.skipped) parts.push(`${fmtInt(r.skipped)} skipped (not pending)`);
      toast(`${{ approve: "Approved", reject: "Rejected", false_positive: "Marked normal", apply: "Applied" }[action]}: ${parts.join(", ")}.`);
      selected.clear();
      allMatching = false;
      load({ keep: true });
      loadFacets();
      refreshBadge();
    } catch (err) {
      toast(err.message, { kind: "error" });
    }
  }

  // ------------------------------------------------------------ detail
  function emptyDetail() {
    return h("div", { class: "inbox-placeholder" },
      h("p", { class: "muted" }, "Select an item to review it."),
      h("dl", { class: "keys-hint" },
        ...[["j k", "move"], ["a", "approve"], ["r", "reject"], ["m", "mark normal"], ["e", "edit value"], ["x", "select"]].flatMap(([k, v]) => [
          h("dt", null, k.split(" ").map((x) => h("kbd", null, x))), h("dd", null, v)])));
  }
  function setDetail(node) { detailEl.replaceChildren(node); }

  function openItem(i, { sheet = false, focusList = true } = {}) {
    if (i < 0 || i >= items.length) return;
    active = i;
    if (!selected.size) anchor = i;
    for (const li of listEl.querySelectorAll(".inbox-item")) {
      const on = li.id === `ri-${items[i].id}`;
      li.classList.toggle("is-active", on);
      li.setAttribute("aria-selected", String(on));
      if (on) li.scrollIntoView({ block: "nearest" });
    }
    listEl.setAttribute("aria-activedescendant", `ri-${items[i].id}`);
    if (focusList && document.activeElement !== listEl && !sheet) listEl.focus({ preventScroll: true });
    if (sheet && window.matchMedia(NARROW).matches) openSheet();
    showDetail(items[i].id);
  }

  function openSheet() {
    detailWrap.classList.add("is-open");
    scrim.classList.add("is-open");
    document.body.classList.add("sheet-open");
    sheetClose.focus({ preventScroll: true });
  }
  function closeSheet() {
    if (!detailWrap.classList.contains("is-open")) return false;
    detailWrap.classList.remove("is-open");
    scrim.classList.remove("is-open");
    document.body.classList.remove("sheet-open");
    const li = items[active] && document.getElementById(`ri-${items[active].id}`);
    if (li) li.focus?.();
    listEl.focus({ preventScroll: true });
    return true;
  }

  async function showDetail(id) {
    const mine = id;
    detail = { id, input: null, item: null };
    setDetail(h("div", { class: "inbox-detail-body" }, loading(5)));
    let data;
    try {
      data = await api.get(`/api/review/${id}`);
    } catch (err) {
      setDetail(errorState(err, () => showDetail(id)));
      return;
    }
    if (!detail || detail.id !== mine) return;
    const it = data.item;
    const pending = it.status === "pending";
    const initial = pending ? (it.suggestion ?? it.value) : it.resolved_value;
    const input = h("input", { class: "input mono", id: "final-value", value: initial === null || initial === undefined ? "" : String(initial), "aria-describedby": "final-hint", disabled: !pending });
    const note = h("input", { class: "input sm", placeholder: "Optional note", "aria-label": "Reviewer note" });
    detail = { id, input, item: it, note };
    const actions = h("div", { class: "detail-actions" });
    if (pending) {
      const approve = h("button", { class: "btn primary", type: "button" }, icon("check"), "Approve", h("kbd", null, "a"));
      const reject = h("button", { class: "btn", type: "button" }, icon("x"), "Reject", h("kbd", null, "r"));
      const fp = h("button", { class: "btn", type: "button" }, icon("thumbsdown"), "Mark normal", h("kbd", null, "m"));
      approve.addEventListener("click", () => busy(approve, () => single("approve")));
      reject.addEventListener("click", () => busy(reject, () => single("reject")));
      fp.addEventListener("click", () => busy(fp, () => single("false_positive")));
      actions.append(approve, reject, fp);
    } else if (it.status === "approved") {
      const apply = button("Apply to cleaned data", { kind: "primary" });
      apply.addEventListener("click", () => busy(apply, async () => {
        try {
          const r = await api.post("/api/review/bulk", { action: "apply", ids: [id] });
          toast(r.applied ? `Wrote #${id} into the cleaned file.` : "This item's run has no cleaned file to write to.");
          load({ keep: true });
          loadFacets();
        } catch (err) { toast(err.message, { kind: "error" }); }
      }));
      actions.append(apply);
    }
    setDetail(h("div", { class: "inbox-detail-body" },
      h("header", { class: "detail-head" },
        h("div", { class: "row" }, chip(it.status), it.detector ? h("span", { class: "mono small muted" }, it.detector) : null, h("span", { class: "small muted" }, "· ", timeEl(it.created_at))),
        h("h2", { class: "mono" }, `${it.column || "whole row"}`, h("span", { class: "muted" }, ` · row ${it.row_index ?? "-"}`)),
        h("p", { class: "small muted" }, it.run_id ? h("a", { href: `#/runs/${it.run_id}` }, `${runLabel(it.pipeline)} · run #${it.run_id}`) : runLabel(it.pipeline || "-"))),
      h("div", { class: "compare" },
        h("div", null, h("div", { class: "label" }, "Current value"), h("div", { class: "big mono" }, show(it.value))),
        h("div", null, h("div", { class: "label" }, pending ? "Suggested" : "Final"),
          pending && (it.suggestion === null || it.suggestion === undefined)
            ? h("div", { class: "big muted" }, "No suggestion")
            : h("div", { class: "big mono after" }, show(pending ? it.suggestion : it.resolved_value)),
          pending && it.suggestion_confidence ? h("div", { class: "small muted" }, `confidence ${fmtNum(it.suggestion_confidence, 2)}`) : null)),
      h("p", { class: "reason" }, it.reason),
      it.column ? h("label", { class: "field" }, h("span", null, "Final value ", h("kbd", null, "e")), input,
        h("span", { class: "hint", id: "final-hint" }, pending ? "Approve writes this value. Numbers are stored as numbers; leave empty for null. Enter approves." : it.reviewer_note ? `Note: ${it.reviewer_note}` : "Already resolved.")) : null,
      pending ? note : null,
      actions,
      data.findings.length ? h("div", { class: "stack", style: { gap: "8px" } }, h("div", { class: "label" }, "Findings on this row"),
        h("ul", { class: "list boxed" }, data.findings.map((f) => h("li", null, h("div", { class: "grow" },
          h("div", { class: "row" }, chip(f.severity), h("span", { class: "mono small" }, f.column || "(row)"), h("span", { class: "mono small muted" }, f.detector)),
          h("p", { class: "small", style: { marginTop: "4px" } }, f.reason)))))) : null,
      data.row ? h("details", { class: "row-details", open: !window.matchMedia(NARROW).matches }, h("summary", { class: "label" }, "Full row"),
        h("div", { class: "table-wrap" }, h("table", { class: "data kvtable" }, h("tbody", null, Object.entries(data.row).map(([k, v]) => h("tr", { class: k === it.column ? "is-selected" : null }, h("th", { scope: "row", class: "mono" }, k), h("td", { class: "value-cell" }, show(v)))))))) : null,
    ));
    input.addEventListener("keydown", (e) => {
      if (e.key === "Enter" && pending) { e.preventDefault(); single("approve"); }
      if (e.key === "Escape") { e.preventDefault(); input.blur(); listEl.focus({ preventScroll: true }); }
    });
  }

  let inflight = false;
  async function single(action) {
    // act on the open item; if its details are still loading, the list row has what we need
    const loaded = detail && detail.item && items[active] && detail.id === items[active].id;
    const it = loaded ? detail.item : items[active];
    if (!it || inflight) return;
    if (it.status !== "pending") { toast(`#${it.id} is already ${it.status}.`); return; }
    const id = it.id;
    const note = loaded ? detail.note?.value || null : null;
    const value = !it.column ? null : loaded && detail.input ? parseTyped(detail.input.value) : (it.suggestion ?? it.value);
    inflight = true;
    try {
      if (action === "approve") await api.post(`/api/review/${id}/approve`, { value, note });
      else if (action === "reject") await api.post(`/api/review/${id}/reject`, { note });
      else {
        const r = await api.post(`/api/review/${id}/false-positive`, { note });
        if (!r.feedback.length) toast(`${it.detector || "This check"} is not a tunable detector, so no feedback was recorded.`);
      }
      toast(`${{ approve: "Approved", reject: "Rejected", false_positive: "Marked normal" }[action]} #${id}.`, { timeout: 2500 });
      selected.delete(id);
      const at = items.findIndex((x) => x.id === id);
      if (state.status === "pending" && at >= 0) {
        // the item leaves this view: drop it now and open the next one in its place
        items.splice(at, 1);
        total = Math.max(0, total - 1);
        if (active >= items.length) active = items.length - 1;
        detail = null;
        drawList();
        if (active >= 0) openItem(active, { focusList: false });
        else setDetail(emptyDetail());
        load({ quiet: true });
      } else {
        load({ keep: true });
      }
      loadFacets();
      refreshBadge();
      if (window.matchMedia(NARROW).matches) closeSheet();
    } catch (err) {
      toast(err.message, { kind: "error" });
    } finally {
      inflight = false;
    }
  }

  // ------------------------------------------------------------ keyboard
  function onKey(e) {
    if (e.metaKey || e.ctrlKey || e.altKey || e.defaultPrevented) return;
    if (e.key === "Escape") {
      if (typingTarget(e)) return;
      if (closeSheet()) { e.preventDefault(); return; }
      if (selected.size || allMatching) { e.preventDefault(); allMatching = false; selected.clear(); paintSelection(); }
      return;
    }
    if (typingTarget(e) || document.querySelector(".drawer.is-open")) return;
    const k = e.key;
    const bulk = selected.size > 0 || allMatching;
    if (k === "j" || k === "ArrowDown") {
      e.preventDefault();
      if (active < items.length - 1) openItem(active + 1);
      else if (state.offset + state.limit < total) { state.offset += state.limit; active = 0; load(); }
    } else if (k === "k" || k === "ArrowUp") {
      e.preventDefault();
      if (active > 0) openItem(active - 1);
      else if (state.offset > 0) { state.offset = Math.max(0, state.offset - state.limit); active = state.limit - 1; load(); }
    } else if (k === "Enter" && active >= 0 && document.activeElement === listEl) {
      e.preventDefault();
      openItem(active, { sheet: true });
    } else if (k === "x" && active >= 0) {
      e.preventDefault();
      toggleSelect(active, e.shiftKey);
    } else if (k === "X" && active >= 0) {
      e.preventDefault();
      toggleSelect(active, true);
    } else if (k === "a") {
      e.preventDefault();
      if (bulk) runBulk("approve"); else single("approve");
    } else if (k === "r") {
      e.preventDefault();
      if (bulk) runBulk("reject"); else single("reject");
    } else if (k === "m") {
      e.preventDefault();
      if (bulk) runBulk("false_positive"); else single("false_positive");
    } else if (k === "e" && detail && detail.input && !detail.input.disabled) {
      e.preventDefault();
      if (window.matchMedia(NARROW).matches) openSheet();
      detail.input.focus();
      detail.input.select();
    }
  }
  document.addEventListener("keydown", onKey);

  loadFacets();
  load();
  return () => {
    document.removeEventListener("keydown", onKey);
    document.body.classList.remove("sheet-open");
  };
}
