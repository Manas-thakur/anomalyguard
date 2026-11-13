// Fix & export: choose a remediation strategy per problem type and per column,
// preview the before/after diff, download the cleaned file and reports, and
// send what a fix could not settle to the review queue (with a confirmation).

import type { ColumnDef } from "@tanstack/react-table";
import { ArrowRightIcon, DownloadIcon, FlagIcon, InboxIcon, PlayIcon, WandSparklesIcon } from "lucide-react";
import { useState } from "react";
import { useNavigate } from "react-router";
import { toast } from "sonner";

import {
  Confirmation,
  ConfirmationAccepted,
  ConfirmationAction,
  ConfirmationActions,
  ConfirmationBody,
  ConfirmationRequest,
  ConfirmationTitle,
} from "@/components/ai-elements/confirmation";
import { EmptyState, ErrorState, InlineError, KpiGrid, Section } from "@/components/common";
import { DataTable, Pager } from "@/components/data-table";
import { FilterSelect } from "@/components/filters";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Field, FieldDescription, FieldLabel } from "@/components/ui/field";
import { Label } from "@/components/ui/label";
import { Spinner } from "@/components/ui/spinner";
import { Switch } from "@/components/ui/switch";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { api, download } from "@/lib/api";
import { fmtInt, fmtNum, fmtValue } from "@/lib/format";
import { queryClient, refreshAll, useChanges } from "@/lib/queries";
import type { Analysis, Change, RemediationPolicy, RemediationResult } from "@/lib/types";

const OUTLIER = ["cap", "winsorize", "median", "mean", "null", "flag", "drop", "keep"];
const MISSING = ["auto", "median", "mean", "mode", "ffill", "bfill", "interpolate", "flag", "drop", "keep"];
const INVALID = ["coerce", "flag", "drop", "keep"];
export const STRATEGY_HELP: Record<string, string> = {
  cap: "clip to robust fences (median ± 3.5 MAD); values it cannot move go to review",
  winsorize: "clip to the 1st and 99th percentiles",
  median: "replace with the column median",
  mean: "replace with the column mean",
  null: "blank the value",
  flag: "leave the value, send it to the review queue",
  drop: "drop the whole row",
  keep: "do nothing",
};

const opts = (list: string[]) => list.map((v) => ({ value: v, label: v }));

const changeColumns: ColumnDef<Change, unknown>[] = [
  { id: "row", header: "Row", cell: ({ row }) => <span className="text-muted-foreground font-mono text-xs">{String(row.original.index)}</span> },
  { id: "column", header: "Column", cell: ({ row }) => <span className="font-mono text-xs">{row.original.column}</span> },
  {
    id: "diff",
    header: "Before → after",
    cell: ({ row: { original: c } }) => (
      <span className="flex items-center gap-2 font-mono text-xs whitespace-nowrap">
        <span className="bg-sev-high-soft text-sev-high rounded px-1.5 py-0.5 line-through decoration-1">{fmtValue(c.before)}</span>
        <ArrowRightIcon className="text-muted-foreground size-3" aria-label="changed to" />
        <span className="bg-ok-soft text-ok rounded px-1.5 py-0.5 font-semibold">{fmtValue(c.after)}</span>
      </span>
    ),
  },
  {
    id: "strategy",
    header: "Strategy",
    cell: ({ row }) => (
      <Badge variant="secondary" className="rounded-md font-mono text-[11px]">
        {row.original.strategy}
      </Badge>
    ),
  },
  {
    id: "reason",
    header: "Reason",
    meta: { hideBelow: "md", className: "max-w-[420px] min-w-[240px] whitespace-normal" },
    cell: ({ row }) => (
      <span className="text-muted-foreground line-clamp-2 text-xs" title={row.original.reason}>
        {row.original.reason}
      </span>
    ),
  },
];

function ChangesTable({ analysisId, result }: { analysisId: string; result: RemediationResult }) {
  const [state, setState] = useState({ offset: 0, limit: 25, column: "" });
  const q = useChanges(analysisId, { ...state }, true);
  const sm = result.summary;
  return (
    <Section
      title="Changed cells"
      description={Object.entries(sm.changes_by_strategy || {}).map(([k, v]) => `${k} ${v}`).join(" · ") || "No cell changes"}
      actions={
        <FilterSelect
          label="Filter changes by column"
          allLabel="All columns"
          value={state.column}
          onChange={(v) => setState((s) => ({ ...s, column: v, offset: 0 }))}
          options={Object.entries(sm.changes_by_column || {}).map(([c, n]) => ({ value: c, label: `${c} (${n})` }))}
        />
      }
      flush
    >
      {q.error ? (
        <ErrorState error={q.error} retry={() => q.refetch()} />
      ) : (
        <>
          <DataTable
            caption="Cell-level diff"
            columns={changeColumns}
            data={q.data?.items ?? []}
            loading={q.isFetching}
            getRowId={(c, i) => `${String(c.index)}-${c.column}-${i}`}
            empty={<EmptyState icon={WandSparklesIcon} title="No cell changes" description="This policy only flags or drops. Flagged values can go to the review queue." />}
          />
          <Pager offset={state.offset} limit={state.limit} total={q.data?.total ?? 0} noun="changes" onChange={(offset, limit) => setState((s) => ({ ...s, offset, limit }))} />
        </>
      )}
    </Section>
  );
}

function DownloadButton({ path, label }: { path: string; label: string }) {
  const [busy, setBusy] = useState(false);
  return (
    <Button
      variant="outline"
      disabled={busy}
      onClick={async () => {
        setBusy(true);
        try {
          await download(path);
        } catch (err) {
          toast.error((err as Error).message);
        } finally {
          setBusy(false);
        }
      }}
    >
      {busy ? <Spinner /> : <DownloadIcon />} {label}
    </Button>
  );
}

function SendToReview({ analysis, n }: { analysis: Analysis; n: number }) {
  const navigate = useNavigate();
  const [state, setState] = useState<"idle" | "requested" | "accepted">("idle");
  const [busy, setBusy] = useState(false);
  const [queued, setQueued] = useState(0);
  if (!n) return <p className="text-muted-foreground text-sm">Nothing was flagged for review by this policy.</p>;
  if (state === "idle")
    return (
      <Button variant="outline" onClick={() => setState("requested")}>
        <FlagIcon /> Send {fmtInt(n)} flagged values to review
      </Button>
    );
  return (
    <Confirmation state={state === "accepted" ? "accepted" : "requested"}>
      <ConfirmationRequest>
        <ConfirmationTitle>Send {fmtInt(n)} flagged values to the review queue?</ConfirmationTitle>
        <ConfirmationBody>
          Each value becomes a pending review item with its reason and, where possible, a suggested value. Approved items can then be written into this analysis's cleaned CSV.
        </ConfirmationBody>
      </ConfirmationRequest>
      <ConfirmationAccepted>
        <ConfirmationTitle>{fmtInt(queued)} items are in the review queue</ConfirmationTitle>
        <ConfirmationBody>
          <Button variant="link" className="h-auto p-0" onClick={() => navigate(`/review?run=${analysis.run_id}`)}>
            <InboxIcon /> Open the review inbox
          </Button>
        </ConfirmationBody>
      </ConfirmationAccepted>
      <ConfirmationActions>
        <ConfirmationAction variant="ghost" onClick={() => setState("idle")} disabled={busy}>
          Cancel
        </ConfirmationAction>
        <ConfirmationAction
          disabled={busy}
          onClick={async () => {
            setBusy(true);
            try {
              const out = await api.post<{ queued: number }>(`/api/analyses/${analysis.id}/review`);
              setQueued(out.queued);
              setState("accepted");
              queryClient.invalidateQueries({ queryKey: ["review"] });
              queryClient.invalidateQueries({ queryKey: ["summary"] });
            } catch (err) {
              toast.error((err as Error).message);
            } finally {
              setBusy(false);
            }
          }}
        >
          {busy ? <Spinner /> : <InboxIcon />} Send to review
        </ConfirmationAction>
      </ConfirmationActions>
    </Confirmation>
  );
}

export function FixPanel({ analysis }: { analysis: Analysis }) {
  const bd = analysis.breakdown ?? { by_column: {}, by_detector: {}, by_severity: {}, findings: 0, rows: 0 };
  const [result, setResult] = useState<RemediationResult | null>(analysis.remediation ?? null);
  const [policy, setPolicy] = useState<RemediationPolicy>(() => {
    const p = analysis.remediation?.policy;
    return {
      default: { missing: "auto", outlier: "cap", invalid: "coerce", ...(p?.default ?? {}) },
      columns: { ...(p?.columns ?? {}) },
      dedupe: p?.dedupe !== false,
    };
  });
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const flaggedCols = Object.keys(bd.by_column).filter((c) => c !== "(row)");

  const setDefault = (k: "missing" | "outlier" | "invalid", v: string) => setPolicy((p) => ({ ...p, default: { ...p.default, [k]: v } }));
  const setCol = (c: string, k: "missing" | "outlier", v: string) =>
    setPolicy((p) => {
      const cur = { ...(p.columns[c] ?? {}) };
      if (v) cur[k] = v;
      else delete cur[k];
      return { ...p, columns: { ...p.columns, [c]: cur } };
    });

  async function preview() {
    setBusy(true);
    setError(null);
    try {
      const body = { ...policy, columns: Object.fromEntries(Object.entries(policy.columns).filter(([, v]) => Object.keys(v).length)) };
      const res = await api.post<RemediationResult>(`/api/analyses/${analysis.id}/remediate`, body);
      setResult(res);
      queryClient.invalidateQueries({ queryKey: ["analysis", analysis.id] });
      refreshAll();
      toast.success("Fixes previewed", { description: `${fmtInt(res.summary.cells_changed)} cells changed, ${fmtInt(res.summary.rows_dropped)} rows dropped. The cleaned file is ready to download.` });
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }

  const sm = result?.summary;
  const stats = Object.entries(result?.column_stats ?? {});
  return (
    <div className="space-y-6">
      <Section title="Remediation policy" description="Choose what happens to each kind of problem. Only cells a detector attributed to a column are treated as outliers.">
        <div className="space-y-5">
          <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
            <Field>
              <FieldLabel>Outliers</FieldLabel>
              <FilterSelect label="Default outlier strategy" size="default" className="w-full" value={policy.default.outlier ?? "cap"} onChange={(v) => setDefault("outlier", v)} options={opts(OUTLIER)} />
              <FieldDescription className="text-xs">cap: robust fences; unmovable values go to review</FieldDescription>
            </Field>
            <Field>
              <FieldLabel>Missing values</FieldLabel>
              <FilterSelect label="Default missing-value strategy" size="default" className="w-full" value={policy.default.missing ?? "auto"} onChange={(v) => setDefault("missing", v)} options={opts(MISSING)} />
              <FieldDescription className="text-xs">auto: median for numbers, mode for categories, flag ids and text</FieldDescription>
            </Field>
            <Field>
              <FieldLabel>Type errors</FieldLabel>
              <FilterSelect label="Type error strategy" size="default" className="w-full" value={policy.default.invalid ?? "coerce"} onChange={(v) => setDefault("invalid", v)} options={opts(INVALID)} />
              <FieldDescription className="text-xs">coerce: unparseable values become missing, then imputed</FieldDescription>
            </Field>
            <Field orientation="horizontal" className="items-center self-center">
              <Switch id="dedupe" checked={policy.dedupe !== false} onCheckedChange={(v) => setPolicy((p) => ({ ...p, dedupe: v }))} />
              <Label htmlFor="dedupe" className="font-normal">
                Drop duplicate rows
              </Label>
            </Field>
          </div>
          {flaggedCols.length ? (
            <div className="rounded-lg border">
              <Table>
                <TableHeader className="bg-muted/40">
                  <TableRow>
                    <TableHead className="text-xs">Column</TableHead>
                    <TableHead className="text-right text-xs">Findings</TableHead>
                    <TableHead className="text-xs">Outliers</TableHead>
                    <TableHead className="text-xs">Missing values</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {flaggedCols.map((c) => (
                    <TableRow key={c}>
                      <TableCell className="font-mono text-xs">{c}</TableCell>
                      <TableCell className="text-right tabular">{fmtInt(bd.by_column[c])}</TableCell>
                      <TableCell>
                        <FilterSelect label={`Outlier strategy for ${c}`} allLabel={`default (${policy.default.outlier})`} value={policy.columns[c]?.outlier ?? ""} onChange={(v) => setCol(c, "outlier", v)} options={opts(OUTLIER)} />
                      </TableCell>
                      <TableCell>
                        <FilterSelect label={`Missing-value strategy for ${c}`} allLabel={`default (${policy.default.missing})`} value={policy.columns[c]?.missing ?? ""} onChange={(v) => setCol(c, "missing", v)} options={opts(MISSING)} />
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </div>
          ) : null}
          <details className="text-muted-foreground text-xs">
            <summary className="hover:text-foreground cursor-pointer select-none">What each outlier strategy does</summary>
            <dl className="mt-2 grid gap-x-4 gap-y-1 sm:grid-cols-[auto_1fr]">
              {Object.entries(STRATEGY_HELP).map(([k, v]) => (
                <div key={k} className="contents">
                  <dt className="text-foreground font-mono">{k}</dt>
                  <dd>{v}</dd>
                </div>
              ))}
            </dl>
          </details>
          {error ? <InlineError>{error}</InlineError> : null}
          <Button onClick={preview} disabled={busy}>
            {busy ? <Spinner /> : <PlayIcon />} {result ? "Preview again" : "Preview fixes"}
          </Button>
        </div>
      </Section>

      {result && sm ? (
        <>
          <KpiGrid
            items={[
              { label: "Rows out", value: fmtInt(sm.rows_out), sub: `of ${fmtInt(sm.rows_in)} in` },
              { label: "Cells changed", value: fmtInt(sm.cells_changed), sub: `${Object.keys(sm.changes_by_column || {}).length} columns` },
              { label: "Rows dropped", value: fmtInt(sm.rows_dropped), sub: Object.entries(sm.drop_reasons || {}).map(([k, v]) => `${v} ${k}`).join(", ") || "none" },
              { label: "Flagged for review", value: fmtInt(sm.rows_flagged_for_review), sub: `${fmtInt(result.n_flagged)} values` },
            ]}
          />
          <Section title="Export" description="The cleaned CSV and both reports reflect the policy previewed above.">
            <div className="space-y-4">
              <div className="flex flex-wrap gap-2">
                <DownloadButton path={`/api/analyses/${analysis.id}/download/cleaned.csv`} label="Cleaned CSV" />
                <DownloadButton path={`/api/analyses/${analysis.id}/download/remediation.md`} label="Report (Markdown)" />
                <DownloadButton path={`/api/analyses/${analysis.id}/download/remediation.json`} label="Report (JSON)" />
                <DownloadButton path={`/api/analyses/${analysis.id}/download/anomalies.json`} label="Anomalies (JSON)" />
              </div>
              <SendToReview analysis={analysis} n={result.n_flagged} />
            </div>
          </Section>
          {stats.length ? (
            <Section title="Column statistics, before and after" flush>
              <Table>
                <TableHeader className="bg-muted/40">
                  <TableRow>
                    {["Column", "Nulls", "Mean", "Std", "Min", "Max"].map((h, i) => (
                      <TableHead key={h} className={i ? "text-right text-xs" : "text-xs"}>
                        {h}
                      </TableHead>
                    ))}
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {stats.map(([c, st]) => (
                    <TableRow key={c}>
                      <TableCell className="font-mono text-xs">{c}</TableCell>
                      {["nulls", "mean", "std", "min", "max"].map((k) => {
                        const b = st.before[k];
                        const a = st.after[k];
                        const changed = b !== a && !(b === undefined && a === undefined);
                        return (
                          <TableCell key={k} className="text-right font-mono text-xs whitespace-nowrap tabular">
                            {b === undefined ? (
                              <span className="text-muted-foreground">–</span>
                            ) : changed ? (
                              <>
                                <span className="text-muted-foreground">{fmtNum(b)}</span>
                                <span className="text-muted-foreground mx-1" aria-label="to">
                                  →
                                </span>
                                <span className="font-semibold">{fmtNum(a)}</span>
                              </>
                            ) : (
                              fmtNum(a)
                            )}
                          </TableCell>
                        );
                      })}
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </Section>
          ) : null}
          <ChangesTable key={result.created_at} analysisId={analysis.id} result={result} />
        </>
      ) : null}
    </div>
  );
}
