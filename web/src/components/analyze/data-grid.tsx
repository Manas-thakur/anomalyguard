// The analysed data with every anomalous cell tinted by severity. A flagged
// cell opens a popover with each finding's reason and feedback buttons.

import type { ColumnDef } from "@tanstack/react-table";
import { CheckIcon, SearchXIcon, ThumbsDownIcon } from "lucide-react";
import { useMemo, useState } from "react";
import { toast } from "sonner";

import { BarList, EmptyState, ErrorState, Section, SeverityBadge, SeverityDot } from "@/components/common";
import { DataTable, Pager } from "@/components/data-table";
import { FilterSelect } from "@/components/filters";
import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { Switch } from "@/components/ui/switch";
import { api } from "@/lib/api";
import { fmtInt, fmtNum, fmtValue } from "@/lib/format";
import { useAnalysisRows } from "@/lib/queries";
import type { AnalysisRows, Breakdown, CellFinding, Severity } from "@/lib/types";
import { cn } from "@/lib/utils";

type Row = AnalysisRows["rows"][number];

export interface GridState {
  offset: number;
  limit: number;
  column: string;
  detector: string;
  severity: string;
  all: string;
  sort: string;
}

const TINT: Record<Severity, string> = {
  high: "bg-sev-high-soft text-sev-high ring-sev-high/30",
  medium: "bg-sev-medium-soft text-sev-medium ring-sev-medium/30",
  low: "bg-sev-low-soft text-foreground ring-sev-low/30",
};

function FindingFeedback({ f }: { f: CellFinding }) {
  const [done, setDone] = useState<string | null>(null);
  const send = async (label: "false_positive" | "true_positive") => {
    try {
      await api.post("/api/feedback", { anomaly_id: f.id, label });
      setDone(label);
      toast.success(label === "false_positive" ? `Recorded a false positive for ${f.detector}` : `Confirmed the ${f.detector} finding`, {
        description: label === "false_positive" ? "Tune thresholds in Settings to apply it." : undefined,
      });
    } catch (err) {
      toast.error((err as Error).message);
    }
  };
  if (done) return <p className="text-muted-foreground text-xs font-medium">{done === "false_positive" ? "Marked as false positive" : "Confirmed"}</p>;
  return (
    <div className="flex gap-1.5">
      <Button size="sm" variant="outline" className="h-7 text-xs" onClick={() => send("false_positive")}>
        <ThumbsDownIcon className="size-3.5" /> False positive
      </Button>
      <Button size="sm" variant="ghost" className="h-7 text-xs" onClick={() => send("true_positive")}>
        <CheckIcon className="size-3.5" /> Confirm
      </Button>
    </div>
  );
}

function CellPopover({ column, value, findings, label }: { column: string; value: unknown; findings: CellFinding[]; label?: string }) {
  const worst = findings.reduce((a, b) => (b.score > a.score ? b : a));
  return (
    <Popover>
      <PopoverTrigger asChild>
        <button
          type="button"
          className={cn("-mx-1.5 -my-0.5 rounded px-1.5 py-0.5 text-left font-mono text-xs font-semibold ring-1 outline-none focus-visible:ring-[3px] focus-visible:ring-ring/60", label ? "bg-muted text-foreground ring-border font-sans font-medium" : TINT[worst.severity])}
          aria-label={label ? `${findings.length} row-level findings` : `${column} = ${fmtValue(value)}, ${findings.length} finding${findings.length > 1 ? "s" : ""}, ${worst.severity} severity`}
          title={findings.map((f) => `${f.detector}: ${f.reason}`).join("\n")}
        >
          {label ?? fmtValue(value)}
        </button>
      </PopoverTrigger>
      <PopoverContent className="w-[min(92vw,380px)] p-0" align="start">
        <div className="border-b px-3 py-2">
          <p className="text-muted-foreground text-xs">{column}</p>
          {value !== undefined && !label ? <p className="font-mono text-sm font-semibold">{fmtValue(value)}</p> : null}
        </div>
        <ul className="max-h-80 divide-y overflow-y-auto">
          {findings.map((f) => (
            <li key={f.id} className="space-y-2 px-3 py-2.5">
              <div className="flex items-center justify-between gap-2">
                <span className="truncate font-mono text-xs">{f.detector}</span>
                <span className="flex items-center gap-2">
                  <SeverityBadge severity={f.severity} />
                  <span className="text-muted-foreground font-mono text-xs tabular">score {fmtNum(f.score, 3)}</span>
                </span>
              </div>
              <p className="text-sm">{f.reason}</p>
              <FindingFeedback f={f} />
            </li>
          ))}
        </ul>
      </PopoverContent>
    </Popover>
  );
}

export function DataGrid({ analysisId, breakdown, state, onState }: { analysisId: string; breakdown: Breakdown; state: GridState; onState: (p: Partial<GridState>) => void }) {
  const q = useAnalysisRows(analysisId, {
    offset: state.offset,
    limit: state.limit,
    only_anomalous: state.all !== "1",
    column: state.column,
    detector: state.detector,
    severity: state.severity,
    sort: state.sort,
  });
  const cols = useMemo(() => q.data?.columns ?? [], [q.data]);
  const columns = useMemo<ColumnDef<Row, unknown>[]>(
    () => [
      { id: "__row", header: "row", meta: { className: "text-muted-foreground font-mono text-xs" }, cell: ({ row }) => String(row.original.index) },
      ...cols.map(
        (c): ColumnDef<Row, unknown> => ({
          id: c,
          header: () => <span className={cn("font-mono", state.column === c && "text-primary font-semibold")}>{c}</span>,
          meta: { className: "whitespace-nowrap" },
          cell: ({ row }) => {
            const v = row.original.values[c];
            const fs = row.original.cells[c];
            if (fs?.length) return <CellPopover column={c} value={v} findings={fs} />;
            return <span className={cn("font-mono text-xs", v === null && "text-muted-foreground italic")}>{fmtValue(v)}</span>;
          },
        }),
      ),
      {
        id: "__rowflags",
        header: "row flags",
        cell: ({ row }) => (row.original.row_findings.length ? <CellPopover column="(whole row)" value={undefined} findings={row.original.row_findings} label={`${row.original.row_findings.length} row-level`} /> : null),
      },
    ],
    [cols, state.column],
  );
  const toggle = (key: "column" | "detector", v: string) => onState({ [key]: state[key] === v ? "" : v, offset: 0 });

  return (
    <div className="space-y-6">
      <div className="grid gap-6 lg:grid-cols-2">
        <Section title="Findings by column" description="Select a bar to filter the table">
          <BarList items={Object.entries(breakdown.by_column).sort((a, b) => b[1] - a[1]).map(([k, v]) => ({ label: k, value: v, active: state.column === k, onClick: () => toggle("column", k) }))} format={fmtInt} />
        </Section>
        <Section title="Findings by detector" description="Grouped detectors are fitted per group">
          <BarList items={Object.entries(breakdown.by_detector).sort((a, b) => b[1] - a[1]).map(([k, v]) => ({ label: k, value: v, active: state.detector === k, onClick: () => toggle("detector", k) }))} format={fmtInt} />
        </Section>
      </div>
      <Section
        title="Data"
        description="Flagged cells are tinted by severity. Hover for the reason; select one for details and feedback."
        actions={
          <span className="text-muted-foreground hidden items-center gap-3 text-xs sm:flex">
            {(["high", "medium", "low"] as Severity[]).map((s) => (
              <span key={s} className="flex items-center gap-1.5">
                <SeverityDot severity={s} /> {s}
              </span>
            ))}
          </span>
        }
        flush
      >
        <div role="toolbar" aria-label="Data filters" className="flex flex-wrap items-center gap-2 border-b p-3">
          <FilterSelect label="Column" allLabel="All columns" value={state.column} onChange={(v) => onState({ column: v, offset: 0 })} options={Object.keys(breakdown.by_column).map((c) => ({ value: c, label: `${c} (${breakdown.by_column[c]})` }))} />
          <FilterSelect label="Detector" allLabel="All detectors" value={state.detector} onChange={(v) => onState({ detector: v, offset: 0 })} options={Object.keys(breakdown.by_detector).map((c) => ({ value: c, label: `${c} (${breakdown.by_detector[c]})` }))} />
          <FilterSelect label="Severity" allLabel="Any severity" value={state.severity} onChange={(v) => onState({ severity: v, offset: 0 })} options={["high", "medium", "low"].map((v) => ({ value: v, label: v }))} className="min-w-[120px]" />
          <FilterSelect
            label="Sort"
            value={state.sort}
            onChange={(v) => onState({ sort: v, offset: 0 })}
            options={[
              { value: "score", label: "Highest score first" },
              { value: "row", label: "Row order" },
            ]}
          />
          <div className="flex items-center gap-2 sm:ml-auto">
            <Switch id="all-rows" checked={state.all === "1"} onCheckedChange={(v) => onState({ all: v ? "1" : "", offset: 0 })} />
            <Label htmlFor="all-rows" className="text-sm font-normal">
              Show every row
            </Label>
          </div>
        </div>
        {q.error ? (
          <ErrorState error={q.error} retry={() => q.refetch()} />
        ) : (
          <>
            <div className="max-h-[70vh] overflow-auto">
              <DataTable
                caption="Analysed rows"
                columns={columns}
                data={q.data?.rows ?? []}
                loading={q.isFetching}
                getRowId={(r) => String(r.index)}
                dense
                empty={<EmptyState icon={SearchXIcon} title="No rows match" description="Clear a filter or include every row." />}
              />
            </div>
            <Pager offset={state.offset} limit={state.limit} total={q.data?.total ?? 0} noun="rows" onChange={(offset, limit) => onState({ offset, limit })} />
          </>
        )}
      </Section>
    </div>
  );
}
