// Stored findings of a run: server-side sorting, filters and paging, with
// per-finding feedback (false positive / confirm).

import type { ColumnDef, SortingState } from "@tanstack/react-table";
import { CheckIcon, SearchXIcon, ThumbsDownIcon } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";

import { EmptyState, ErrorState, SeverityBadge } from "@/components/common";
import { DataTable, Pager } from "@/components/data-table";
import { FilterSelect } from "@/components/filters";
import { Button } from "@/components/ui/button";
import { api } from "@/lib/api";
import { fmtNum, fmtValue } from "@/lib/format";
import { useFindings } from "@/lib/queries";
import type { Breakdown, Finding } from "@/lib/types";

export interface FindingFilters {
  column: string;
  detector: string;
  severity: string;
}

function Feedback({ f }: { f: Finding }) {
  const [state, setState] = useState<"idle" | "busy" | "false_positive" | "true_positive">("idle");
  const send = async (label: "false_positive" | "true_positive") => {
    setState("busy");
    try {
      await api.post("/api/feedback", { anomaly_id: f.id, label });
      setState(label);
    } catch (err) {
      setState("idle");
      toast.error((err as Error).message);
    }
  };
  if (state === "false_positive" || state === "true_positive")
    return <span className="text-muted-foreground text-xs font-medium">{state === "false_positive" ? "Marked false positive" : "Confirmed"}</span>;
  return (
    <div className="flex gap-1" data-no-row-click>
      <Button variant="outline" size="sm" className="h-7 px-2 text-xs" disabled={state === "busy"} onClick={() => send("false_positive")} aria-label={`Mark finding ${f.id} as a false positive`}>
        <ThumbsDownIcon className="size-3.5" /> False positive
      </Button>
      <Button variant="ghost" size="sm" className="h-7 px-2 text-xs" disabled={state === "busy"} onClick={() => send("true_positive")} aria-label={`Confirm finding ${f.id}`}>
        <CheckIcon className="size-3.5" /> Confirm
      </Button>
    </div>
  );
}

const columns: ColumnDef<Finding, unknown>[] = [
  {
    id: "score",
    accessorFn: (a) => a.score,
    header: "Score",
    enableSorting: true,
    cell: ({ row: { original: a } }) => (
      <div className="flex items-center gap-2">
        <SeverityBadge severity={a.severity} className="px-1.5" />
        <span className="font-mono text-xs tabular">{fmtNum(a.score, 3)}</span>
      </div>
    ),
  },
  { id: "row", accessorFn: (a) => a.row_index, header: "Row", enableSorting: true, cell: ({ row }) => <span className="font-mono text-xs">{String(row.original.row_index)}</span> },
  { id: "column", accessorFn: (a) => a.column, header: "Column", enableSorting: true, cell: ({ row }) => <span className="font-mono text-xs">{row.original.column || "(row)"}</span> },
  { id: "detector", accessorFn: (a) => a.detector, header: "Detector", enableSorting: true, meta: { hideBelow: "md" }, cell: ({ row }) => <span className="text-muted-foreground font-mono text-xs whitespace-nowrap">{row.original.detector}</span> },
  { id: "value", header: "Value", enableSorting: false, cell: ({ row }) => <span className="font-mono text-xs font-semibold">{fmtValue(row.original.value)}</span> },
  {
    id: "reason",
    header: "Reason",
    enableSorting: false,
    meta: { hideBelow: "lg", className: "max-w-[420px] min-w-[240px] whitespace-normal" },
    cell: ({ row }) => (
      <span className="text-muted-foreground line-clamp-2 text-xs" title={row.original.reason}>
        {row.original.reason}
      </span>
    ),
  },
  { id: "feedback", header: "Feedback", enableSorting: false, cell: ({ row }) => <Feedback f={row.original} /> },
];

export function FindingsTable({ runId, breakdown, filters, onFilters }: { runId: number; breakdown: Breakdown; filters: FindingFilters; onFilters: (f: Partial<FindingFilters>) => void }) {
  const [sorting, setSorting] = useState<SortingState>([{ id: "score", desc: true }]);
  const [page, setPage] = useState({ offset: 0, limit: 25 });
  const sort = sorting[0] ?? { id: "score", desc: true };
  const q = useFindings(runId, { ...page, sort: sort.id, order: sort.desc ? "desc" : "asc", column: filters.column, detector: filters.detector, severity: filters.severity });
  const setF = (patch: Partial<FindingFilters>) => {
    setPage((p) => ({ ...p, offset: 0 }));
    onFilters(patch);
  };

  return (
    <div>
      <div role="toolbar" aria-label="Finding filters" className="flex flex-wrap gap-2 border-b p-3">
        <FilterSelect label="Column" allLabel="All columns" value={filters.column} onChange={(v) => setF({ column: v })} options={Object.keys(breakdown.by_column).map((c) => ({ value: c, label: c }))} />
        <FilterSelect label="Detector" allLabel="All detectors" value={filters.detector} onChange={(v) => setF({ detector: v })} options={Object.keys(breakdown.by_detector).map((c) => ({ value: c, label: c }))} />
        <FilterSelect label="Severity" allLabel="Any severity" value={filters.severity} onChange={(v) => setF({ severity: v })} options={["high", "medium", "low"].map((v) => ({ value: v, label: v }))} className="min-w-[120px]" />
      </div>
      {q.error ? (
        <ErrorState error={q.error} retry={() => q.refetch()} />
      ) : (
        <>
          <DataTable
            caption="Findings"
            columns={columns}
            data={q.data?.items ?? []}
            loading={q.isFetching}
            getRowId={(f) => String(f.id)}
            sorting={sorting}
            onSortingChange={(updater) => {
              setSorting((old) => {
                const next = typeof updater === "function" ? updater(old) : updater;
                // first click on a non-score column sorts ascending
                if (next[0] && next[0].id !== old[0]?.id && next[0].id !== "score") return [{ id: next[0].id, desc: false }];
                return next;
              });
              setPage((p) => ({ ...p, offset: 0 }));
            }}
            empty={<EmptyState icon={SearchXIcon} title="No findings" description={filters.column || filters.detector || filters.severity ? "Nothing matches these filters." : "This run stored no findings."} />}
          />
          <Pager offset={page.offset} limit={page.limit} total={q.data?.total ?? 0} noun="findings" onChange={(offset, limit) => setPage({ offset, limit })} />
        </>
      )}
    </div>
  );
}
