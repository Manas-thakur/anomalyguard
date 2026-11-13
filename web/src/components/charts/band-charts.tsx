// Expected-band charts for incidents (Recharts through the shadcn chart
// container). The shaded band is the robust expected range, actual values are
// neutral ink, and flagged values use the anomaly colour so the break-out reads
// at a glance. Values far outside the plotted range go to an overflow lane so a
// single extreme value does not flatten the chart.

import { useMemo, useState } from "react";
import {
  Area,
  Bar,
  BarChart,
  Cell,
  ComposedChart,
  Line,
  ReferenceArea,
  ReferenceLine,
  Scatter,
  XAxis,
  YAxis,
} from "recharts";

import { ChartContainer, ChartTooltip, type ChartConfig } from "@/components/ui/chart";
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group";
import { fmtInt, fmtShort, parseTime } from "@/lib/format";
import type { DistributionChart, HistoryChart, SeriesChart } from "@/lib/types";
import { cn } from "@/lib/utils";

const config = {
  bar: { label: "Rows", color: "var(--bar)" },
  actual: { label: "Actual", color: "var(--line)" },
  expected: { label: "Expected", color: "var(--band-edge)" },
  band: { label: "Expected range", color: "var(--band)" },
  anomaly: { label: "Flagged", color: "var(--anomaly)" },
} satisfies ChartConfig;

function TipBox({ lines }: { lines: string[] }) {
  return (
    <div className="bg-popover text-popover-foreground grid min-w-32 gap-0.5 rounded-lg border px-2.5 py-1.5 text-xs shadow-lg">
      {lines.map((l, i) => (
        <div key={i} className={i === 0 ? "font-medium" : "text-muted-foreground tabular"}>
          {l}
        </div>
      ))}
    </div>
  );
}

export function Legend({ items }: { items: { kind: "band" | "bar" | "line" | "anomaly" | "ring" | "dashed"; label: string }[] }) {
  return (
    <ul className="text-muted-foreground flex flex-wrap gap-x-4 gap-y-1 text-xs" aria-label="Legend">
      {items.map((it) => (
        <li key={it.label} className="flex items-center gap-1.5">
          <span
            aria-hidden
            className={cn(
              "inline-block",
              it.kind === "band" && "h-2.5 w-3.5 rounded-sm border border-[var(--band-edge)] bg-[var(--band)]",
              it.kind === "bar" && "h-2.5 w-2.5 rounded-[2px] bg-[var(--bar)]",
              it.kind === "line" && "h-0.5 w-3.5 rounded bg-[var(--line)]",
              it.kind === "dashed" && "h-0 w-3.5 border-t-2 border-dashed border-[var(--band-edge)]",
              it.kind === "anomaly" && "size-2.5 rounded-full bg-[var(--anomaly)]",
              it.kind === "ring" && "size-2.5 rounded-full border-2 border-[var(--anomaly)]",
            )}
          />
          {it.label}
        </li>
      ))}
    </ul>
  );
}

/** Round tick values inside [lo, hi]. */
export function niceTicks(lo: number, hi: number, count = 4): number[] {
  const span = hi - lo || 1;
  const raw = span / Math.max(1, count);
  const p = 10 ** Math.floor(Math.log10(raw));
  const n = raw / p;
  const step = (n <= 1 ? 1 : n <= 2 ? 2 : n <= 2.5 ? 2.5 : n <= 5 ? 5 : 10) * p;
  const out: number[] = [];
  for (let v = Math.ceil(lo / step) * step; v <= hi + step * 1e-9; v += step) out.push(Number(v.toPrecision(12)));
  return out;
}

function OverflowLane({ side, marks }: { side: "above" | "below"; marks: DistributionChart["marks"] }) {
  const sorted = [...marks].sort((a, b) => (side === "above" ? b.v - a.v : a.v - b.v));
  return (
    <div className="bg-sev-high-soft/60 border-sev-high/20 flex w-[84px] shrink-0 flex-col items-center justify-center gap-1 rounded-lg border px-1.5 py-2 text-center">
      <span className="text-muted-foreground text-[11px] leading-tight">far {side}</span>
      <span className="text-sev-high text-sm font-semibold tabular">{fmtShort(sorted[0].v)}</span>
      <span className="text-muted-foreground text-[11px] leading-tight">
        {marks.length} value{marks.length > 1 ? "s" : ""}
      </span>
      <ul className="mt-0.5 flex flex-wrap justify-center gap-1" aria-label={`Values far ${side} the range`}>
        {sorted.slice(0, 10).map((m, i) => (
          <li key={i} className="size-2 rounded-full bg-[var(--anomaly)]" title={`Row ${m.row}: ${fmtShort(m.v)}`}>
            <span className="sr-only">
              Row {String(m.row)}: {fmtShort(m.v)}
            </span>
          </li>
        ))}
      </ul>
    </div>
  );
}

/** Histogram of one column with the expected band and flagged values on a strip below. */
export function DistributionBandChart({ data, groupedBy }: { data: DistributionChart; groupedBy?: string[] }) {
  const [d0, d1] = data.domain;
  const band = data.band;
  const hasBand = band.low !== null && band.high !== null;
  const { bins, inside, over, under, max } = useMemo(() => {
    const bins = data.counts.map((c, i) => ({ bin: i, count: c, lo: data.edges[i], hi: data.edges[i + 1] }));
    const max = Math.max(1, ...data.counts);
    const inside = data.marks.filter((m) => m.v >= d0 && m.v <= d1);
    // spread overlapping marks into two rows so density stays readable
    const used = new Map<number, number>();
    const placed = inside.slice(0, 250).map((m) => {
      const k = Math.round(((m.v - d0) / (d1 - d0 || 1)) * 90);
      const n = used.get(k) ?? 0;
      used.set(k, n + 1);
      const inBand = hasBand && m.v >= (band.low as number) && m.v <= (band.high as number);
      return { x: m.v, y: n % 2 ? 0.07 : 0.16, row: m.row, inBand };
    });
    return { bins, inside: placed, over: data.marks.filter((m) => m.v > d1), under: data.marks.filter((m) => m.v < d0), max };
  }, [data, d0, d1, hasBand, band.low, band.high]);

  const label = `Distribution of ${data.column}${hasBand ? `, expected ${fmtShort(band.low)} to ${fmtShort(band.high)}` : ""}; ${data.marks.length} flagged values${over.length ? `, ${over.length} far above, up to ${fmtShort(data.max)}` : ""}${under.length ? `, ${under.length} far below, down to ${fmtShort(data.min)}` : ""}.`;
  const anyInBand = inside.some((m) => m.inBand);

  return (
    <figure className="space-y-2">
      <div className="flex items-stretch gap-2" role="img" aria-label={label}>
        {under.length ? <OverflowLane side="below" marks={under} /> : null}
        <ChartContainer config={config} className="aspect-auto h-[176px] min-w-0 flex-1" aria-hidden>
          <ComposedChart data={bins} margin={{ top: 16, right: 8, bottom: 0, left: 8 }} accessibilityLayer={false}>
            <XAxis xAxisId="cat" dataKey="bin" type="category" hide />
            <XAxis
              xAxisId="num"
              type="number"
              dataKey="x"
              domain={[d0, d1]}
              allowDataOverflow
              tickLine={false}
              axisLine={false}
              tickMargin={6}
              ticks={niceTicks(d0, d1, 5)}
              interval={0}
              tickFormatter={(v: number) => fmtShort(v)}
            />
            <YAxis yAxisId="count" domain={[-max * 0.34, max * 1.04]} hide />
            <YAxis yAxisId="strip" domain={[0, 1]} hide />
            {hasBand ? (
              <ReferenceArea
                xAxisId="num"
                yAxisId="strip"
                x1={Math.max(band.low as number, d0)}
                x2={Math.min(band.high as number, d1)}
                y1={0}
                y2={1}
                fill="var(--band)"
                stroke="var(--band-edge)"
                strokeDasharray="3 3"
                ifOverflow="hidden"
                label={{ value: "expected", position: "insideTop", fill: "var(--muted-foreground)", fontSize: 11, offset: 4 }}
              />
            ) : null}
            <ReferenceLine xAxisId="cat" yAxisId="count" y={0} stroke="var(--border)" />
            <Bar xAxisId="cat" yAxisId="count" dataKey="count" fill="var(--color-bar)" radius={[2, 2, 0, 0]} isAnimationActive={false} />
            <Scatter
              xAxisId="num"
              yAxisId="strip"
              data={inside}
              dataKey="y"
              isAnimationActive={false}
              shape={(props: unknown) => {
                const p = props as { cx: number; cy: number; payload: { inBand: boolean } };
                return p.payload.inBand ? (
                  <circle cx={p.cx} cy={p.cy} r={3.5} fill="var(--card)" stroke="var(--anomaly)" strokeWidth={2} />
                ) : (
                  <circle cx={p.cx} cy={p.cy} r={4} fill="var(--anomaly)" stroke="var(--card)" strokeWidth={1.5} />
                );
              }}
            />
            <ChartTooltip
              cursor={false}
              shared={false}
              content={({ active, payload }) => {
                if (!active || !payload?.length) return null;
                const p = payload[0].payload as { count?: number; lo?: number; hi?: number; x?: number; row?: unknown; inBand?: boolean };
                if (p.row !== undefined) return <TipBox lines={[`Row ${String(p.row)}`, `${fmtShort(p.x)} · ${p.inBand ? "flagged in its group, inside the range" : "outside the expected range"}`]} />;
                return <TipBox lines={[`${fmtShort(p.lo)} to ${fmtShort(p.hi)}`, `${fmtInt(p.count)} rows`]} />;
              }}
            />
          </ComposedChart>
        </ChartContainer>
        {over.length ? <OverflowLane side="above" marks={over} /> : null}
      </div>
      <figcaption>
        <Legend
          items={[
            ...(hasBand ? [{ kind: "band" as const, label: "expected range" }] : []),
            { kind: "bar", label: "rows" },
            { kind: "anomaly", label: "flagged, outside the range" },
            ...(anyInBand ? [{ kind: "ring" as const, label: groupedBy?.length ? `flagged within its ${groupedBy.join(", ")}` : "flagged in context" }] : []),
          ]}
        />
      </figcaption>
    </figure>
  );
}

function fmtX(x: string | number, isTime: boolean, long = false): string {
  if (!isTime) return `Row ${x}`;
  const d = parseTime(String(x));
  if (!d) return String(x);
  return long
    ? d.toLocaleString(undefined, { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" })
    : d.toLocaleDateString(undefined, { month: "short", day: "numeric" });
}

/** Time series with the expected band, the expected line and flagged readings. */
export function SeriesBandChart({ data }: { data: SeriesChart }) {
  const hasFocus = Boolean(data.focus);
  const [view, setView] = useState<"focus" | "all">(hasFocus ? "focus" : "all");
  const isTime = Boolean(data.time);
  const rows = useMemo(() => {
    const flagged = new Set(data.flagged);
    const [a, b] = view === "focus" && data.focus ? data.focus : [0, data.x.length - 1];
    const out = [];
    for (let i = a; i <= b; i += 1) {
      const low = data.low[i];
      const high = data.high[i];
      out.push({
        i,
        x: data.x[i],
        y: data.y[i],
        expected: data.expected[i],
        band: low === null || high === null ? null : [low, high],
        low,
        high,
        flag: flagged.has(i) ? data.y[i] : null,
      });
    }
    return out;
  }, [data, view]);
  const nFlag = rows.filter((r) => r.flag !== null).length;
  const label = `${data.column} over ${isTime ? "time" : "rows"} with its expected band; ${nFlag} flagged readings are marked.`;

  return (
    <figure className="space-y-2">
      {hasFocus ? (
        <ToggleGroup
          type="single"
          size="sm"
          variant="outline"
          value={view}
          onValueChange={(v) => v && setView(v as "focus" | "all")}
          aria-label="Chart range"
          className="ml-auto"
        >
          <ToggleGroupItem value="focus" className="px-2.5 text-xs">
            Around the anomaly
          </ToggleGroupItem>
          <ToggleGroupItem value="all" className="px-2.5 text-xs">
            Full history
          </ToggleGroupItem>
        </ToggleGroup>
      ) : null}
      <div role="img" aria-label={label}>
        <ChartContainer config={config} className="aspect-auto h-[208px] w-full" aria-hidden>
          <ComposedChart data={rows} margin={{ top: 8, right: 8, bottom: 0, left: 0 }} accessibilityLayer={false}>
            <XAxis
              dataKey="i"
              type="number"
              domain={["dataMin", "dataMax"]}
              tickLine={false}
              axisLine={false}
              tickMargin={6}
              minTickGap={40}
              tickFormatter={(i: number) => fmtX(data.x[i], isTime)}
            />
            <YAxis width={44} tickLine={false} axisLine={false} tickFormatter={(v: number) => fmtShort(v)} domain={["auto", "auto"]} tickCount={4} />
            <Area dataKey="band" stroke="none" fill="var(--band)" isAnimationActive={false} connectNulls={false} activeDot={false} />
            <Line dataKey="expected" stroke="var(--band-edge)" strokeDasharray="4 3" strokeWidth={1.25} dot={false} isAnimationActive={false} activeDot={false} />
            <Line dataKey="y" stroke="var(--color-actual)" strokeWidth={1.4} dot={false} isAnimationActive={false} activeDot={{ r: 4, fill: "var(--color-actual)", stroke: "var(--card)" }} />
            <Line
              dataKey="flag"
              stroke="none"
              isAnimationActive={false}
              activeDot={false}
              dot={(props: unknown) => {
                const p = props as { cx?: number; cy?: number; value?: number | null; index: number };
                if (p.value === null || p.value === undefined || p.cx === undefined || p.cy === undefined) return <g key={p.index} />;
                return <circle key={p.index} cx={p.cx} cy={p.cy} r={3.5} fill="var(--anomaly)" stroke="var(--card)" strokeWidth={1.5} />;
              }}
            />
            <ChartTooltip
              cursor={{ stroke: "var(--muted-foreground)", strokeDasharray: "3 3" }}
              content={({ active, payload }) => {
                if (!active || !payload?.length) return null;
                const p = payload[0].payload as (typeof rows)[number];
                return (
                  <TipBox
                    lines={[
                      fmtX(p.x, isTime, true),
                      `Actual ${fmtShort(p.y)}${p.flag !== null ? " · flagged" : ""}`,
                      `Expected ${fmtShort(p.low)} to ${fmtShort(p.high)}`,
                    ]}
                  />
                );
              }}
            />
          </ComposedChart>
        </ChartContainer>
      </div>
      <figcaption>
        <Legend
          items={[
            { kind: "band", label: "expected range" },
            { kind: "dashed", label: "expected" },
            { kind: "line", label: "actual" },
            { kind: "anomaly", label: "flagged" },
          ]}
        />
      </figcaption>
    </figure>
  );
}

/** One metric across the recent runs of a source, with the expected level shaded. */
export function HistoryBandChart({ data }: { data: HistoryChart }) {
  const high = data.band.high || 0;
  const rows = data.points.map((p) => ({ ...p, label: `#${p.run_id}`, now: p.run_id === data.current }));
  const label = `${data.label} over the last ${rows.length} runs; expected at most ${fmtShort(high)}.`;
  return (
    <figure className="space-y-2">
      <div role="img" aria-label={label}>
        <ChartContainer config={config} className="aspect-auto h-[132px] w-full" aria-hidden>
          <BarChart data={rows} margin={{ top: 8, right: 8, bottom: 0, left: 0 }} accessibilityLayer={false}>
            <XAxis dataKey="label" tickLine={false} axisLine={false} tickMargin={6} />
            <YAxis width={36} tickLine={false} axisLine={false} allowDecimals={false} tickCount={3} tickFormatter={(v: number) => fmtShort(v)} />
            {high > 0 ? <ReferenceArea y1={0} y2={high} fill="var(--band)" stroke="var(--band-edge)" strokeDasharray="3 3" /> : <ReferenceLine y={0} stroke="var(--band-edge)" strokeWidth={2} />}
            <Bar dataKey="v" radius={[3, 3, 0, 0]} maxBarSize={32} isAnimationActive={false}>
              {rows.map((r) => (
                <Cell key={r.run_id} fill={r.now && r.v > high ? "var(--anomaly)" : r.now ? "var(--line)" : "var(--bar)"} />
              ))}
            </Bar>
            <ChartTooltip cursor={{ fill: "var(--muted)" }} content={({ active, payload }) => (active && payload?.length ? <TipBox lines={[`Run ${(payload[0].payload as { label: string }).label}`, `${data.label}: ${fmtInt(payload[0].value as number)}`]} /> : null)} />
          </BarChart>
        </ChartContainer>
      </div>
      <figcaption>
        <Legend
          items={[
            { kind: "band", label: high > 0 ? "expected" : "expected: none" },
            { kind: "bar", label: "earlier runs" },
            { kind: "anomaly", label: "this run" },
          ]}
        />
      </figcaption>
    </figure>
  );
}
