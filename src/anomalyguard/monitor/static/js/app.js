// App shell: hash router, theme switch, API-key prompt, sidebar badge.

import { api, onKeyRequired, setKey } from "./api.js";
import { clear, closeDrawer, closePopover, errorState, h, setTitle } from "./ui.js";
import * as overview from "./pages/overview.js";
import * as analyze from "./pages/analyze.js";
import * as runs from "./pages/runs.js";
import * as review from "./pages/review.js";
import * as pipelines from "./pages/pipelines.js";
import * as settings from "./pages/settings.js";

const ROUTES = [
  { re: /^overview$/, page: overview, nav: "overview" },
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
  const raw = location.hash.replace(/^#\/?/, "") || "overview";
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
  appEl.classList.remove("nav-open");
  document.getElementById("nav-toggle").setAttribute("aria-expanded", "false");
  const route = ROUTES.find((r) => r.re.test(path));
  for (const a of document.querySelectorAll("#nav a")) {
    if (route && a.dataset.route === route.nav) a.setAttribute("aria-current", "page");
    else a.removeAttribute("aria-current");
  }
  const page = h("div", { class: "page view-enter" });
  clear(main).append(page);
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
function applyTheme(choice) {
  if (choice === "light" || choice === "dark") document.documentElement.dataset.theme = choice;
  else delete document.documentElement.dataset.theme;
  for (const b of document.querySelectorAll("[data-theme-choice]")) {
    b.setAttribute("aria-pressed", String(b.dataset.themeChoice === choice));
  }
  window.dispatchEvent(new CustomEvent("themechange"));
}
let savedTheme = "system";
try { savedTheme = localStorage.getItem(THEME_KEY) || "system"; } catch { /* storage blocked */ }
applyTheme(savedTheme);
for (const b of document.querySelectorAll("[data-theme-choice]")) {
  b.addEventListener("click", () => {
    const choice = b.dataset.themeChoice;
    try { if (choice === "system") localStorage.removeItem(THEME_KEY); else localStorage.setItem(THEME_KEY, choice); } catch { /* ignore */ }
    applyTheme(choice);
  });
}

// ---------------------------------------------------------------- mobile nav
const toggle = document.getElementById("nav-toggle");
toggle.addEventListener("click", () => {
  const open = !appEl.classList.contains("nav-open");
  appEl.classList.toggle("nav-open", open);
  toggle.setAttribute("aria-expanded", String(open));
  if (open) document.querySelector("#nav a")?.focus();
});
document.addEventListener("keydown", (e) => {
  if (e.key === "Escape" && appEl.classList.contains("nav-open")) { appEl.classList.remove("nav-open"); toggle.focus(); }
});
appEl.addEventListener("click", (e) => {
  if (e.target === appEl || e.target === main) appEl.classList.remove("nav-open");
});

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
    document.getElementById("app-version").textContent = `AnomalyGuard ${hl.version}`;
  }).catch(() => {});
  window.addEventListener("hashchange", render);
  render();
}

function localKeyHeader() {
  try { const k = localStorage.getItem("ag.apiKey"); return k ? { "X-API-Key": k } : {}; } catch { return {}; }
}

boot();
