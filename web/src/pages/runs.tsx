// Runs: every pipeline run and analysis, filterable, paged on the server.

import type { ColumnDef } from "@tanstack/react-table";
import { FileUpIcon, ListIcon, WorkflowIcon } from "lucide-react";
import { Link, useNavigate } from "react-router";

import { EmptyState, ErrorState, PageHeader, Section, StatusBadge, TimeAgo, useTitle } from "@/components/common";
import { DataTable, Pager } from "@/components/data-table";
import { FilterSelect, SearchInput, useUrlState } from "@/components/filters";
import { Button } from "@/components/ui/button";
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group";
import { fmtInt, fmtMs, fmtPct, isAnalysis, runLabel } from "@/lib/format";
import { useRuns, useSummary } from "@/lib/queries";
import type { RunRow } from "@/lib/types";
import { cn } from "@/lib/utils";

const columns: ColumnDef<RunRow, unknown>[] = [
  {
    id: "id",
    header: "Run",
    cell: ({ row }) => (
      <Link to={`/runs/${row.original.id}`} className="font-mono text-sm font-medium hover:underline">
        #{row.original.id}
      </Link>
    ),
  },
  {
    id: "source",
    header: "Source",
    meta: { className: "max-w-[260px]" },
    cell: ({ row: { original: r } }) => (
      <div className="flex min-w-0 items-center gap-2" title={r.error || runLabel(r.pipeline)}>
        {isAnalysis(r.pipeline) ? <FileUpIcon className="text-muted-foreground size-3.5 shrink-0" aria-label="analysis" /> : <WorkflowIcon className="text-muted-foreground size-3.5 shrink-0" aria-label="pipeline" />}
        <span className="truncate">{runLabel(r.pipeline)}</span>
      </div>
    ),
  },
  { id: "status", header: "Status", cell: ({ row }) => <StatusBadge status={row.original.status} /> },
  { id: "rows", header: "Rows", meta: { align: "right", hideBelow: "md" }, cell: ({ row }) => fmtInt(row.original.rows) },
  {
    id: "anomalous",
    header: "Anomalous",
    meta: { align: "right" },
    cell: ({ row: { original: r } }) => (
      <span>
        {fmtInt(r.n_anomalies)} <span className="text-muted-foreground hidden text-xs sm:inline">({fmtPct(r.anomaly_rate)})</span>
      </span>
    ),
  },
  {
    id: "quality",
    header: "Quality",
    meta: { align: "right", hideBelow: "sm" },
    cell: ({ row: { original: r } }) => <span className={cn(r.quality_score !== null && r.quality_score < 0.9 && "text-sev-high font-medium")}>{r.quality_score === null ? "–" : fmtPct(r.quality_score)}</span>,
  },
  { id: "fixed", header: "Fixed", meta: { align: "right", hideBelow: "lg" }, cell: ({ row }) => fmtInt(row.original.cells_changed) },
  { id: "flagged", header: "Flagged", meta: { align: "right", hideBelow: "lg" }, cell: ({ row }) => fmtInt(row.original.flagged_for_review) },
  { id: "alerts", header: "Alerts", meta: { align: "right", hideBelow: "lg" }, cell: ({ row }) => fmtInt(row.original.alerts_sent) },
  { id: "duration", header: "Duration", meta: { align: "right", hideBelow: "lg" }, cell: ({ row }) => <span className="text-muted-foreground">{fmtMs(row.original.duration_ms)}</span> },
  { id: "started", header: "Started", meta: { hideBelow: "md" }, cell: ({ row }) => <TimeAgo value={row.original.started_at} className="text-muted-foreground text-sm" /> },
];

export default function RunsPage() {
  useTitle("Runs");
  const navigate = useNavigate();
  const [s, set] = useUrlState({ kind: "", status: "", pipeline: "", q: "", offset: 0, limit: 25 });
  const summary = useSummary();
  const q = useRuns({ limit: s.limit, offset: s.offset, kind: s.kind, status: s.status, pipeline: s.pipeline, q: s.q });
  const filtered = Boolean(s.kind || s.status || s.pipeline || s.q);

  return (
    <div className="animate-fade-in space-y-6">
      <PageHeader title="Runs" description="Every pipeline run and every analysis, newest first." />
      <Section flush>
        <div role="toolbar" aria-label="Run filters" className="flex flex-wrap items-center gap-2 border-b p-3">
          <ToggleGroup type="single" variant="outline" size="sm" value={s.kind || "all"} onValueChange={(v) => v && set({ kind: v === "all" ? "" : v, offset: 0 })} aria-label="Run type">
            <ToggleGroupItem value="all" className="px-3 text-xs">
              All
            </ToggleGroupItem>
            <ToggleGroupItem value="pipeline" className="px-3 text-xs">
              Pipelines
            </ToggleGroupItem>
            <ToggleGroupItem value="analysis" className="px-3 text-xs">
              Analyses
            </ToggleGroupItem>
          </ToggleGroup>
          <FilterSelect
            label="Source"
            allLabel="All sources"
            value={s.pipeline}
            onChange={(v) => set({ pipeline: v, offset: 0 })}
            options={(summary.data?.pipelines ?? []).map((p) => ({ value: p, label: isAnalysis(p) ? `${runLabel(p)} (analysis)` : p }))}
          />
          <FilterSelect
            label="Status"
            allLabel="Any status"
            value={s.status}
            onChange={(v) => set({ status: v, offset: 0 })}
            options={["success", "failed", "empty", "running"].map((v) => ({ value: v, label: v }))}
            className="min-w-[120px]"
          />
          <SearchInput value={s.q} onChange={(v) => set({ q: v, offset: 0 })} placeholder="Search source, run id or error" label="Search runs" className="sm:ml-auto" />
        </div>
        {q.error ? (
          <ErrorState error={q.error} retry={() => q.refetch()} />
        ) : (
          <>
            <DataTable
              caption="Runs"
              columns={columns}
              data={q.data?.items ?? []}
              loading={q.isFetching}
              getRowId={(r) => String(r.id)}
              onRowClick={(r) => navigate(`/runs/${r.id}`)}
              rowLabel={(r) => `Run ${r.id}, ${runLabel(r.pipeline)}, ${r.status}`}
              empty={
                filtered ? (
                  <EmptyState icon={ListIcon} title="No runs match these filters">
                    <Button variant="outline" size="sm" onClick={() => set({ kind: "", status: "", pipeline: "", q: "", offset: 0 })}>
                      Clear filters
                    </Button>
                  </EmptyState>
                ) : (
                  <EmptyState icon={ListIcon} title="No runs yet" description="Analyses and pipeline runs are recorded here.">
                    <Button asChild>
                      <Link to="/analyze">Analyze a file</Link>
                    </Button>
                    <Button asChild variant="outline">
                      <Link to="/pipelines">Run a pipeline</Link>
                    </Button>
                  </EmptyState>
                )
              }
            />
            <Pager offset={s.offset} limit={s.limit} total={q.data?.total ?? 0} noun="runs" onChange={(offset, limit) => set({ offset, limit })} />
          </>
        )}
      </Section>
    </div>
  );
}
