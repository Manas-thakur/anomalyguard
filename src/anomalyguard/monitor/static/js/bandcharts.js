// Expected-band charts for incidents. The shaded band is the robust expected
// range; actual values are drawn in neutral ink and flagged values are marked in
// the anomaly colour (with a surface ring), so the break-out reads at a glance.

import { clear, h, s } from "./ui.js";

/** Redraw `draw(width)` into `host` now and whenever its width changes. */
function responsive(host, draw) {
  let last = 0;
  const run = () => {
    const w = Math.round(host.clientWidth || host.parentElement?.clientWidth || 560);
    if (!w || Math.abs(w - last) < 4) return;
    last = w;
    clear(host);
    draw(Math.max(260, w));
  };
  const ro = new ResizeObserver(() => {
    if (!host.isConnected) { ro.disconnect(); return; }
    run();
  });
  ro.observe(host);
  requestAnimationFrame(run);
}

function niceTicks(lo, hi, count = 4) {
  const span = hi - lo || 1;
  const raw = span / Math.max(1, count);
  const p = 10 ** Math.floor(Math.log10(raw));
  const n = raw / p;
  const step = (n <= 1 ? 1 : n <= 2 ? 2 : n <= 2.5 ? 2.5 : n <= 5 ? 5 : 10) * p;
  const out = [];
  for (let v = Math.ceil(lo / step) * step; v <= hi + step * 1e-9; v += step) out.push(Number(v.toPrecision(12)));
  return out;
}

function tipBox(host) {
  const tip = h("div", { class: "tip", hidden: true, role: "status" });
  host.append(tip);
  return {
    show(lines, px, py) {
      clear(tip);
      lines.forEach((l, i) => tip.append(h("div", { class: i ? "s" : "t" }, l)));
      tip.hidden = false;
      const maxLeft = host.clientWidth - tip.offsetWidth - 4;
      tip.style.left = `${Math.max(0, Math.min(px + 12, maxLeft))}px`;
      tip.style.top = `${Math.max(0, py - tip.offsetHeight - 10)}px`;
    },
    hide() { tip.hidden = true; },
  };
}

/**
 * Distribution of one column: histogram bars, the expected range shaded and
 * flagged values marked on a strip under the bars. Values far beyond the plotted
 * range are collected in a lane on the side where they fall.
 */
export function distributionChart(data, fmt = (v) => String(v)) {
  const host = h("div", { class: "chart band-chart" });
  const marks = data.marks || [];
  const [d0, d1] = data.domain;
  const over = marks.filter((m) => m.v > d1);
  const under = marks.filter((m) => m.v < d0);
  const inside = marks.filter((m) => m.v >= d0 && m.v <= d1);
  const band = data.band || {};
  const hasBand = band.low !== null && band.low !== undefined;
  const label = `Distribution of ${data.column}${hasBand ? `, expected ${fmt(band.low)} to ${fmt(band.high)}` : ""}; ${marks.length} flagged values${over.length ? `, ${over.length} far above, up to ${fmt(data.max)}` : ""}${under.length ? `, ${under.length} far below, down to ${fmt(data.min)}` : ""}.`;
  responsive(host, (width) => {
    const height = 156;
    const laneW = 72;
    const m = { top: 20, right: over.length ? laneW + 10 : 12, bottom: 44, left: under.length ? laneW + 10 : 12 };
    const iw = width - m.left - m.right;
    const barH = height - m.top - m.bottom;
    const base = m.top + barH;
    const x = (v) => m.left + ((v - d0) / (d1 - d0 || 1)) * iw;
    const max = Math.max(...data.counts, 1);
    const svg = s("svg", { viewBox: `0 0 ${width} ${height}`, role: "img", "aria-label": label });
    if (hasBand) {
      const bx0 = x(Math.max(band.low, d0));
      const bx1 = x(Math.min(band.high, d1));
      svg.append(
        s("rect", { class: "band", x: bx0, y: m.top - 8, width: Math.max(1, bx1 - bx0), height: barH + 8 }),
        s("line", { class: "band-edge", x1: bx0, x2: bx0, y1: m.top - 8, y2: base }),
        s("line", { class: "band-edge", x1: bx1, x2: bx1, y1: m.top - 8, y2: base }),
        s("text", { class: "band-label", x: Math.min(Math.max((bx0 + bx1) / 2, m.left + 30), m.left + iw - 30), y: m.top - 11, "text-anchor": "middle" }, "expected"),
      );
    }
    const bw = iw / data.counts.length;
    data.counts.forEach((c, i) => {
      if (!c) return;
      const bh = Math.max(1.5, (c / max) * (barH - 6));
      const r = s("rect", { class: "bar", x: m.left + i * bw + 1, y: base - bh, width: Math.max(1, bw - 2), height: bh, rx: 1.5 });
      r.append(s("title", null, `${fmt(data.edges[i])} to ${fmt(data.edges[i + 1])}: ${c} rows`));
      svg.append(r);
    });
    svg.append(s("line", { class: "baseline", x1: m.left, x2: m.left + iw, y1: base, y2: base }));
    const axis = s("g", { class: "axis" });
    for (const t of niceTicks(d0, d1, Math.max(2, Math.floor(iw / 90)))) {
      if (t < d0 || t > d1) continue;
      axis.append(s("text", { x: x(t), y: height - 4, "text-anchor": "middle" }, fmt(t)));
    }
    svg.append(axis);
    const stripY = base + 14;
    let tip = null;
    const markEl = (cx, cy, mk) => {
      const inBand = hasBand && mk.v >= band.low && mk.v <= band.high;
      const what = inBand ? "flagged in context, inside the range" : "flagged, outside the range";
      const g = s("g", { class: "mark", tabindex: "0", role: "img", "aria-label": `Row ${mk.row}: ${fmt(mk.v)}, ${what}` });
      g.append(s("circle", { class: "hit", cx, cy, r: 9 }), s("circle", { class: inBand ? "anomaly in-band" : "anomaly", cx, cy, r: 4 }));
      const show = () => { const sc = host.clientWidth / width; tip.show([`Row ${mk.row}`, `${fmt(mk.v)}, ${what}`], cx * sc, cy * sc); };
      g.addEventListener("pointerenter", show);
      g.addEventListener("focus", show);
      g.addEventListener("pointerleave", () => tip.hide());
      g.addEventListener("blur", () => tip.hide());
      return g;
    };
    const used = new Map();
    for (const mk of inside.slice(0, 200)) {
      const cx = x(mk.v);
      const k = Math.round(cx / 7);
      const n = used.get(k) || 0;
      used.set(k, n + 1);
      if (n > 1) continue; // two stacked marks per pixel column is enough to read density
      svg.append(markEl(cx, stripY + n * 9, mk));
    }
    const lane = (list, side) => {
      if (!list.length) return;
      const lx0 = side === "right" ? width - laneW - 2 : 2;
      const sorted = list.slice().sort((a, b) => (side === "right" ? b.v - a.v : a.v - b.v));
      svg.append(
        s("rect", { class: "lane", x: lx0, y: m.top - 8, width: laneW, height: barH + 8 + 26, rx: 6 }),
        s("text", { class: "lane-label", x: lx0 + laneW / 2, y: m.top + 6, "text-anchor": "middle" }, side === "right" ? "far above" : "far below"),
        s("text", { class: "lane-value", x: lx0 + laneW / 2, y: m.top + 24, "text-anchor": "middle" }, fmt(sorted[0].v)),
        s("text", { class: "lane-label", x: lx0 + laneW / 2, y: m.top + 38, "text-anchor": "middle" }, `${list.length} value${list.length > 1 ? "s" : ""}`),
      );
      sorted.slice(0, 12).forEach((mk, i) => {
        const cx = lx0 + 12 + (i % 5) * ((laneW - 24) / 4);
        const cy = base + 2 - Math.floor(i / 5) * 12;
        svg.append(markEl(cx, cy, mk));
      });
    };
    lane(over, "right");
    lane(under, "left");
    host.append(svg);
    tip = tipBox(host);
  });
  return host;
}

/** Time series with the expected band (area), the expected line and flagged points. */
export function seriesBandChart(data, fmt = (v) => String(v)) {
  const host = h("div", { class: "chart band-chart" });
  const isTime = Boolean(data.time);
  const xs = data.x.map((v) => (isTime ? new Date(v).getTime() : Number(v)));
  const flagged = new Set(data.flagged);
  const label = `${data.column} over ${isTime ? "time" : "rows"} with its expected band; ${data.flagged.length} flagged readings are marked.`;
  responsive(host, (width) => {
    const height = 196;
    const m = { top: 12, right: 12, bottom: 26, left: 48 };
    const iw = width - m.left - m.right;
    const ih = height - m.top - m.bottom;
    const vals = [...data.y, ...data.low, ...data.high].filter((v) => v !== null && Number.isFinite(v));
    let lo = Math.min(...vals);
    let hi = Math.max(...vals);
    const pad = (hi - lo || 1) * 0.06;
    lo -= pad;
    hi += pad;
    const t0 = xs[0];
    const t1 = xs[xs.length - 1];
    const x = (t) => m.left + ((t - t0) / (t1 - t0 || 1)) * iw;
    const y = (v) => m.top + ih - ((v - lo) / (hi - lo || 1)) * ih;
    const svg = s("svg", { viewBox: `0 0 ${width} ${height}`, role: "img", "aria-label": label });
    const grid = s("g", { class: "grid" });
    const axis = s("g", { class: "axis" });
    for (const v of niceTicks(lo, hi, 4)) {
      if (v < lo || v > hi) continue;
      grid.append(s("line", { x1: m.left, x2: width - m.right, y1: y(v), y2: y(v) }));
      axis.append(s("text", { x: m.left - 8, y: y(v) + 4, "text-anchor": "end" }, fmt(v)));
    }
    const n = Math.max(2, Math.floor(iw / 110));
    for (let i = 0; i <= n; i += 1) {
      const t = t0 + ((t1 - t0) * i) / n;
      const text = isTime ? new Date(t).toLocaleDateString(undefined, { month: "short", day: "numeric" }) : String(Math.round(t));
      axis.append(s("text", { x: x(t), y: height - 6, "text-anchor": i === 0 ? "start" : i === n ? "end" : "middle" }, text));
    }
    svg.append(grid, axis);
    let up = "";
    let down = [];
    const flush = () => {
      if (up) svg.append(s("path", { class: "band", d: `${up}${down.reverse().join("")}Z` }));
      up = "";
      down = [];
    };
    xs.forEach((t, i) => {
      if (data.low[i] === null || data.high[i] === null) { flush(); return; }
      up += `${up ? "L" : "M"}${x(t).toFixed(1)},${y(data.high[i]).toFixed(1)}`;
      down.push(`L${x(t).toFixed(1)},${y(data.low[i]).toFixed(1)}`);
    });
    flush();
    const path = (arr, cls) => {
      let d = "";
      let pen = false;
      arr.forEach((v, i) => {
        if (v === null) { pen = false; return; }
        d += `${pen ? "L" : "M"}${x(xs[i]).toFixed(1)},${y(v).toFixed(1)}`;
        pen = true;
      });
      svg.append(s("path", { class: cls, d }));
    };
    path(data.expected, "expected-line");
    path(data.y, "actual-line");
    for (const i of data.flagged) {
      if (data.y[i] === null) continue;
      svg.append(s("circle", { class: "anomaly", cx: x(xs[i]), cy: y(data.y[i]), r: 3.5 }));
    }
    const cross = s("line", { class: "crosshair", y1: m.top, y2: m.top + ih, visibility: "hidden" });
    const dot = s("circle", { class: "hover-dot", r: 4.5, visibility: "hidden" });
    const hit = s("rect", { x: m.left, y: m.top, width: iw, height: ih, fill: "transparent" });
    svg.append(cross, dot, hit);
    host.append(svg);
    const tip = tipBox(host);
    const move = (ev) => {
      const r = svg.getBoundingClientRect();
      const sc = r.width / width;
      const px = (ev.clientX - r.left) / sc;
      const t = t0 + ((px - m.left) / iw) * (t1 - t0);
      let best = 0;
      for (let i = 1; i < xs.length; i += 1) if (Math.abs(xs[i] - t) < Math.abs(xs[best] - t)) best = i;
      for (const i of data.flagged) if (Math.abs(x(xs[i]) - px) < 6) { best = i; break; }
      const cx = x(xs[best]);
      cross.setAttribute("x1", cx);
      cross.setAttribute("x2", cx);
      cross.setAttribute("visibility", "visible");
      if (data.y[best] !== null) {
        dot.setAttribute("cx", cx);
        dot.setAttribute("cy", y(data.y[best]));
        dot.setAttribute("visibility", "visible");
      }
      const when = isTime ? new Date(xs[best]).toLocaleString(undefined, { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" }) : `Row ${xs[best]}`;
      tip.show([when, `Actual ${fmt(data.y[best])}${flagged.has(best) ? ", flagged" : ""}`, `Expected ${fmt(data.low[best])} to ${fmt(data.high[best])}`],
        cx * sc, y(data.y[best] ?? hi) * sc);
    };
    hit.addEventListener("pointermove", move);
    hit.addEventListener("pointerdown", move);
    hit.addEventListener("pointerleave", () => {
      cross.setAttribute("visibility", "hidden");
      dot.setAttribute("visibility", "hidden");
      tip.hide();
    });
  });
  return host;
}

/** One metric across the recent runs of a source, with the expected level shaded. */
export function historyChart(data, fmt = (v) => String(v)) {
  const host = h("div", { class: "chart band-chart" });
  const pts = data.points;
  const label = `${data.label} over the last ${pts.length} runs; expected at most ${fmt(data.band.high || 0)}.`;
  responsive(host, (width) => {
    const height = 124;
    const m = { top: 12, right: 12, bottom: 22, left: 40 };
    const iw = width - m.left - m.right;
    const ih = height - m.top - m.bottom;
    const top = Math.max(1, ...pts.map((p) => p.v), data.band.high || 0) * 1.15;
    const y = (v) => m.top + ih - (v / top) * ih;
    const slot = iw / Math.max(pts.length, 1);
    const svg = s("svg", { viewBox: `0 0 ${width} ${height}`, role: "img", "aria-label": label });
    const bandTop = y(data.band.high || 0);
    svg.append(s("rect", { class: "band", x: m.left, y: bandTop - 2, width: iw, height: Math.max(3, y(0) - bandTop + 2) }));
    const axis = s("g", { class: "axis" });
    for (const v of niceTicks(0, top, 3)) {
      if (v > top || (v % 1 && top > 3)) continue;
      axis.append(s("text", { x: m.left - 6, y: y(v) + 4, "text-anchor": "end" }, fmt(v)));
    }
    svg.append(axis);
    pts.forEach((p, i) => {
      const bw = Math.min(28, slot * 0.6);
      const cx = m.left + slot * i + slot / 2;
      const isNow = p.run_id === data.current;
      const bar = s("rect", {
        class: isNow && p.v > (data.band.high || 0) ? "bar is-anomaly" : isNow ? "bar is-current" : "bar",
        x: cx - bw / 2, y: y(p.v), width: bw, height: Math.max(p.v ? 1.5 : 0, y(0) - y(p.v)), rx: 2,
      });
      bar.append(s("title", null, `Run #${p.run_id}: ${fmt(p.v)}`));
      svg.append(bar);
      if (pts.length <= 10 || isNow) svg.append(s("text", { class: "axis-label", x: cx, y: height - 6, "text-anchor": "middle" }, `#${p.run_id}`));
    });
    svg.append(s("line", { class: "baseline", x1: m.left, x2: m.left + iw, y1: y(0), y2: y(0) }));
    host.append(svg);
  });
  return host;
}

/** Tiny trend line for tables: points [{v}] -> inline SVG. */
export function sparkline(points, { width = 88, height = 24, label = "Trend" } = {}) {
  const vals = points.map((p) => p.v).filter((v) => v !== null && Number.isFinite(v));
  const svg = s("svg", { class: "spark", width, height, viewBox: `0 0 ${width} ${height}`, role: "img", "aria-label": label });
  if (!vals.length) return svg;
  let lo = Math.min(...vals);
  let hi = Math.max(...vals);
  if (hi - lo < 0.01) { lo -= 0.005; hi += 0.005; }
  const x = (i) => (vals.length === 1 ? width - 4 : 3 + (i / (vals.length - 1)) * (width - 7));
  const y = (v) => 4 + (1 - (v - lo) / (hi - lo)) * (height - 8);
  svg.append(s("path", { class: "spark-line", d: vals.map((v, i) => `${i ? "L" : "M"}${x(i).toFixed(1)},${y(v).toFixed(1)}`).join("") }));
  svg.append(s("circle", { class: "spark-dot", cx: x(vals.length - 1), cy: y(vals[vals.length - 1]), r: 2.5 }));
  return svg;
}
