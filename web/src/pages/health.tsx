// Health: KPI strip, one row per monitored source (status, quality sparkline,
// trend, open incidents, last run), a feed of recent incidents and trends.

import type { ColumnDef } from "@tanstack/react-table";
import { ActivityIcon, ArrowDownRightIcon, ArrowUpRightIcon, DatabaseIcon, FileUpIcon, GaugeIcon, MinusIcon, ShieldAlertIcon, WorkflowIcon } from "lucide-react";
import { Link, useNavigate, useSearchParams } from "react-router";

import { Sparkline, TrendChart } from "@/components/charts/small-charts";
import { EmptyState, ErrorState, KpiGrid, KpiSkeleton, LoadingRows, PageHeader, Section, SeverityDot, TimeAgo, useTitle } from "@/components/common";
import { DataTable } from "@/components/data-table";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { fmtAgo, fmtInt, fmtPct, fmtPoints } from "@/lib/format";
import { useHealth, useRecentIncidents, useSeries } from "@/lib/queries";
import type { HealthSource } from "@/lib/types";
import { cn } from "@/lib/utils";

const STATUS: Record<HealthSource["status"], { label: string; why: string; dot: string }> = {
  failing: { label: "Failing", why: "The last run failed", dot: "bg-sev-high ring-sev-high/25" },
  degraded: { label: "Degraded", why: "A high-severity incident, or quality below 90%", dot: "bg-sev-high ring-sev-high/25" },
  warning: { label: "Warning", why: "Open incidents", dot: "bg-sev-medium ring-sev-medium/25" },
  healthy: { label: "Healthy", why: "No open incidents", dot: "bg-ok ring-ok/25" },
};

function StatusDot({ status }: { status: HealthSource["status"] }) {
  const s = STATUS[status];
  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <span tabIndex={0} className={cn("inline-block size-2.5 shrink-0 rounded-full ring-[3px] outline-none focus-visible:ring-ring/50", s.dot)}>
          <span className="sr-only">{s.label}: {s.why}</span>
        </span>
      </TooltipTrigger>
      <TooltipContent>
        <span className="font-medium">{s.label}</span> · {s.why}
      </TooltipContent>
    </Tooltip>
  );
}

function Trend({ trend }: { trend: number | null }) {
  if (trend === null || trend === undefined) return <span className="text-muted-foreground">–</span>;
  const pts = trend * 100;
  const flat = Math.abs(pts) < 0.05;
  const up = pts > 0;
  const Icon = flat ? MinusIcon : up ? ArrowUpRightIcon : ArrowDownRightIcon;
  return (
    <span className={cn("inline-flex items-center gap-0.5 font-medium tabular", flat ? "text-muted-foreground" : up ? "text-ok" : "text-sev-high")} title={flat ? "No change since the previous run" : `Quality ${up ? "up" : "down"} ${Math.abs(pts).toFixed(1)} points since the previous run`}>
      <Icon className="size-3.5" aria-hidden />
      {fmtPoints(trend)}
    </span>
  );
}

const columns: ColumnDef<HealthSource, unknown>[] = [
  {
    id: "source",
    header: "Source",
    cell: ({ row: { original: s } }) => (
      <div className="flex min-w-0 items-center gap-3">
        <StatusDot status={s.status} />
        <div className="min-w-0">
          <Link to={`/runs/${s.latest_success ?? s.last_run.id}`} className="block truncate font-medium hover:underline">
            {s.name}
          </Link>
          <div className="text-muted-foreground flex items-center gap-1 text-xs">
            {s.kind === "analysis" ? <FileUpIcon className="size-3" aria-hidden /> : <WorkflowIcon className="size-3" aria-hidden />}
            {s.kind} · {fmtInt(s.runs)} {s.runs === 1 ? "run" : "runs"}
          </div>
        </div>
      </div>
    ),
  },
  {
    id: "quality",
    header: "Quality",
    cell: ({ row: { original: s } }) => (
      <div className="flex items-center gap-2">
        <Sparkline points={s.quality_series} label={`Quality over the last ${s.quality_series.length} runs`} hideOnMobile />
        <span className="font-medium tabular">{s.quality === null ? "–" : fmtPct(s.quality)}</span>
      </div>
    ),
  },
  { id: "trend", header: "Trend", meta: { align: "right", hideBelow: "md" }, cell: ({ row }) => <Trend trend={row.original.trend} /> },
  {
    id: "open",
    header: "Open",
    meta: { align: "right" },
    cell: ({ row: { original: s } }) =>
      s.open_incidents ? (
        <Badge variant="outline" className={cn("rounded-md tabular", s.high_incidents ? "bg-sev-high-soft text-sev-high border-sev-high/25" : "bg-sev-medium-soft text-sev-medium border-sev-medium/25")}>
          {fmtInt(s.open_incidents)}
          <span className="sr-only"> open incidents{s.high_incidents ? `, ${s.high_incidents} high` : ""}</span>
        </Badge>
      ) : (
        <span className="text-muted-foreground">0</span>
      ),
  },
  {
    id: "last",
    header: "Last run",
    meta: { hideBelow: "sm" },
    cell: ({ row: { original: s } }) => (
      <span className="text-muted-foreground text-sm">
        {s.last_run.status !== "success" ? <span className="text-sev-high font-medium">{s.last_run.status} · </span> : null}
        <TimeAgo value={s.last_run.started_at} />
      </span>
    ),
  },
];

function IncidentFeed() {
  const q = useRecentIncidents(12);
  if (q.error) return <ErrorState error={q.error} retry={() => q.refetch()} />;
  if (!q.data) return <LoadingRows rows={6} />;
  if (!q.data.length) return <EmptyState icon={ShieldAlertIcon} title="No incidents" description="Incidents from your latest runs appear here." />;
  return (
    <ul className="divide-y">
      {q.data.map((i) => {
        const source = i.column ? i.entity.slice(0, -(i.column.length + 1)) : i.entity;
        return (
          <li key={`${i.run_id}-${i.id}`}>
            <Link
              to={`/runs/${i.run_id}?incident=${i.id}`}
              className={cn("hover:bg-muted/60 focus-visible:bg-muted/60 flex gap-3 px-4 py-3 outline-none", i.status !== "open" && "opacity-70")}
            >
              <SeverityDot severity={i.severity} className="mt-1.5" />
              <span className="min-w-0 flex-1">
                <span className="flex items-center gap-2 text-sm font-medium">
                  <span className="truncate">{i.title}</span>
                  {i.status !== "open" ? (
                    <Badge variant="secondary" className="h-5 rounded-md px-1.5 text-[11px]">
                      {i.status === "normal" ? "normal" : "confirmed"}
                    </Badge>
                  ) : null}
                </span>
                <span className="text-muted-foreground block truncate text-xs">{[source, i.column, fmtAgo(i.started_at)].filter(Boolean).join(" · ")}</span>
              </span>
              <span className="sr-only">{i.severity} severity</span>
            </Link>
          </li>
        );
      })}
    </ul>
  );
}

function Trends() {
  const [params, setParams] = useSearchParams();
  const navigate = useNavigate();
  const metric = params.get("metric") === "anomaly_rate" ? "anomaly_rate" : "quality_score";
  const q = useSeries();
  return (
    <Section
      title="Trends"
      description="Latest runs of every source"
      actions={
        <ToggleGroup
          type="single"
          size="sm"
          variant="outline"
          value={metric}
          onValueChange={(v) => {
            if (!v) return;
            const next = new URLSearchParams(params);
            if (v === "quality_score") next.delete("metric");
            else next.set("metric", v);
            setParams(next, { replace: true });
          }}
          aria-label="Metric"
        >
          <ToggleGroupItem value="quality_score" className="px-2.5 text-xs">
            Quality
          </ToggleGroupItem>
          <ToggleGroupItem value="anomaly_rate" className="px-2.5 text-xs">
            Anomaly rate
          </ToggleGroupItem>
        </ToggleGroup>
      }
    >
      {q.error ? <ErrorState error={q.error} retry={() => q.refetch()} /> : !q.data ? <LoadingRows rows={5} /> : <TrendChart series={q.data.series} metric={metric} onOpenRun={(id) => navigate(`/runs/${id}`)} />}
    </Section>
  );
}

export function HealthPage() {
  useTitle("Health");
  const navigate = useNavigate();
  const q = useHealth();
  const k = q.data?.kpis;

  return (
    <div className="animate-fade-in space-y-6">
      <PageHeader
        title="Health"
        description="Every monitored pipeline and analysed file: is it healthy, what changed, and what needs a decision."
        actions={
          <>
            <Button variant="outline" asChild>
              <Link to="/pipelines">
                <WorkflowIcon /> Run a pipeline
              </Link>
            </Button>
            <Button asChild>
              <Link to="/analyze">
                <FileUpIcon /> Analyze a file
              </Link>
            </Button>
          </>
        }
      />
      {q.error ? (
        <Section>
          <ErrorState error={q.error} retry={() => q.refetch()} />
        </Section>
      ) : !k ? (
        <KpiSkeleton />
      ) : (
        <KpiGrid
          items={[
            { label: "Open incidents", icon: ShieldAlertIcon, value: fmtInt(k.open_incidents), sub: k.high_incidents ? `${fmtInt(k.high_incidents)} high severity` : "none high", tone: k.high_incidents ? "alert" : "default" },
            { label: "Sources monitored", icon: ActivityIcon, value: fmtInt(k.monitored), sub: k.unhealthy ? `${fmtInt(k.unhealthy)} need attention` : `${fmtInt(k.runs)} runs` },
            { label: "Avg quality", icon: GaugeIcon, value: k.avg_quality === null ? "–" : fmtPct(k.avg_quality), sub: "latest run of each source" },
            { label: "Rows scanned", icon: DatabaseIcon, value: fmtInt(k.rows_scanned), sub: "all successful runs" },
          ]}
        />
      )}
      <div className="grid gap-6 xl:grid-cols-[minmax(0,1fr)_380px]">
        <div className="min-w-0 space-y-6">
          <Section title="Sources" description="Latest successful run of each source. Select a row to open it." flush>
            {q.data && !q.data.sources.length ? (
              <EmptyState icon={ActivityIcon} title="Nothing monitored yet" description="Analyze a file or run a pipeline; each one shows up here with its quality trend and open incidents.">
                <Button asChild>
                  <Link to="/analyze">Analyze a file</Link>
                </Button>
                <Button asChild variant="outline">
                  <Link to="/pipelines">See pipelines</Link>
                </Button>
              </EmptyState>
            ) : (
              <DataTable
                caption="Monitored sources"
                columns={columns}
                data={q.data?.sources ?? []}
                loading={!q.data && !q.error}
                getRowId={(s) => s.pipeline}
                onRowClick={(s) => navigate(`/runs/${s.latest_success ?? s.last_run.id}`)}
                rowLabel={(s) => `${s.name}: ${STATUS[s.status].label}`}
              />
            )}
          </Section>
          <Trends />
        </div>
        <Section
          title="Recent incidents"
          actions={
            <Button variant="link" size="sm" asChild className="h-auto p-0 text-xs">
              <Link to="/runs">All runs</Link>
            </Button>
          }
          flush
          className="self-start"
        >
          <IncidentFeed />
        </Section>
      </div>
    </div>
  );
}
