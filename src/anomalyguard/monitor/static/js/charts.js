// Inline-SVG charts: a time-series line chart with a real time axis, a
// crosshair tooltip and a toggleable legend; horizontal bar lists; histograms.

import { h, s, clear, fmtTime } from "./ui.js";

export const SERIES_TOKENS = ["--series-1", "--series-2", "--series-3", "--series-4", "--series-5", "--series-6"];
export const MAX_SERIES = SERIES_TOKENS.length;

/** Stable colour per entity: the same pipeline keeps its colour across filters. */
export function colorFor(key, allKeys) {
  const i = Math.max(0, allKeys.indexOf(key));
  return `var(${SERIES_TOKENS[i % SERIES_TOKENS.length]})`;
}

const MIN = 60e3;
const HOUR = 60 * MIN;
const DAY = 24 * HOUR;
const STEPS = [MIN, 5 * MIN, 15 * MIN, 30 * MIN, HOUR, 3 * HOUR, 6 * HOUR, 12 * HOUR, DAY, 2 * DAY, 7 * DAY, 14 * DAY, 30 * DAY, 90 * DAY];

function timeTicks(t0, t1, maxTicks) {
  const span = Math.max(t1 - t0, MIN);
  const step = STEPS.find((st) => span / st <= maxTicks) || STEPS[STEPS.length - 1];
  const tzOffset = new Date(t0).getTimezoneOffset() * MIN;
  let t = Math.ceil((t0 - tzOffset) / step) * step + tzOffset;
  const out = [];
  for (; t <= t1; t += step) out.push(t);
  return { ticks: out, step };
}

function tickLabel(t, step, span) {
  const d = new Date(t);
  if (step >= DAY) return d.toLocaleDateString(undefined, { month: "short", day: "numeric" });
  const time = d.toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit" });
  if (span > DAY && d.getHours() === 0 && d.getMinutes() === 0) {
    return d.toLocaleDateString(undefined, { month: "short", day: "numeric" });
  }
  return time;
}

function niceMax(v) {
  if (!(v > 0)) return 1;
  const p = 10 ** Math.floor(Math.log10(v));
  const n = v / p;
  const nice = n <= 1 ? 1 : n <= 2 ? 2 : n <= 2.5 ? 2.5 : n <= 5 ? 5 : 10;
  return nice * p;
}

/**
 * series: [{ key, label, color, points: [{ t: Date|string, v: number, meta }] }]
 * opts: { yFormat, yMin, yMax, height, emptyText, onPointClick }
 */
export function lineChart(container, series, opts = {}) {
  const hidden = new Set();
  const wrap = h("div", { class: "chart" });
  const plot = h("div");
  const legend = series.length > 1 ? h("div", { class: "legend", role: "group", "aria-label": "Series" }) : null;
  wrap.append(plot);
  if (legend) wrap.append(legend);
  clear(container).append(wrap);
  const yFormat = opts.yFormat || ((v) => String(v));

  const data = series.map((sr) => ({
    ...sr,
    points: sr.points
      .map((p) => ({ ...p, t: p.t instanceof Date ? p.t : new Date(p.t) }))
      .filter((p) => !Number.isNaN(p.t.getTime()) && p.v !== null && p.v !== undefined && Number.isFinite(p.v))
      .sort((a, b) => a.t - b.t),
  }));

  if (legend) {
    for (const sr of data) {
      const b = h("button", { type: "button", "aria-pressed": "true" },
        h("span", { class: "swatch", style: { background: sr.color } }), sr.label);
      b.addEventListener("click", () => {
        if (hidden.has(sr.key)) hidden.delete(sr.key);
        else if (hidden.size < data.length - 1) hidden.add(sr.key);
        b.setAttribute("aria-pressed", String(!hidden.has(sr.key)));
        draw();
      });
      legend.append(b);
    }
  }

  let tip = null;
  function draw() {
    clear(plot);
    const visible = data.filter((d) => !hidden.has(d.key) && d.points.length);
    const all = visible.flatMap((d) => d.points);
    const width = Math.max(280, Math.round(plot.clientWidth || container.clientWidth || 600));
    const height = opts.height || 220;
    if (!all.length) {
      plot.append(h("p", { class: "muted small", style: { padding: "24px 0" } }, opts.emptyText || "No data in this range."));
      return;
    }
    const m = { top: 12, right: 16, bottom: 26, left: 52 };
    const iw = width - m.left - m.right;
    const ih = height - m.top - m.bottom;
    let t0 = Math.min(...all.map((p) => p.t.getTime()));
    let t1 = Math.max(...all.map((p) => p.t.getTime()));
    if (t1 - t0 < MIN) { t0 -= 30 * MIN; t1 += 30 * MIN; }
    const pad = (t1 - t0) * 0.03;
    t0 -= pad; t1 += pad;
    const vmax = Math.max(...all.map((p) => p.v));
    const vmin = Math.min(...all.map((p) => p.v));
    const yMax = opts.yMax !== undefined ? Math.max(opts.yMax, vmax) : niceMax(vmax * 1.1);
    let yMin = opts.yMin !== undefined ? Math.min(opts.yMin, vmin) : 0;
    if (opts.yFloor !== undefined) yMin = Math.max(opts.yFloor, Math.min(yMin, Math.floor(vmin * 20) / 20));
    const x = (t) => m.left + ((t - t0) / (t1 - t0)) * iw;
    const y = (v) => m.top + ih - ((v - yMin) / (yMax - yMin || 1)) * ih;

    const svg = s("svg", { viewBox: `0 0 ${width} ${height}`, role: "img", "aria-label": opts.label || "Time series chart" });
    const grid = s("g", { class: "grid" });
    const axis = s("g", { class: "axis" });
    const yTicks = 4;
    for (let i = 0; i <= yTicks; i += 1) {
      const v = yMin + ((yMax - yMin) * i) / yTicks;
      grid.append(s("line", { x1: m.left, x2: width - m.right, y1: y(v), y2: y(v) }));
      axis.append(s("text", { x: m.left - 8, y: y(v) + 4, "text-anchor": "end" }, yFormat(v)));
    }
    const { ticks, step } = timeTicks(t0, t1, Math.max(2, Math.floor(iw / 90)));
    for (const t of ticks) {
      axis.append(s("text", { x: x(t), y: height - 6, "text-anchor": "middle" }, tickLabel(t, step, t1 - t0)));
    }
    svg.append(grid, s("line", { class: "baseline", x1: m.left, x2: width - m.right, y1: m.top + ih, y2: m.top + ih }), axis);

    for (const sr of visible) {
      const d = sr.points.map((p, i) => `${i ? "L" : "M"}${x(p.t.getTime()).toFixed(1)},${y(p.v).toFixed(1)}`).join("");
      svg.append(s("path", { class: "line", d, style: `stroke: ${sr.color}` }));
      if (sr.points.length <= 60) {
        for (const p of sr.points) {
          svg.append(s("circle", { class: "dot", cx: x(p.t.getTime()), cy: y(p.v), r: 4, style: `fill: ${sr.color}` }));
        }
      }
    }

    const cross = s("line", { class: "crosshair", y1: m.top, y2: m.top + ih, visibility: "hidden" });
    const hover = s("g");
    svg.append(cross, hover);
    const hit = s("rect", { x: m.left, y: m.top, width: iw, height: ih, fill: "transparent" });
    svg.append(hit);
    plot.append(svg);

    tip = h("div", { class: "tip", hidden: true });
    plot.style.position = "relative";
    plot.append(tip);
    const scale = () => (svg.getBoundingClientRect().width || width) / width;

    function nearest(px) {
      // nearest run in time across visible series, then each series' point nearest that time
      let best = null;
      for (const sr of visible) {
        for (const p of sr.points) {
          const dx = Math.abs(x(p.t.getTime()) - px);
          if (!best || dx < best.dx) best = { dx, t: p.t.getTime() };
        }
      }
      return best;
    }
    function move(ev) {
      const r = svg.getBoundingClientRect();
      const px = (ev.clientX - r.left) / scale();
      const best = nearest(px);
      if (!best) return;
      const tx = x(best.t);
      cross.setAttribute("x1", tx);
      cross.setAttribute("x2", tx);
      cross.setAttribute("visibility", "visible");
      clear(hover);
      clear(tip);
      tip.append(h("div", { class: "t" }, new Date(best.t).toLocaleString(undefined, { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit", second: "2-digit" })));
      for (const sr of visible) {
        const p = sr.points.reduce((a, b) => (Math.abs(b.t - best.t) < Math.abs(a.t - best.t) ? b : a));
        if (Math.abs(p.t - best.t) > (t1 - t0) / 40) continue;
        hover.append(s("circle", { class: "dot", cx: x(p.t.getTime()), cy: y(p.v), r: 5.5, style: `fill: ${sr.color}` }));
        tip.append(h("div", { class: "s" }, h("span", { class: "row", style: { gap: "6px" } }, h("span", { class: "swatch", style: { background: sr.color } }), sr.label), h("b", null, yFormat(p.v))));
        if (p.meta) tip.append(h("div", { class: "muted small" }, p.meta));
      }
      tip.hidden = false;
      const sc = scale();
      const left = tx * sc + 12;
      const maxLeft = plot.clientWidth - tip.offsetWidth - 4;
      tip.style.left = `${Math.max(0, left > maxLeft ? tx * sc - tip.offsetWidth - 12 : left)}px`;
      tip.style.top = `${m.top * sc}px`;
      hit.dataset.t = String(best.t);
    }
    function leave() {
      cross.setAttribute("visibility", "hidden");
      clear(hover);
      tip.hidden = true;
    }
    hit.addEventListener("pointermove", move);
    hit.addEventListener("pointerdown", move);
    hit.addEventListener("pointerleave", leave);
    if (opts.onPointClick) {
      hit.style.cursor = "pointer";
      hit.addEventListener("click", () => {
        const t = Number(hit.dataset.t);
        for (const sr of visible) {
          const p = sr.points.find((q) => q.t.getTime() === t);
          if (p) { opts.onPointClick(p, sr); return; }
        }
      });
    }
  }

  draw();
  let last = plot.clientWidth;
  const ro = new ResizeObserver(() => {
    if (Math.abs(plot.clientWidth - last) > 4) { last = plot.clientWidth; draw(); }
  });
  ro.observe(plot);
  return () => ro.disconnect();
}

/** Horizontal bar list: [{ label, value, title?, onClick? }] */
export function barList(items, { format = (v) => String(v), color, empty = "Nothing to show." } = {}) {
  if (!items.length) return h("p", { class: "muted small" }, empty);
  const max = Math.max(...items.map((i) => i.value), 1);
  return h("div", { class: "bars" }, items.map((it) => {
    const row = h("div", { class: ["bar-row", it.onClick && "is-link"], title: it.title || `${it.label}: ${format(it.value)}` },
      h("span", { class: "name" }, it.label),
      h("span", { class: "track" }, h("span", { class: "fill", style: { width: `${(it.value / max) * 100}%`, background: it.color || color || "" } })),
      h("span", { class: "n" }, format(it.value)));
    if (it.onClick) {
      row.tabIndex = 0;
      row.setAttribute("role", "button");
      row.addEventListener("click", it.onClick);
      row.addEventListener("keydown", (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); it.onClick(); } });
    }
    return row;
  }));
}

/** Mini histogram from {edges, counts, below, above}. */
export function histogram(hist, fmt = (v) => String(v)) {
  if (!hist) return null;
  const counts = hist.counts;
  const extra = (hist.below ? 1 : 0) + (hist.above ? 1 : 0);
  const n = counts.length + extra;
  const max = Math.max(...counts, hist.below || 0, hist.above || 0, 1);
  const w = 100 / n;
  const svg = s("svg", { class: "hist", viewBox: "0 0 100 36", preserveAspectRatio: "none", role: "img",
    "aria-label": `Distribution from ${fmt(hist.edges[0])} to ${fmt(hist.edges[hist.edges.length - 1])}` });
  let i = 0;
  const bar = (c, cls, title) => {
    const bh = c ? Math.max(1.5, (c / max) * 34) : 0;
    const r = s("rect", { x: i * w + 0.4, y: 36 - bh, width: Math.max(0.5, w - 0.8), height: bh, class: cls });
    r.append(s("title", null, title));
    svg.append(r);
    i += 1;
  };
  if (hist.below) bar(hist.below, "over", `${hist.below} below ${fmt(hist.edges[0])}`);
  counts.forEach((c, k) => bar(c, "", `${fmt(hist.edges[k])} to ${fmt(hist.edges[k + 1])}: ${c}`));
  if (hist.above) bar(hist.above, "over", `${hist.above} above ${fmt(hist.edges[hist.edges.length - 1])}`);
  return svg;
}

export { fmtTime };
