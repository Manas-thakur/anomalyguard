// App shell: hash router, theme, command palette, keyboard shortcuts, API-key
// prompt and the sidebar badge.

import { api, onKeyRequired, setKey } from "./api.js";
import { clear, closeDrawer, closePopover, errorState, h, setTitle } from "./ui.js";
import { initPalette, open as openPalette, close as closePalette } from "./palette.js";
import * as health from "./pages/health.js";
import * as analyze from "./pages/analyze.js";
import * as runs from "./pages/runs.js";
import * as review from "./pages/review.js";
import * as pipelines from "./pages/pipelines.js";
import * as settings from "./pages/settings.js";

const ROUTES = [
  { re: /^(?:health|overview)$/, page: health, nav: "health" },
  { re: /^analyze(?:\/(d|a)\/([a-f0-9]+))?$/, page: analyze, nav: "analyze", params: (m) => ({ kind: m[1], id: m[2] }) },
  { re: /^runs$/, page: runs, nav: "runs" },
  { re: /^runs\/(\d+)$/, page: runs, nav: "runs", params: (m) => ({ id: Number(m[1]) }) },
  { re: /^review$/, page: review, nav: "review" },
  { re: /^pipelines$/, page: pipelines, nav: "pipelines" },
  { re: /^pipelines\/([a-f0-9]+)$/, page: pipelines, nav: "pipelines", params: (m) => ({ id: m[1] }) },
  { re: /^settings$/, page: settings, nav: "settings" },
];

const main = document.getElementById("main");
const appEl = document.getElementById("app");
let cleanup = null;

/** Parse "#/runs?status=failed" into { path, query }. */
export function currentRoute() {
  const raw = location.hash.replace(/^#\/?/, "") || "health";
  const [path, q = ""] = raw.split("?");
  return { path, query: Object.fromEntries(new URLSearchParams(q)) };
}

/** Update the query part of the hash without re-rendering the page. */
export function setQuery(query) {
  const { path } = currentRoute();
  const qs = new URLSearchParams(Object.entries(query).filter(([, v]) => v !== undefined && v !== null && v !== "")).toString();
  history.replaceState(null, "", `#/${path}${qs ? `?${qs}` : ""}`);
}

function render() {
  const { path, query } = currentRoute();
  if (cleanup) { try { cleanup(); } catch { /* page already gone */ } cleanup = null; }
  closeDrawer();
  closePopover();
  closePalette();
  setNav(false);
  const route = ROUTES.find((r) => r.re.test(path));
  for (const a of document.querySelectorAll("#nav a")) {
    if (route && a.dataset.route === route.nav) a.setAttribute("aria-current", "page");
    else a.removeAttribute("aria-current");
  }
  const page = h("div", { class: "page view-enter" });
  clear(main).append(page);
  document.body.dataset.route = route ? route.nav : "";
  if (!route) {
    setTitle("Not found");
    page.append(errorState(new Error(`No page at #/${path}`)));
    return;
  }
  const params = { ...(route.params ? route.params(path.match(route.re)) : {}), query };
  try {
    cleanup = route.page.render(page, params) || null;
  } catch (err) {
    console.error(err);
    page.append(errorState(err));
  }
  main.focus({ preventScroll: true });
  window.scrollTo(0, 0);
  refreshBadge();
}

// ---------------------------------------------------------------- theme
const THEME_KEY = "ag.theme";
let themeChoice = "system";
function applyTheme(choice) {
  themeChoice = choice;
  if (choice === "light" || choice === "dark") document.documentElement.dataset.theme = choice;
  else delete document.documentElement.dataset.theme;
  for (const b of document.querySelectorAll("[data-theme-choice]")) {
    b.setAttribute("aria-pressed", String(b.dataset.themeChoice === choice));
  }
  window.dispatchEvent(new CustomEvent("themechange"));
}
/** The theme in effect: "light" or "dark" (resolving "system"). */
export function effectiveTheme() {
  if (themeChoice === "light" || themeChoice === "dark") return themeChoice;
  return window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
}
export function setTheme(choice) {
  try { if (choice === "system") localStorage.removeItem(THEME_KEY); else localStorage.setItem(THEME_KEY, choice); } catch { /* ignore */ }
  applyTheme(choice);
}
try { themeChoice = localStorage.getItem(THEME_KEY) || "system"; } catch { /* storage blocked */ }
applyTheme(themeChoice);
for (const b of document.querySelectorAll("[data-theme-choice]")) {
  b.addEventListener("click", () => setTheme(b.dataset.themeChoice));
}

// ---------------------------------------------------------------- mobile nav
const toggle = document.getElementById("nav-toggle");
function setNav(open) {
  appEl.classList.toggle("nav-open", open);
  toggle.setAttribute("aria-expanded", String(open));
}
toggle.addEventListener("click", () => {
  const open = !appEl.classList.contains("nav-open");
  setNav(open);
  if (open) document.querySelector("#nav a")?.focus();
});
appEl.addEventListener("click", (e) => {
  if (e.target === appEl || e.target === main) setNav(false);
});

// ---------------------------------------------------------------- shortcuts
const isMac = /Mac|iPhone|iPad/.test(navigator.platform || navigator.userAgent);
for (const k of document.querySelectorAll("[data-mod-key]")) k.textContent = isMac ? "⌘K" : "Ctrl K";

export const SHORTCUTS = [
  ["Anywhere", [
    [isMac ? "⌘ K" : "Ctrl K", "Open the command palette"],
    ["?", "Show keyboard shortcuts"],
    ["g h", "Go to Health"],
    ["g r", "Go to Runs"],
    ["g i", "Go to the review inbox"],
    ["g a", "Go to Analyze"],
    ["g p", "Go to Pipelines"],
    ["g s", "Go to Settings"],
    ["/", "Focus search on the page"],
  ]],
  ["Review inbox", [
    ["j  k", "Next / previous item"],
    ["a", "Approve (selection, or the open item)"],
    ["r", "Reject: keep the original value"],
    ["m", "Mark as normal (false positive)"],
    ["e", "Edit the final value"],
    ["x", "Select or deselect the open item"],
    ["Shift click", "Select a range"],
    ["Esc", "Clear the selection or close the item"],
  ]],
];

const shortcutsDialog = document.getElementById("shortcuts");
function showShortcuts() {
  const grid = clear(document.getElementById("shortcut-grid"));
  for (const [title, rows] of SHORTCUTS) {
    grid.append(h("section", null, h("h3", { class: "label" }, title), h("dl", null, rows.flatMap(([keys, what]) => [
      h("dt", null, keys.split(/\s+/).map((k) => h("kbd", null, k))), h("dd", null, what)]))));
  }
  if (!shortcutsDialog.open) shortcutsDialog.showModal();
}
for (const b of document.querySelectorAll("[data-open-shortcuts]")) b.addEventListener("click", showShortcuts);
shortcutsDialog.addEventListener("click", (e) => { if (e.target === shortcutsDialog) shortcutsDialog.close(); });

/** True when a key press is meant for a text field or an open dialog. */
export function typingTarget(e) {
  const t = e.target;
  if (!(t instanceof Element)) return false;
  return Boolean(t.closest("input, textarea, select, [contenteditable=''], [contenteditable=true]")) || Boolean(document.querySelector("dialog[open]"));
}

const GO = { h: "#/health", r: "#/runs", i: "#/review", a: "#/analyze", p: "#/pipelines", s: "#/settings", q: "#/review" };
let pendingG = 0;
document.addEventListener("keydown", (e) => {
  if ((e.metaKey || e.ctrlKey) && !e.altKey && e.key.toLowerCase() === "k") {
    e.preventDefault();
    if (document.getElementById("palette").open) closePalette(); else openPalette();
    return;
  }
  if (e.key === "Escape" && appEl.classList.contains("nav-open")) { setNav(false); toggle.focus(); return; }
  if (e.defaultPrevented || e.metaKey || e.ctrlKey || e.altKey || typingTarget(e)) return;
  if (e.key === "?") { e.preventDefault(); showShortcuts(); return; }
  if (e.key === "/") {
    const search = main.querySelector("input[type=search]");
    if (search) { e.preventDefault(); search.focus(); search.select(); }
    return;
  }
  if (pendingG && Date.now() - pendingG < 1200 && GO[e.key]) {
    e.preventDefault();
    pendingG = 0;
    location.hash = GO[e.key];
    return;
  }
  pendingG = e.key === "g" ? Date.now() : 0;
});

initPalette({ setTheme, theme: () => effectiveTheme(), showShortcuts });

// ---------------------------------------------------------------- API key prompt
const dialog = document.getElementById("key-dialog");
const keyInput = document.getElementById("key-input");
const keyError = document.getElementById("key-error");
let pending = null;
onKeyRequired(() => {
  if (pending) return pending;
  pending = new Promise((resolve) => {
    keyError.hidden = true;
    keyInput.value = "";
    const done = async (e) => {
      e.preventDefault();
      const key = keyInput.value.trim();
      if (!key) return;
      const res = await fetch("/api/auth", { headers: { "X-API-Key": key } }).then((r) => r.json()).catch(() => null);
      if (!res || !res.authenticated) { keyError.hidden = false; keyInput.select(); return; }
      document.getElementById("key-form").removeEventListener("submit", done);
      dialog.close();
      pending = null;
      resolve(key);
    };
    document.getElementById("key-form").addEventListener("submit", done);
    dialog.addEventListener("cancel", (e) => e.preventDefault());
    dialog.showModal();
    keyInput.focus();
  });
  return pending;
});

// ---------------------------------------------------------------- shared state
export async function refreshBadge() {
  try {
    const s = await api.get("/api/summary");
    const el = document.getElementById("nav-review-count");
    el.hidden = !s.review.pending;
    el.textContent = s.review.pending > 999 ? "999+" : String(s.review.pending);
    el.setAttribute("aria-label", `${s.review.pending} pending`);
    return s;
  } catch { return null; }
}

async function boot() {
  try {
    const auth = await fetch("/api/auth", { headers: localKeyHeader() }).then((r) => r.json());
    if (auth.auth_enabled && !auth.authenticated) setKey("");
  } catch { /* the page will show its own error */ }
  fetch("/health").then((r) => r.json()).then((hl) => {
    document.getElementById("app-version").textContent = `v${hl.version}`;
  }).catch(() => {});
  window.addEventListener("hashchange", render);
  render();
}

function localKeyHeader() {
  try { const k = localStorage.getItem("ag.apiKey"); return k ? { "X-API-Key": k } : {}; } catch { return {}; }
}

boot();
