// Number, time and label formatting shared by every page.

const nf = new Intl.NumberFormat("en-US");

export function fmtInt(v: number | null | undefined): string {
  if (v === null || v === undefined || Number.isNaN(v)) return "–";
  return nf.format(Math.round(v));
}

/** Statistics: grouped thousands, trimmed precision. */
export function fmtNum(v: unknown, digits = 4): string {
  if (v === null || v === undefined || v === "") return "–";
  if (typeof v !== "number") return String(v);
  if (!Number.isFinite(v)) return String(v);
  if (Number.isInteger(v)) return nf.format(v);
  if (Math.abs(v) >= 1000) return nf.format(Math.round(v * 10) / 10);
  return String(Number(v.toPrecision(digits)));
}

/** Short value for chart axes and labels. */
export function fmtShort(v: unknown): string {
  if (typeof v !== "number") return fmtValue(v);
  if (Math.abs(v) >= 100) return fmtInt(v);
  return fmtNum(v, 4);
}

export function fmtPct(v: number | null | undefined, digits = 1): string {
  if (v === null || v === undefined || Number.isNaN(v)) return "–";
  return `${(v * 100).toFixed(digits)}%`;
}

/** Raw data values: no digit grouping (ids, years), trimmed float noise. */
export function fmtValue(v: unknown): string {
  if (v === null || v === undefined) return "null";
  if (typeof v === "number") {
    if (Number.isInteger(v) || !Number.isFinite(v)) return String(v);
    return String(Number(v.toPrecision(10)));
  }
  if (typeof v === "boolean") return v ? "true" : "false";
  if (typeof v === "object") return JSON.stringify(v);
  return String(v);
}

export function parseTime(t: string | null | undefined): Date | null {
  if (!t) return null;
  // the API stores "YYYY-MM-DD HH:MM:SS" (local, from data) and ISO with offset
  const d = new Date(t.includes("T") || t.length <= 10 ? t : t.replace(" ", "T"));
  return Number.isNaN(d.getTime()) ? null : d;
}

export function fmtTime(t: string | null | undefined): string {
  const d = parseTime(t);
  if (!d) return "–";
  return d.toLocaleString(undefined, { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" });
}

export function fmtAgo(t: string | null | undefined, now: number = Date.now()): string {
  const d = parseTime(t);
  if (!d) return "–";
  const sec = Math.round((now - d.getTime()) / 1000);
  if (sec < 45) return "just now";
  const min = Math.round(sec / 60);
  if (min < 60) return `${min} min ago`;
  const hr = Math.round(min / 60);
  if (hr < 36) return `${hr} h ago`;
  const days = Math.round(hr / 24);
  if (days < 30) return `${days} d ago`;
  return fmtTime(t);
}

export function fmtMs(ms: number | null | undefined): string {
  if (ms === null || ms === undefined) return "–";
  if (ms < 1000) return `${Math.round(ms)} ms`;
  if (ms < 60000) return `${(ms / 1000).toFixed(1)} s`;
  return `${Math.floor(ms / 60000)} min ${Math.round((ms % 60000) / 1000)} s`;
}

export function fmtBytes(n: number | null | undefined): string {
  if (n === null || n === undefined) return "–";
  const units = ["B", "KB", "MB", "GB"];
  let i = 0;
  let v = n;
  while (v >= 1024 && i < units.length - 1) {
    v /= 1024;
    i += 1;
  }
  return `${v.toFixed(i ? 1 : 0)} ${units[i]}`;
}

/** "+46% above range" from a signed fraction measured past the band edge. */
export function fmtDelta(d: number | null | undefined): string | null {
  if (d === null || d === undefined) return null;
  if (d === 0) return "within range";
  const pct = Math.abs(d) * 100;
  const text = pct >= 1000 ? `${fmtInt(pct)}%` : pct >= 10 ? `${pct.toFixed(0)}%` : `${pct.toFixed(1)}%`;
  return `${d > 0 ? "+" : "−"}${text} ${d > 0 ? "above" : "below"} range`;
}

/** Quality change in points since the previous run, e.g. "+1.2" or "−0.4". */
export function fmtPoints(trend: number | null | undefined): string {
  if (trend === null || trend === undefined) return "–";
  const pts = trend * 100;
  if (Math.abs(pts) < 0.05) return "0.0";
  return `${pts > 0 ? "+" : "−"}${Math.abs(pts).toFixed(1)}`;
}

export function fmtSchedule(seconds: number | null | undefined): string {
  if (!seconds) return "manual";
  if (seconds % 86400 === 0) return `every ${seconds / 86400} d`;
  if (seconds % 3600 === 0) return `every ${seconds / 3600} h`;
  if (seconds % 60 === 0) return `every ${seconds / 60} min`;
  return `every ${seconds} s`;
}

export const ANALYSIS_PREFIX = "analysis:";
export const isAnalysis = (p: string | null | undefined) => Boolean(p && p.startsWith(ANALYSIS_PREFIX));
/** "analysis:orders.csv" -> "orders.csv"; pipeline names pass through. */
export const runLabel = (p: string | null | undefined) => (p && p.startsWith(ANALYSIS_PREFIX) ? p.slice(ANALYSIS_PREFIX.length) : p || "–");

export function plural(n: number, one: string, many = `${one}s`): string {
  return `${fmtInt(n)} ${n === 1 ? one : many}`;
}

/** Parse what a reviewer typed: numbers stay numbers, empty means null. */
export function parseTyped(text: string): string | number | boolean | null {
  const t = text.trim();
  if (t === "" || t.toLowerCase() === "null") return null;
  if (t === "true") return true;
  if (t === "false") return false;
  if (/^[-+]?(\d+\.?\d*|\.\d+)([eE][-+]?\d+)?$/.test(t)) return Number(t);
  return text;
}

export function titleCase(s: string): string {
  return s ? s[0].toUpperCase() + s.slice(1) : s;
}
