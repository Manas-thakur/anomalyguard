// Compact charts: table sparklines, column-card histograms and the Health trend
// chart (one line per source on a real time axis, toggleable legend).

import { useMemo, useState } from "react";
import { Bar, BarChart, CartesianGrid, Line, LineChart, XAxis, YAxis } from "recharts";

import { ChartContainer, ChartTooltip, type ChartConfig } from "@/components/ui/chart";
import { useIsMobile } from "@/hooks/use-mobile";
import { fmtInt, fmtPct, fmtShort, fmtTime, runLabel } from "@/lib/format";
import type { SeriesPoint } from "@/lib/types";
import { cn } from "@/lib/utils";

const sparkConfig = { v: { label: "Quality", color: "var(--chart-1)" } } satisfies ChartConfig;

export function Sparkline({ points, label, className, hideOnMobile }: { points: { v: number | null }[]; label: string; className?: string; hideOnMobile?: boolean }) {
  const mobile = useIsMobile();
  if (hideOnMobile && mobile) return null;
  return <SparklineChart points={points} label={label} className={className} />;
}

function SparklineChart({ points, label, className }: { points: { v: number | null }[]; label: string; className?: string }) {
  const data = points.filter((p) => p.v !== null && Number.isFinite(p.v)).map((p, i) => ({ i, v: p.v as number }));
  if (!data.length) return <span className={cn("inline-block h-6 w-[88px]", className)} aria-hidden />;
  const vals = data.map((d) => d.v);
  let lo = Math.min(...vals);
  let hi = Math.max(...vals);
  if (hi - lo < 0.01) {
    lo -= 0.005;
    hi += 0.005;
  }
  const last = data.length - 1;
  return (
    <span role="img" aria-label={label} className={cn("inline-block h-6 w-[88px]", className)}>
      <ChartContainer config={sparkConfig} className="aspect-auto h-6 w-[88px]" aria-hidden initialDimension={{ width: 88, height: 24 }}>
        <LineChart data={data.length === 1 ? [data[0], { ...data[0], i: 1 }] : data} margin={{ top: 3, right: 3, bottom: 3, left: 3 }} accessibilityLayer={false}>
          <YAxis domain={[lo, hi]} hide />
          <XAxis dataKey="i" type="number" domain={["dataMin", "dataMax"]} hide />
          <Line
            dataKey="v"
            stroke="var(--color-v)"
            strokeWidth={1.5}
            isAnimationActive={false}
            dot={(p: { index: number; cx?: number; cy?: number }) =>
              p.index === (data.length === 1 ? 1 : last) && p.cx !== undefined && p.cy !== undefined ? (
                <circle key={p.index} cx={p.cx} cy={p.cy} r={2.5} fill="var(--color-v)" />
              ) : (
                <g key={p.index} />
              )
            }
          />
        </LineChart>
      </ChartContainer>
    </span>
  );
}

const histConfig = { count: { label: "Rows", color: "var(--bar)" }, tail: { label: "Beyond p1/p99", color: "var(--anomaly)" } } satisfies ChartConfig;

export function MiniHistogram({ hist, column }: { hist: { edges: number[]; counts: number[]; below?: number; above?: number }; column: string }) {
  const data = useMemo(() => {
    const out: { key: string; count: number; tail: boolean; label: string }[] = [];
    if (hist.below) out.push({ key: "below", count: hist.below, tail: true, label: `${fmtInt(hist.below)} below ${fmtShort(hist.edges[0])}` });
    hist.counts.forEach((c, i) => out.push({ key: String(i), count: c, tail: false, label: `${fmtShort(hist.edges[i])} to ${fmtShort(hist.edges[i + 1])}: ${fmtInt(c)}` }));
    if (hist.above) out.push({ key: "above", count: hist.above, tail: true, label: `${fmtInt(hist.above)} above ${fmtShort(hist.edges[hist.edges.length - 1])}` });
    return out;
  }, [hist]);
  return (
    <div role="img" aria-label={`Distribution of ${column} from ${fmtShort(hist.edges[0])} to ${fmtShort(hist.edges[hist.edges.length - 1])}`}>
      <ChartContainer config={histConfig} className="aspect-auto h-12 w-full" aria-hidden>
        <BarChart data={data} margin={{ top: 2, right: 0, bottom: 0, left: 0 }} barCategoryGap={1} accessibilityLayer={false}>
          <XAxis dataKey="key" hide />
          <Bar dataKey="count" radius={[1.5, 1.5, 0, 0]} isAnimationActive={false} shape={(p: unknown) => {
            const b = p as { x: number; y: number; width: number; height: number; payload: { tail: boolean } };
            return <rect x={b.x} y={b.y} width={Math.max(1, b.width)} height={Math.max(b.height, b.height > 0 ? 1 : 0)} rx={1} fill={b.payload.tail ? "var(--anomaly)" : "var(--bar)"} />;
          }} />
          <ChartTooltip cursor={{ fill: "var(--muted)" }} content={({ active, payload }) => (active && payload?.length ? <div className="bg-popover rounded-md border px-2 py-1 text-xs shadow-md tabular">{(payload[0].payload as { label: string }).label}</div> : null)} />
        </BarChart>
      </ChartContainer>
    </div>
  );
}

const SERIES_COLORS = ["var(--chart-1)", "var(--chart-2)", "var(--chart-3)", "var(--chart-4)", "var(--chart-5)", "var(--chart-6)"];
export const MAX_SERIES = SERIES_COLORS.length;

export interface TrendSeries {
  pipeline: string;
  points: SeriesPoint[];
}

/** Quality or anomaly rate over time, one line per source; click a point to open the run. */
export function TrendChart({ series, metric, onOpenRun }: { series: TrendSeries[]; metric: "quality_score" | "anomaly_rate"; onOpenRun?: (id: number) => void }) {
  const [hidden, setHidden] = useState<Set<string>>(new Set());
  const keys = useMemo(() => series.map((s) => s.pipeline).sort(), [series]);
  const shown = useMemo(
    () =>
      [...series]
        .sort((a, b) => b.points.length - a.points.length)
        .slice(0, MAX_SERIES)
        .sort((a, b) => a.pipeline.localeCompare(b.pipeline)),
    [series],
  );
  const config = Object.fromEntries(shown.map((s) => [`s${keys.indexOf(s.pipeline)}`, { label: runLabel(s.pipeline), color: SERIES_COLORS[keys.indexOf(s.pipeline) % SERIES_COLORS.length] }])) satisfies ChartConfig;
  const isQ = metric === "quality_score";
  const lines = shown.map((s) => ({
    key: `s${keys.indexOf(s.pipeline)}`,
    pipeline: s.pipeline,
    data: s.points
      .filter((p) => p.status !== "failed" && p[metric] !== null)
      .map((p) => ({ t: new Date(p.started_at).getTime(), v: p[metric] as number, id: p.id, rows: p.rows, pipeline: s.pipeline })),
  }));
  const all = lines.flatMap((l) => l.data);
  if (!all.length) return <p className="text-muted-foreground py-8 text-center text-sm">No finished runs yet.</p>;
  const vals = all.map((p) => p.v);
  const yMin = isQ ? Math.min(0.8, Math.floor(Math.min(...vals) * 20) / 20) : 0;
  const yMax = isQ ? 1 : Math.max(0.01, Math.max(...vals) * 1.15);
  const ts = all.map((p) => p.t);
  const span = Math.max(...ts) - Math.min(...ts);
  const fmtT = (t: number) =>
    span > 2 * 86400e3 ? new Date(t).toLocaleDateString(undefined, { month: "short", day: "numeric" }) : new Date(t).toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit" });

  return (
    <figure className="space-y-3">
      <div role="img" aria-label={`${isQ ? "Quality score" : "Anomaly rate"} over time for ${lines.length} sources`}>
        <ChartContainer config={config} className="aspect-auto h-[220px] w-full" aria-hidden>
          <LineChart margin={{ top: 8, right: 12, bottom: 0, left: 0 }} accessibilityLayer={false}>
            <CartesianGrid vertical={false} strokeDasharray="3 3" />
            <XAxis
              dataKey="t"
              type="number"
              scale="time"
              domain={span ? ["dataMin", "dataMax"] : [Math.min(...ts) - 3600e3, Math.max(...ts) + 3600e3]}
              tickFormatter={fmtT}
              tickLine={false}
              axisLine={false}
              tickMargin={8}
              minTickGap={48}
              allowDuplicatedCategory={false}
            />
            <YAxis width={44} domain={[yMin, yMax]} tickFormatter={(v: number) => fmtPct(v, isQ ? 0 : 1)} tickLine={false} axisLine={false} tickCount={5} />
            {lines.map((l) =>
              hidden.has(l.key) ? null : (
                <Line
                  key={l.key}
                  data={l.data}
                  dataKey="v"
                  name={l.key}
                  stroke={`var(--color-${l.key})`}
                  strokeWidth={2}
                  isAnimationActive={false}
                  dot={{ r: 3, fill: `var(--color-${l.key})`, strokeWidth: 0 }}
                  activeDot={{
                    r: 5,
                    style: { cursor: onOpenRun ? "pointer" : undefined },
                    onClick: (_e: unknown, p: unknown) => {
                      const id = (p as { payload?: { id?: number } }).payload?.id;
                      if (id && onOpenRun) onOpenRun(id);
                    },
                  }}
                />
              ),
            )}
            <ChartTooltip
              shared={false}
              content={({ active, payload }) => {
                if (!active || !payload?.length) return null;
                const p = payload[0].payload as { t: number; v: number; id: number; rows: number; pipeline: string };
                return (
                  <div className="bg-popover grid gap-0.5 rounded-lg border px-2.5 py-1.5 text-xs shadow-lg">
                    <div className="font-medium">{runLabel(p.pipeline)}</div>
                    <div className="tabular">
                      {fmtPct(p.v, isQ ? 1 : 2)} · run #{p.id}
                    </div>
                    <div className="text-muted-foreground">
                      {fmtTime(new Date(p.t).toISOString())} · {fmtInt(p.rows)} rows
                    </div>
                  </div>
                );
              }}
            />
          </LineChart>
        </ChartContainer>
      </div>
      {lines.length > 1 ? (
        <figcaption role="group" aria-label="Series" className="flex flex-wrap gap-1.5">
          {lines.map((l) => {
            const off = hidden.has(l.key);
            return (
              <button
                key={l.key}
                type="button"
                aria-pressed={!off}
                onClick={() =>
                  setHidden((h) => {
                    const n = new Set(h);
                    if (n.has(l.key)) n.delete(l.key);
                    else n.add(l.key);
                    return n;
                  })
                }
                className={cn("hover:bg-muted flex items-center gap-1.5 rounded-md border px-2 py-1 text-xs transition-opacity", off && "opacity-50")}
              >
                <span aria-hidden className="size-2 rounded-full" style={{ background: config[l.key]?.color }} />
                <span className="max-w-[180px] truncate">{runLabel(l.pipeline)}</span>
              </button>
            );
          })}
        </figcaption>
      ) : null}
    </figure>
  );
}
