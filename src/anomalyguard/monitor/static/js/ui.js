// Small DOM helpers and shared components. Everything renders text with
// textContent, never innerHTML, so data values cannot inject markup.

const SVGNS = "http://www.w3.org/2000/svg";

export function h(tag, attrs, ...children) {
  const el = document.createElement(tag);
  setAttrs(el, attrs);
  append(el, children);
  return el;
}

export function s(tag, attrs, ...children) {
  const el = document.createElementNS(SVGNS, tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (v === undefined || v === null || v === false) continue;
    if (k.startsWith("on") && typeof v === "function") el.addEventListener(k.slice(2).toLowerCase(), v);
    else el.setAttribute(k, String(v));
  }
  append(el, children);
  return el;
}

function setAttrs(el, attrs) {
  for (const [k, v] of Object.entries(attrs || {})) {
    if (v === undefined || v === null || v === false) continue;
    if (k === "class") el.className = Array.isArray(v) ? v.filter(Boolean).join(" ") : v;
    else if (k === "dataset") Object.assign(el.dataset, v);
    else if (k === "style" && typeof v === "object") Object.assign(el.style, v);
    else if (k.startsWith("on") && typeof v === "function") el.addEventListener(k.slice(2).toLowerCase(), v);
    else if (k === "value" || k === "checked" || k === "disabled" || k === "indeterminate" || k === "selected") el[k] = v;
    else if (v === true) el.setAttribute(k, "");
    else el.setAttribute(k, String(v));
  }
}

function append(el, children) {
  for (const c of children.flat(Infinity)) {
    if (c === null || c === undefined || c === false) continue;
    el.append(c instanceof Node ? c : document.createTextNode(String(c)));
  }
}

export function clear(el) { while (el.firstChild) el.firstChild.remove(); return el; }

/** Append children, skipping null/false (native append would print "null"). */
export function add(el, ...children) { append(el, children); return el; }

const ICONS = {
  upload: "M12 15V4M7.5 8.5 12 4l4.5 4.5M5 14v4a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2v-4",
  download: "M12 4v11M7.5 10.5 12 15l4.5-4.5M5 14v4a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2v-4",
  close: "M6 6l12 12M18 6 6 18",
  left: "M15 6l-6 6 6 6",
  right: "M9 6l6 6-6 6",
  play: "M7 5v14l11-7z",
  check: "M5 12.5l4.5 4.5L19 7.5",
  x: "M7 7l10 10M17 7 7 17",
  flag: "M5 21V4M5 4h11l-2 4 2 4H5",
  refresh: "M20 11a8 8 0 1 0-2.3 5.7M20 5v6h-6",
  plus: "M12 5v14M5 12h14",
  file: "M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8zM14 3v5h5",
  trash: "M4 7h16M9 7V4h6v3M6 7l1 13h10l1-13",
  external: "M14 4h6v6M20 4l-9 9M18 14v5a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1V7a1 1 0 0 1 1-1h5",
  thumbsdown: "M10 15H5a2 2 0 0 1-2-2.3l1.2-6A2 2 0 0 1 6.2 5H17v9l-4 6a2 2 0 0 1-3-1.7zM17 5h3v9h-3",
};

export function icon(name, cls = "icon") {
  return s("svg", { class: cls, viewBox: "0 0 24 24", "aria-hidden": "true" }, s("path", { d: ICONS[name] || "" }));
}

// ---------------------------------------------------------------- formatting
const nf = new Intl.NumberFormat();
export const fmtInt = (v) => (v === null || v === undefined ? "-" : nf.format(Math.round(v)));
export function fmtNum(v, digits = 4) {
  if (v === null || v === undefined || v === "") return "-";
  if (typeof v !== "number") return String(v);
  if (!Number.isFinite(v)) return String(v);
  if (Number.isInteger(v)) return nf.format(v);
  const abs = Math.abs(v);
  if (abs >= 1000) return nf.format(Math.round(v * 10) / 10);
  return String(Number(v.toPrecision(digits)));
}
export function fmtPct(v, digits = 1) {
  if (v === null || v === undefined) return "-";
  return `${(v * 100).toFixed(digits)}%`;
}
export function fmtValue(v) {
  if (v === null || v === undefined) return "null";
  if (typeof v === "number") {
    // data values: no digit grouping (ids, years), trimmed float noise
    if (Number.isInteger(v) || !Number.isFinite(v)) return String(v);
    return String(Number(v.toPrecision(10)));
  }
  if (typeof v === "boolean") return v ? "true" : "false";
  return String(v);
}
export function parseTime(t) {
  if (!t) return null;
  const d = new Date(t);
  return Number.isNaN(d.getTime()) ? null : d;
}
export function fmtTime(t) {
  const d = parseTime(t);
  if (!d) return "-";
  return d.toLocaleString(undefined, { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" });
}
export function fmtAgo(t) {
  const d = parseTime(t);
  if (!d) return "-";
  const sec = Math.round((Date.now() - d.getTime()) / 1000);
  if (sec < 45) return "just now";
  const min = Math.round(sec / 60);
  if (min < 60) return `${min} min ago`;
  const hr = Math.round(min / 60);
  if (hr < 36) return `${hr} h ago`;
  const days = Math.round(hr / 24);
  if (days < 30) return `${days} d ago`;
  return fmtTime(t);
}
export function timeEl(t) {
  const d = parseTime(t);
  return h("time", { datetime: t || "", title: d ? d.toLocaleString() : "" }, fmtAgo(t));
}
export function fmtMs(ms) {
  if (ms === null || ms === undefined) return "-";
  if (ms < 1000) return `${Math.round(ms)} ms`;
  if (ms < 60000) return `${(ms / 1000).toFixed(1)} s`;
  return `${Math.floor(ms / 60000)} min ${Math.round((ms % 60000) / 1000)} s`;
}
export function fmtBytes(n) {
  if (!n && n !== 0) return "-";
  const u = ["B", "KB", "MB", "GB"];
  let i = 0;
  let v = n;
  while (v >= 1024 && i < u.length - 1) { v /= 1024; i += 1; }
  return `${v.toFixed(i ? 1 : 0)} ${u[i]}`;
}
export const runLabel = (p) => (p && p.startsWith("analysis:") ? p.slice(9) : p);
export const isAnalysis = (p) => Boolean(p && p.startsWith("analysis:"));

// ---------------------------------------------------------------- components
export function chip(text, kind) {
  return h("span", { class: ["chip", kind || String(text).toLowerCase()] }, text);
}

export function pageHead({ title, lede, crumbs, actions }) {
  return h("header", { class: "page-head" },
    h("div", { style: { minWidth: "0" } },
      crumbs ? h("nav", { class: "crumbs", "aria-label": "Breadcrumb" }, crumbs.flatMap((c, i) => [
        i ? h("span", { "aria-hidden": "true" }, "/") : null,
        c.href ? h("a", { href: c.href }, c.label) : h("span", null, c.label),
      ])) : null,
      h("h1", null, title),
      lede ? h("p", { class: "lede" }, lede) : null),
    actions && actions.length ? h("div", { class: "actions" }, actions) : null);
}

export function panel({ title, sub, actions, body, flush = false, cls }) {
  return h("section", { class: ["panel", cls] },
    title || actions ? h("div", { class: "panel-head" },
      h("div", { style: { minWidth: "0" } }, title ? h("h2", null, title) : null, sub ? h("p", null, sub) : null),
      actions ? h("div", { class: "row" }, actions) : null) : null,
    h("div", { class: flush ? "panel-body flush" : "panel-body" }, body));
}

export function kpis(items) {
  return h("div", { class: "kpis" }, items.map((k) => h("div", { class: ["kpi", k.alert && "is-alert"] },
    h("div", { class: "label" }, k.label),
    h("div", { class: "value" }, k.value),
    k.sub ? h("div", { class: "sub" }, k.sub) : null)));
}

export function loading(lines = 3) {
  return h("div", { class: "skeleton-block", "aria-busy": "true", "aria-label": "Loading" },
    Array.from({ length: lines }, (_, i) => h("span", { class: "skeleton", style: { width: `${[60, 85, 40, 70][i % 4]}%` } })));
}

export function emptyState({ title, text, actions, center = false }) {
  return h("div", { class: ["state", center && "center"] }, h("h3", null, title), text ? h("p", null, text) : null,
    actions ? h("div", { class: "row" }, actions) : null);
}

export function errorState(err, retry) {
  const msg = err && err.message ? err.message : String(err);
  return h("div", { class: "state error", role: "alert" }, h("h3", null, "Could not load this"), h("p", null, msg),
    retry ? h("button", { class: "btn", type: "button", onClick: retry }, icon("refresh"), "Try again") : null);
}

export function button(label, { onClick, kind, icon: ic, small, title, type = "button", disabled } = {}) {
  return h("button", { class: ["btn", kind, small && "sm"], type, title, disabled, onClick }, ic ? icon(ic) : null, label);
}

/** Run an async action with a loading state on the button. */
export async function busy(btn, fn) {
  btn.dataset.state = "loading";
  btn.disabled = true;
  try { return await fn(); } finally { delete btn.dataset.state; btn.disabled = false; }
}

export function select(options, { value, onChange, label, cls = "select", name } = {}) {
  const el = h("select", { class: cls, name, "aria-label": label, onChange: (e) => onChange && onChange(e.target.value) },
    options.map((o) => {
      const opt = typeof o === "object" ? o : { value: o, label: o };
      return h("option", { value: opt.value, selected: String(opt.value) === String(value ?? "") }, opt.label);
    }));
  return el;
}

export function segmented(options, value, onChange, label) {
  const wrap = h("div", { class: "segmented", role: "group", "aria-label": label });
  for (const o of options) {
    const opt = typeof o === "object" ? o : { value: o, label: o };
    wrap.append(h("button", {
      type: "button", "aria-pressed": String(opt.value === value),
      onClick: () => {
        for (const b of wrap.children) b.setAttribute("aria-pressed", "false");
        wrap.querySelector(`[data-v="${CSS.escape(String(opt.value))}"]`).setAttribute("aria-pressed", "true");
        onChange(opt.value);
      },
      dataset: { v: String(opt.value) },
    }, opt.label));
  }
  return wrap;
}

export function pager({ offset, limit, total, onChange, sizes = [25, 50, 100], noun = "rows" }) {
  const from = total ? offset + 1 : 0;
  const to = Math.min(offset + limit, total);
  const page = Math.floor(offset / limit) + 1;
  const pages = Math.max(1, Math.ceil(total / limit));
  return h("div", { class: "pager" },
    h("span", { class: "num" }, `${fmtInt(from)}–${fmtInt(to)} of ${fmtInt(total)} ${noun}`),
    h("div", { class: "row" },
      h("label", { class: "row" }, h("span", null, "Per page"),
        select(sizes.map(String), { value: String(limit), cls: "select sm", label: "Rows per page", onChange: (v) => onChange(0, Number(v)) })),
      h("button", { class: "btn sm icon-only", type: "button", "aria-label": "Previous page", disabled: offset <= 0, onClick: () => onChange(Math.max(0, offset - limit), limit) }, icon("left")),
      h("span", { class: "num" }, `${page} / ${pages}`),
      h("button", { class: "btn sm icon-only", type: "button", "aria-label": "Next page", disabled: to >= total, onClick: () => onChange(offset + limit, limit) }, icon("right"))));
}

export function debounce(fn, ms = 300) {
  let t;
  return (...args) => { clearTimeout(t); t = setTimeout(() => fn(...args), ms); };
}

// ---------------------------------------------------------------- toast
export function toast(message, { kind, action, timeout = 5000 } = {}) {
  const box = document.getElementById("toasts");
  const el = h("div", { class: ["toast", kind] }, h("span", { class: "grow" }, message),
    action ? h("button", { type: "button", onClick: () => { action.run(); el.remove(); } }, action.label) : null,
    h("button", { type: "button", "aria-label": "Dismiss", onClick: () => el.remove() }, icon("close")));
  box.append(el);
  if (timeout) setTimeout(() => el.remove(), timeout);
  return el;
}

// ---------------------------------------------------------------- drawer
let openDrawer = null;
export function drawer({ title, sub, body, foot, onClose }) {
  closeDrawer();
  const scrim = h("div", { class: "scrim" });
  const closeBtn = h("button", { class: "btn ghost icon-only", type: "button", "aria-label": "Close" }, icon("close"));
  const panelEl = h("aside", { class: "drawer", role: "dialog", "aria-modal": "true", "aria-label": typeof title === "string" ? title : "Details" },
    h("div", { class: "drawer-head" }, h("div", { style: { minWidth: "0" } }, h("h2", null, title), sub ? h("p", { class: "muted small" }, sub) : null), closeBtn),
    h("div", { class: "drawer-body" }, body),
    foot ? h("div", { class: "drawer-foot" }, foot) : null);
  const previous = document.activeElement;
  const close = () => {
    scrim.classList.remove("is-open");
    panelEl.classList.remove("is-open");
    document.removeEventListener("keydown", onKey);
    setTimeout(() => { scrim.remove(); panelEl.remove(); }, 260);
    if (previous && previous.focus) previous.focus();
    openDrawer = null;
    if (onClose) onClose();
  };
  const onKey = (e) => { if (e.key === "Escape") close(); };
  scrim.addEventListener("click", close);
  closeBtn.addEventListener("click", close);
  document.addEventListener("keydown", onKey);
  document.body.append(scrim, panelEl);
  requestAnimationFrame(() => { scrim.classList.add("is-open"); panelEl.classList.add("is-open"); closeBtn.focus(); });
  openDrawer = { close, el: panelEl };
  return openDrawer;
}
export function closeDrawer() { if (openDrawer) openDrawer.close(); }

// ---------------------------------------------------------------- popover
let openPop = null;
export function popover(anchor, content) {
  closePopover();
  const el = h("div", { class: "popover", role: "dialog" }, content);
  document.body.append(el);
  const r = anchor.getBoundingClientRect();
  const w = el.offsetWidth;
  const left = Math.max(12, Math.min(r.left, window.innerWidth - w - 12));
  const below = r.bottom + 6 + el.offsetHeight < window.innerHeight;
  el.style.left = `${left}px`;
  el.style.top = below ? `${r.bottom + 6}px` : `${Math.max(12, r.top - el.offsetHeight - 6)}px`;
  const onDoc = (e) => { if (!el.contains(e.target) && e.target !== anchor) closePopover(); };
  const onKey = (e) => { if (e.key === "Escape") closePopover(); };
  setTimeout(() => document.addEventListener("click", onDoc), 0);
  document.addEventListener("keydown", onKey);
  window.addEventListener("scroll", closePopover, { once: true, capture: true });
  openPop = { el, off: () => { document.removeEventListener("click", onDoc); document.removeEventListener("keydown", onKey); } };
  return el;
}
export function closePopover() { if (openPop) { openPop.off(); openPop.el.remove(); openPop = null; } }

/** Parse what a user typed as a final value: numbers become numbers, "null" null. */
export function parseTyped(text) {
  const t = String(text).trim();
  if (t === "" || t.toLowerCase() === "null") return null;
  if (/^-?\d+(\.\d+)?([eE][-+]?\d+)?$/.test(t)) return Number(t);
  if (t === "true" || t === "false") return t === "true";
  return t;
}

export function setTitle(text) { document.title = text ? `${text} · AnomalyGuard` : "AnomalyGuard"; }
