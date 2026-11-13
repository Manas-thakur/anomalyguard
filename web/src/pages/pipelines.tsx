// Pipelines: YAML files from the configured folders, run now, create from a template.

import type { ColumnDef } from "@tanstack/react-table";
import { FolderOpenIcon, PlayIcon, PlusIcon, WorkflowIcon } from "lucide-react";
import { useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router";

import { EmptyState, ErrorState, PageHeader, Section, StatusBadge, TimeAgo, useTitle } from "@/components/common";
import { DataTable } from "@/components/data-table";
import { NewPipelineSheet } from "@/components/pipelines/new-pipeline";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Spinner } from "@/components/ui/spinner";
import { runPipeline } from "@/lib/actions";
import { fmtInt, fmtSchedule } from "@/lib/format";
import { usePipelines } from "@/lib/queries";
import type { Pipeline } from "@/lib/types";

function RunButton({ p }: { p: Pipeline }) {
  const navigate = useNavigate();
  const [busy, setBusy] = useState(false);
  return (
    <Button
      size="sm"
      variant="outline"
      disabled={!p.valid || busy}
      onClick={async () => {
        setBusy(true);
        await runPipeline(p, navigate);
        setBusy(false);
      }}
      aria-label={`Run ${p.name || p.file} now`}
    >
      {busy ? <Spinner /> : <PlayIcon />} {busy ? "Running" : "Run now"}
    </Button>
  );
}

const columns: ColumnDef<Pipeline, unknown>[] = [
  {
    id: "name",
    header: "Pipeline",
    meta: { className: "max-w-[340px]" },
    cell: ({ row: { original: p } }) => (
      <div className="min-w-0 space-y-0.5">
        <Link to={`/pipelines/${p.id}`} className="font-medium hover:underline">
          {p.name || p.file}
        </Link>
        {p.description ? <p className="text-muted-foreground truncate text-xs">{p.description}</p> : null}
        {!p.valid ? <p className="text-sev-high line-clamp-2 text-xs">{p.error}</p> : null}
      </div>
    ),
  },
  {
    id: "file",
    header: "File",
    meta: { hideBelow: "lg" },
    cell: ({ row: { original: p } }) => (
      <div className="font-mono text-xs">
        {p.file}
        <div className="text-muted-foreground">{p.dir}</div>
      </div>
    ),
  },
  {
    id: "detectors",
    header: "Detectors",
    meta: { hideBelow: "md" },
    cell: ({ row }) => (
      <div className="flex max-w-[260px] flex-wrap gap-1">
        {(row.original.detectors ?? []).map((d, i) => (
          <Badge key={`${d}-${i}`} variant="secondary" className="rounded-md font-mono text-[11px]">
            {d}
          </Badge>
        ))}
      </div>
    ),
  },
  { id: "schedule", header: "Schedule", meta: { hideBelow: "sm" }, cell: ({ row }) => (row.original.valid ? <span className="text-sm whitespace-nowrap">{fmtSchedule(row.original.interval_seconds)}</span> : <StatusBadge status="invalid" />) },
  {
    id: "last",
    header: "Last run",
    cell: ({ row: { original: p } }) =>
      p.last_run ? (
        <span className="flex items-center gap-2 whitespace-nowrap">
          <StatusBadge status={p.last_run.status} />
          <Link to={`/runs/${p.last_run.id}`} className="text-muted-foreground text-sm hover:underline">
            <TimeAgo value={p.last_run.started_at} />
          </Link>
        </span>
      ) : (
        <span className="text-muted-foreground text-sm">never</span>
      ),
  },
  { id: "runs", header: "Runs", meta: { align: "right", hideBelow: "md" }, cell: ({ row }) => fmtInt(row.original.runs || 0) },
  { id: "run", header: () => <span className="sr-only">Run</span>, meta: { align: "right" }, cell: ({ row }) => <RunButton p={row.original} /> },
];

export default function PipelinesPage() {
  useTitle("Pipelines");
  const navigate = useNavigate();
  const [params, setParams] = useSearchParams();
  const [open, setOpen] = useState(params.get("new") === "1");
  const q = usePipelines();
  const setSheet = (o: boolean) => {
    setOpen(o);
    if (!o && params.get("new")) setParams({}, { replace: true });
  };
  if (params.get("new") === "1" && !open) setOpen(true);

  const where = q.data ? (
    <p className="text-muted-foreground flex flex-wrap items-center gap-1 px-4 py-3 text-xs">
      <FolderOpenIcon className="size-3.5" aria-hidden />
      Scanning{" "}
      {q.data.dirs.map((d, i) => (
        <span key={d.path}>
          {i ? ", " : ""}
          <code className="font-mono">{d.path}</code>
          {d.exists ? "" : " (missing)"}
        </span>
      ))}
      . New pipelines are written to <code className="font-mono">{q.data.write_dir}</code>.
    </p>
  ) : null;

  return (
    <div className="animate-fade-in space-y-6">
      <PageHeader
        title="Pipelines"
        description="Declarative YAML pipelines: source, schema, detectors, remediation, alerts and sink."
        actions={
          <Button onClick={() => setSheet(true)}>
            <PlusIcon /> New pipeline
          </Button>
        }
      />
      <Section flush>
        {q.error ? (
          <ErrorState error={q.error} retry={() => q.refetch()} />
        ) : (
          <DataTable
            caption="Pipelines"
            columns={columns}
            data={q.data?.pipelines ?? []}
            loading={q.isLoading}
            getRowId={(p) => p.id}
            onRowClick={(p) => navigate(`/pipelines/${p.id}`)}
            rowLabel={(p) => `${p.name || p.file}${p.valid ? "" : ", invalid"}`}
            empty={
              <EmptyState icon={WorkflowIcon} title="No pipelines found" description="Create one from a template, or point ANOMALYGUARD_PIPELINE_DIRS (or serve --pipeline-dir) at a folder of pipeline YAML files.">
                <Button onClick={() => setSheet(true)}>
                  <PlusIcon /> New pipeline
                </Button>
              </EmptyState>
            }
          />
        )}
        {where ? <div className="border-t">{where}</div> : null}
      </Section>
      <NewPipelineSheet open={open} onOpenChange={setSheet} writeDir={q.data?.write_dir} />
    </div>
  );
}
