// Incident cards: plain-language tag, entity, one sentence, expected vs actual
// with the change, a chart with the expected band (loaded when scrolled into
// view) and inline triage: Mark as normal, Confirm, Mute 24h, Reopen, Unmute.

import { BellOffIcon, CheckIcon, ChevronDownIcon, FlagIcon, InfoIcon, RotateCcwIcon, TableIcon } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { Link, useNavigate } from "react-router";
import { toast } from "sonner";

import { DistributionBandChart, HistoryBandChart, SeriesBandChart } from "@/components/charts/band-charts";
import { SeverityBadge, TimeAgo } from "@/components/common";
import { Button } from "@/components/ui/button";
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "@/components/ui/collapsible";
import { HoverCard, HoverCardContent, HoverCardTrigger } from "@/components/ui/hover-card";
import { Skeleton } from "@/components/ui/skeleton";
import { Spinner } from "@/components/ui/spinner";
import { api } from "@/lib/api";
import { fmtDelta, fmtInt, fmtShort, fmtValue, titleCase } from "@/lib/format";
import { queryClient, useIncidentChart } from "@/lib/queries";
import type { Incident } from "@/lib/types";
import { cn } from "@/lib/utils";

export const KIND_HELP: Record<string, string> = {
  outlier: "Robust range: median ± 3.5 robust standard deviations (MAD) of the column.",
  pattern: "Expected = trend + daily/weekly seasonality, ± 3.5 robust standard deviations of the residual.",
  level_shift: "Expected = the level before the shift plus seasonality, ± 3.5 robust standard deviations.",
  missing: "Expected = the empty values in the previous run of this source (0 if there is none).",
  duplicates: "A clean load has no repeated rows.",
  invalid: "Rows that break the inferred or configured schema.",
  multivariate: "Rows whose combination of values is rare, even if each value looks normal.",
};

function useInView<T extends Element>(margin = "200px") {
  const ref = useRef<T>(null);
  const [seen, setSeen] = useState(false);
  useEffect(() => {
    const el = ref.current;
    if (!el || seen) return;
    const io = new IntersectionObserver((entries) => {
      if (entries.some((e) => e.isIntersecting)) {
        setSeen(true);
        io.disconnect();
      }
    }, { rootMargin: margin });
    io.observe(el);
    return () => io.disconnect();
  }, [margin, seen]);
  return [ref, seen] as const;
}

function IncidentChartSlot({ inc }: { inc: Incident }) {
  const [ref, seen] = useInView<HTMLDivElement>();
  const q = useIncidentChart(inc.run_id, inc.id, seen);
  return (
    <div ref={ref} className="min-h-[60px]">
      {!q.data && !q.error ? <Skeleton className="h-[176px] w-full rounded-lg" /> : null}
      {q.error ? <p className="text-muted-foreground text-sm">Chart unavailable: {(q.error as Error).message}</p> : null}
      {q.data?.type === "distribution" ? <DistributionBandChart data={q.data} groupedBy={inc.grouped} /> : null}
      {q.data?.type === "series" ? <SeriesBandChart data={q.data} /> : null}
      {q.data?.type === "history" && q.data.points.length ? <HistoryBandChart data={q.data} /> : null}
    </div>
  );
}

function Stat({ label, value, sub, tone }: { label: string; value: string; sub?: string | null; tone?: "actual" | "up" | "down" }) {
  return (
    <div className="min-w-0">
      <dt className="text-muted-foreground text-xs">{label}</dt>
      <dd className={cn("mt-0.5 truncate font-mono text-sm font-semibold tabular", tone === "actual" && "text-sev-high", (tone === "up" || tone === "down") && "text-foreground")} title={value}>
        {value}
      </dd>
      {sub ? (
        <dd className="text-muted-foreground truncate text-xs" title={sub}>
          {sub}
        </dd>
      ) : null}
    </div>
  );
}

export interface IncidentCardProps {
  inc: Incident;
  onChange?: (inc: Incident) => void;
  onShowColumn?: (column: string) => void;
  showSource?: boolean;
  focused?: boolean;
}

export function IncidentCard({ inc, onChange, onShowColumn, showSource, focused }: IncidentCardProps) {
  const navigate = useNavigate();
  const [busy, setBusy] = useState<string | null>(null);
  const ref = useRef<HTMLElement>(null);
  useEffect(() => {
    if (focused && ref.current) {
      ref.current.scrollIntoView({ block: "center" });
      ref.current.focus({ preventScroll: true });
    }
  }, [focused]);

  const update = (next: Incident) => {
    onChange?.(next);
    queryClient.invalidateQueries({ queryKey: ["health"] });
    queryClient.invalidateQueries({ queryKey: ["incidents"] });
    queryClient.invalidateQueries({ queryKey: ["summary"] });
  };

  async function act(action: "normal" | "confirm" | "reopen") {
    setBusy(action);
    try {
      const r = await api.post<{ incident: Incident; feedback?: number; queued?: number; rejected?: number }>(`/api/runs/${inc.run_id}/incidents/${inc.id}/triage`, { action });
      update({ ...inc, ...r.incident });
      if (action === "normal") {
        toast.success("Marked as normal", {
          description: r.feedback
            ? `${fmtInt(r.feedback)} findings recorded as false positives${r.rejected ? `, ${fmtInt(r.rejected)} review items rejected` : ""}. Tune thresholds in Settings.`
            : undefined,
        });
      } else if (action === "confirm") {
        toast.success("Confirmed", {
          description: r.queued ? `${fmtInt(r.queued)} flagged values are in the review queue.` : undefined,
          action: r.queued ? { label: "Open review", onClick: () => navigate(`/review?run=${inc.run_id}&column=${encodeURIComponent(inc.column || "")}`) } : undefined,
        });
        queryClient.invalidateQueries({ queryKey: ["review"] });
      } else toast("Reopened");
    } catch (err) {
      toast.error((err as Error).message);
    } finally {
      setBusy(null);
    }
  }

  async function mute() {
    setBusy("mute");
    try {
      const m = await api.post<{ id: number; until: string }>(`/api/runs/${inc.run_id}/incidents/${inc.id}/mute`, { hours: 24 });
      const muted = { ...inc, muted_until: m.until, mute_id: m.id };
      update(muted);
      toast(`Muted ${inc.entity} for 24 hours`, {
        action: {
          label: "Undo",
          onClick: async () => {
            await api.del(`/api/incidents/mutes/${m.id}`);
            update({ ...muted, muted_until: null, mute_id: null });
          },
        },
      });
    } catch (err) {
      toast.error((err as Error).message);
    } finally {
      setBusy(null);
    }
  }

  async function unmute() {
    if (!inc.mute_id) return;
    setBusy("unmute");
    try {
      await api.del(`/api/incidents/mutes/${inc.mute_id}`);
      update({ ...inc, muted_until: null, mute_id: null });
      toast(`Unmuted ${inc.entity}`);
    } catch (err) {
      toast.error((err as Error).message);
    } finally {
      setBusy(null);
    }
  }

  const exp = inc.expected;
  const act_ = inc.actual;
  const delta = fmtDelta(inc.delta_pct);
  const isRange = !["missing", "duplicates", "invalid"].includes(inc.kind);
  const triaged = inc.status !== "open";
  const muted = Boolean(inc.muted_until);
  const btn = (key: string, icon: React.ReactNode) => (busy === key ? <Spinner /> : icon);

  return (
    <article
      ref={ref}
      id={`incident-${inc.id}`}
      tabIndex={-1}
      aria-labelledby={`inc-title-${inc.id}`}
      className={cn(
        "bg-card relative overflow-hidden rounded-xl border shadow-xs outline-none transition-shadow focus-visible:ring-[3px] focus-visible:ring-ring/50",
        focused && "ring-primary/40 ring-2",
        (triaged || muted) && "bg-card/70",
      )}
    >
      <span aria-hidden className={cn("absolute inset-y-0 left-0 w-1", inc.severity === "high" ? "bg-sev-high" : inc.severity === "medium" ? "bg-sev-medium" : "bg-sev-low", (triaged || muted) && "opacity-40")} />
      <div className="space-y-4 p-4 pl-5">
        <header className="flex flex-wrap items-center gap-x-3 gap-y-1.5">
          <SeverityBadge severity={inc.severity}>{inc.title}</SeverityBadge>
          <span className="text-muted-foreground text-xs">
            {titleCase(inc.severity)} severity
            {showSource ? (
              <>
                {" · "}
                <Link className="hover:text-foreground underline-offset-4 hover:underline" to={`/runs/${inc.run_id}`}>
                  run #{inc.run_id}
                </Link>
                {" · "}
                <TimeAgo value={inc.started_at} />
              </>
            ) : null}
          </span>
        </header>
        <div className="space-y-1">
          <h3 id={`inc-title-${inc.id}`} className="font-mono text-[15px] font-semibold break-all">
            {inc.entity}
          </h3>
          <p className={cn("text-sm text-pretty", (triaged || muted) ? "text-muted-foreground" : "text-foreground/85")}>{inc.explanation}</p>
        </div>
        <dl className="bg-muted/40 grid grid-cols-2 gap-x-4 gap-y-3 rounded-lg border px-3 py-2.5 sm:grid-cols-4">
          <Stat label="Expected" value={exp ? exp.text : "–"} sub={exp && isRange && exp.center !== null ? `median ${fmtShort(exp.center)}` : exp?.basis ?? null} />
          <Stat label="Actual" value={act_ ? act_.text : "–"} sub={act_?.at ? act_.at : act_?.row !== undefined && act_?.row !== null ? `row ${act_.row}` : null} tone="actual" />
          {delta ? <Stat label="Change" value={delta} tone={(inc.delta_pct ?? 0) > 0 ? "up" : "down"} /> : <Stat label="Findings" value={fmtInt(inc.n_findings)} />}
          <Stat label="Scope" value={`${fmtInt(inc.n_rows)} ${inc.n_rows === 1 ? "row" : "rows"}`} sub={inc.detectors.join(", ")} />
        </dl>
        {inc.chart ? <IncidentChartSlot inc={inc} /> : null}
        <footer className="flex flex-wrap items-center justify-between gap-3">
          <div role="group" aria-label="Triage" className="flex flex-wrap items-center gap-2">
            {muted ? (
              <>
                <span className="text-muted-foreground flex items-center gap-1.5 text-sm">
                  <BellOffIcon className="size-4" aria-hidden />
                  Muted until {new Date(inc.muted_until as string).toLocaleString(undefined, { weekday: "short", hour: "2-digit", minute: "2-digit" })}
                </span>
                <Button size="sm" variant="ghost" onClick={unmute} disabled={busy !== null}>
                  {btn("unmute", <RotateCcwIcon />)} Unmute
                </Button>
              </>
            ) : triaged ? (
              <>
                <span className={cn("flex items-center gap-1.5 text-sm font-medium", inc.status === "normal" ? "text-ok" : "text-primary")}>
                  {inc.status === "normal" ? <CheckIcon className="size-4" aria-hidden /> : <FlagIcon className="size-4" aria-hidden />}
                  {inc.status === "normal" ? "Marked as normal" : "Confirmed"}
                </span>
                <Button size="sm" variant="ghost" onClick={() => act("reopen")} disabled={busy !== null}>
                  {btn("reopen", <RotateCcwIcon />)} Reopen
                </Button>
              </>
            ) : (
              <>
                <Button size="sm" variant="outline" onClick={() => act("normal")} disabled={busy !== null} title="Not a problem: record false positives so the detector learns">
                  {btn("normal", <CheckIcon />)} Mark as normal
                </Button>
                <Button
                  size="sm"
                  onClick={() => act("confirm")}
                  disabled={busy !== null}
                  title={inc.column && inc.kind !== "missing" ? "A real problem: record true positives and send the flagged cells to review" : "A real problem: record it as confirmed"}
                >
                  {btn("confirm", <FlagIcon />)} Confirm
                </Button>
                <Button size="sm" variant="ghost" onClick={mute} disabled={busy !== null} title={`Hide ${inc.title.toLowerCase()} on ${inc.entity} for 24 hours`}>
                  {btn("mute", <BellOffIcon />)} Mute 24h
                </Button>
              </>
            )}
          </div>
          {KIND_HELP[inc.kind] ? (
            <HoverCard openDelay={150}>
              <HoverCardTrigger asChild>
                <button type="button" className="text-muted-foreground hover:text-foreground flex items-center gap-1 rounded text-xs outline-none focus-visible:ring-[3px] focus-visible:ring-ring/50">
                  <InfoIcon className="size-3.5" aria-hidden /> How is “expected” set?
                </button>
              </HoverCardTrigger>
              <HoverCardContent className="w-72 text-sm">{KIND_HELP[inc.kind]}</HoverCardContent>
            </HoverCard>
          ) : null}
        </footer>
        {inc.sample?.length ? (
          <Collapsible className="border-t pt-3">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <CollapsibleTrigger className="group text-muted-foreground hover:text-foreground flex items-center gap-1 rounded text-sm font-medium outline-none focus-visible:ring-[3px] focus-visible:ring-ring/50">
                <ChevronDownIcon className="size-4 transition-transform group-data-[state=closed]:-rotate-90" aria-hidden />
                Top findings ({fmtInt(inc.n_findings)})
              </CollapsibleTrigger>
              {onShowColumn && inc.column ? (
                <Button variant="link" size="sm" className="h-auto p-0 text-xs" onClick={() => onShowColumn(inc.column as string)}>
                  <TableIcon /> Show {inc.column} in the table
                </Button>
              ) : null}
            </div>
            <CollapsibleContent>
              <ul className="mt-2 divide-y rounded-lg border">
                {inc.sample.map((f) => (
                  <li key={f.id} className="space-y-0.5 px-3 py-2">
                    <div className="flex flex-wrap items-baseline gap-x-3 font-mono text-xs">
                      <span className="text-muted-foreground">row {String(f.row_index)}</span>
                      {f.value !== null && f.value !== undefined ? <span className="font-semibold">{fmtValue(f.value)}</span> : null}
                      <span className="text-muted-foreground">{f.detector}</span>
                    </div>
                    <p className="text-muted-foreground text-xs break-words">{f.reason}</p>
                  </li>
                ))}
              </ul>
            </CollapsibleContent>
          </Collapsible>
        ) : null}
      </div>
    </article>
  );
}
