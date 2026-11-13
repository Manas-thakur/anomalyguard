// WCAG contrast check of the design tokens in src/index.css, for both themes.
// Text pairs need 4.5:1; chart marks, status dots and the focus ring need 3:1.
//   node scripts/contrast.mjs        (exits 1 if a pair fails)

import { readFileSync } from "node:fs";

const css = readFileSync(new URL("../src/index.css", import.meta.url), "utf8");

function block(selector) {
  const start = css.indexOf(`${selector} {`);
  const body = css.slice(start, css.indexOf("\n}", start));
  const out = {};
  for (const m of body.matchAll(/--([\w-]+):\s*oklch\(([^)]+)\)/g)) {
    const [l, c, h, , a] = m[2].trim().split(/\s+/);
    out[m[1]] = { l: Number(l), c: Number(c), h: Number(h), a: a === undefined ? 1 : Number(a) };
  }
  return out;
}

function oklchToLinear({ l, c, h }) {
  const hr = (h * Math.PI) / 180;
  const a = c * Math.cos(hr);
  const b = c * Math.sin(hr);
  const l_ = (l + 0.3963377774 * a + 0.2158037573 * b) ** 3;
  const m_ = (l - 0.1055613458 * a - 0.0638541728 * b) ** 3;
  const s_ = (l - 0.0894841775 * a - 1.291485548 * b) ** 3;
  const clamp = (v) => Math.min(1, Math.max(0, v));
  return [
    clamp(4.0767416621 * l_ - 3.3077115913 * m_ + 0.2309699292 * s_),
    clamp(-1.2684380046 * l_ + 2.6097574011 * m_ - 0.3413193965 * s_),
    clamp(-0.0041960863 * l_ - 0.7034186147 * m_ + 1.707614701 * s_),
  ];
}

const toSrgb = (lin) => lin.map((v) => (v <= 0.0031308 ? 12.92 * v : 1.055 * v ** (1 / 2.4) - 0.055));
const toLin = (srgb) => srgb.map((v) => (v <= 0.04045 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4));
const luminance = (lin) => 0.2126 * lin[0] + 0.7152 * lin[1] + 0.0722 * lin[2];

/** Colour of `fg` (possibly translucent) drawn over the opaque `bg`. */
function over(fg, bg) {
  const f = toSrgb(oklchToLinear(fg));
  const b = toSrgb(oklchToLinear(bg));
  return toLin(f.map((v, i) => v * fg.a + b[i] * (1 - fg.a)));
}

function ratio(fg, bg, base) {
  const bgLin = bg.a < 1 ? over(bg, base) : oklchToLinear(bg);
  const bgSolid = { ...bg, a: 1 };
  const fgLin = fg.a < 1 ? over(fg, bg.a < 1 ? base : bgSolid) : oklchToLinear(fg);
  const [hi, lo] = [luminance(fgLin), luminance(bgLin)].sort((x, y) => y - x);
  return (hi + 0.05) / (lo + 0.05);
}

const TEXT = [
  ["foreground", "background"],
  ["foreground", "card"],
  ["muted-foreground", "background"],
  ["muted-foreground", "card"],
  ["muted-foreground", "muted"],
  ["primary-foreground", "primary"],
  ["primary", "card"],
  ["accent-foreground", "accent"],
  ["sev-high", "card"],
  ["sev-high", "sev-high-soft"],
  ["sev-medium", "card"],
  ["sev-medium", "sev-medium-soft"],
  ["sev-low", "card"],
  ["sev-low", "sev-low-soft"],
  ["ok", "card"],
  ["ok", "ok-soft"],
  ["sidebar-foreground", "sidebar"],
  ["sidebar-accent-foreground", "sidebar-accent"],
];
const GRAPHICS = [
  ["anomaly", "card"],
  ["anomaly", "band"],
  ["line", "card"],
  ["line", "band"],
  ["bar", "card"],
  ["ring", "card"],
  ["sev-high", "card"],
  ["sev-medium", "card"],
  ["ok", "card"],
  ...["chart-1", "chart-2", "chart-3", "chart-4", "chart-5", "chart-6"].map((c) => [c, "card"]),
];

let failed = 0;
for (const [theme, sel] of [
  ["light", ":root"],
  ["dark", ".dark"],
]) {
  const t = { ...block(":root"), ...block(sel) };
  const base = t.card;
  for (const [pairs, min] of [
    [TEXT, 4.5],
    [GRAPHICS, 3],
  ]) {
    for (const [fg, bg] of pairs) {
      const r = ratio(t[fg], t[bg], base);
      const ok = r >= min;
      if (!ok) failed += 1;
      console.log(`${ok ? "ok  " : "FAIL"} ${theme.padEnd(5)} ${fg.padEnd(26)} on ${bg.padEnd(16)} ${r.toFixed(2)} (min ${min})`);
    }
  }
}
if (failed) {
  console.error(`\n${failed} pair(s) below the WCAG AA minimum`);
  process.exit(1);
}
