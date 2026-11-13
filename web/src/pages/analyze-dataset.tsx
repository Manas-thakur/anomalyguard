// Analyze, steps 2-3: the profile (quality scores, column cards with
// histograms) and the detector setup (detectors, group-by, sensitivity).

import { ChevronDownIcon, PlayIcon, SlidersHorizontalIcon } from "lucide-react";
import { useMemo, useRef, useState } from "react";
import { Link, useNavigate, useParams } from "react-router";

import { AnalysisProgress, Stepper } from "@/components/analyze/steps";
import { MiniHistogram } from "@/components/charts/small-charts";
import { ErrorState, InlineError, KpiGrid, KpiSkeleton, PageHeader, useTitle } from "@/components/common";
import { FilterSelect } from "@/components/filters";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Checkbox } from "@/components/ui/checkbox";
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "@/components/ui/collapsible";
import { Field, FieldDescription, FieldGroup, FieldLabel, FieldLegend, FieldSet } from "@/components/ui/field";
import { Label } from "@/components/ui/label";
import { Skeleton } from "@/components/ui/skeleton";
import { Spinner } from "@/components/ui/spinner";
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group";
import { api, waitForJob } from "@/lib/api";
import { fmtBytes, fmtInt, fmtNum, fmtPct, fmtTime } from "@/lib/format";
import { refreshAll, useDetectors, useProfile } from "@/lib/queries";
import type { Analysis, ColumnProfile, DatasetProfile, Detector, Job } from "@/lib/types";
import { cn } from "@/lib/utils";

const CATEGORY: Record<string, string> = { statistical: "Statistical", ml: "Machine learning", timeseries: "Time series", contextual: "Contextual", ensemble: "Ensemble" };

function ColumnCard({ c }: { c: ColumnProfile }) {
  const stats: [string, string][] =
    c.mean !== null && c.mean !== undefined
      ? [
          ["mean", fmtNum(c.mean)],
          ["median", fmtNum(c.median)],
          ["min", fmtNum(c.min)],
          ["max", fmtNum(c.max)],
        ]
      : c.min !== null && c.min !== undefined
        ? [
            ["min", String(c.min).slice(0, 19)],
            ["max", String(c.max).slice(0, 19)],
          ]
        : [];
  const rows: [string, string][] = [["nulls", `${fmtInt(c.nulls)} (${c.null_pct}%)`], ["unique", fmtInt(c.unique)], ...(c.invalid ? ([["invalid", fmtInt(c.invalid)]] as [string, string][]) : []), ...stats];
  return (
    <article className="bg-card flex min-w-0 flex-col gap-2.5 rounded-lg border p-3">
      <div className="flex items-center justify-between gap-2">
        <h3 className="truncate font-mono text-sm font-semibold" title={c.name}>
          {c.name}
        </h3>
        <Badge variant="secondary" className="rounded-md font-mono text-[11px]">
          {c.dtype}
        </Badge>
      </div>
      {c.histogram ? (
        <MiniHistogram hist={c.histogram} column={c.name} />
      ) : c.top_values?.length ? (
        <ul className="space-y-1" aria-label={`Most common values of ${c.name}`}>
          {c.top_values.slice(0, 4).map(([v, n]) => {
            const max = c.top_values[0][1] || 1;
            return (
              <li key={v} className="relative flex items-center justify-between gap-2 overflow-hidden rounded px-1.5 py-0.5 text-xs">
                <span aria-hidden className="bg-primary/10 absolute inset-y-0 left-0 rounded" style={{ width: `${(n / max) * 100}%` }} />
                <span className="relative truncate font-mono" title={v}>
                  {v}
                </span>
                <span className="text-muted-foreground relative tabular">{fmtInt(n)}</span>
              </li>
            );
          })}
        </ul>
      ) : (
        <div className="text-muted-foreground flex h-12 items-center text-xs">No distribution for this type</div>
      )}
      <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-0.5 text-xs">
        {rows.map(([k, v]) => (
          <div key={k} className="contents">
            <dt className="text-muted-foreground">{k}</dt>
            <dd className={cn("truncate text-right font-mono tabular", k === "invalid" && "text-sev-high", k === "nulls" && c.nulls > 0 && "text-sev-medium")} title={v}>
              {v}
            </dd>
          </div>
        ))}
      </dl>
    </article>
  );
}

function DetectorSetup({ prof, detectors, datasetId }: { prof: DatasetProfile; detectors: Detector[]; datasetId: string }) {
  const navigate = useNavigate();
  const sug = prof.suggestions;
  // a time-ordered file without natural groups is most likely a series
  const series = sug.time_columns.length > 0 && sug.group_by.length === 0;
  const [chosen, setChosen] = useState<Set<string>>(() => new Set(series ? ["mad", "seasonal", "cusum"] : ["mad", "iforest"]));
  const [groupBy, setGroupBy] = useState(sug.group_by.includes("region") ? "region" : "");
  const [sensitivity, setSensitivity] = useState("medium");
  const [combine, setCombine] = useState("any");
  const [timeColumn, setTimeColumn] = useState(sug.time_columns[0] ?? "");
  const [cols, setCols] = useState<Set<string>>(() => new Set(sug.numeric_columns));
  const [job, setJob] = useState<Job | null>(null);
  const [running, setRunning] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const byCat = useMemo(() => {
    const out: Record<string, Detector[]> = {};
    for (const d of detectors) (out[d.category] ||= []).push(d);
    return out;
  }, [detectors]);

  async function run() {
    setRunning(true);
    setError(null);
    setJob(null);
    try {
      const list = [...cols];
      const res = await api.post<{ analysis: Analysis; job: Job }>("/api/analyses", {
        dataset_id: datasetId,
        detectors: [...chosen],
        group_by: groupBy || null,
        time_column: timeColumn || null,
        sensitivity,
        combine,
        columns: list.length && list.length < sug.numeric_columns.length ? list : null,
      });
      setJob(res.job);
      const done = await waitForJob(api, res.job.id, { onUpdate: setJob, interval: 400 });
      if (done.status !== "success") throw new Error(done.error || `Job ${done.status}`);
      refreshAll();
      navigate(`/analyze/a/${res.analysis.id}`);
    } catch (err) {
      setError((err as Error).message);
      setRunning(false);
    }
  }

  return (
    <Card id="detector-setup" className="gap-0 py-0 shadow-xs lg:sticky lg:top-16">
      <CardHeader className="border-b px-4 py-3.5 [.border-b]:pb-3.5">
        <CardTitle className="flex items-center gap-2 text-sm font-semibold">
          <SlidersHorizontalIcon className="text-primary size-4" aria-hidden /> Detect anomalies
        </CardTitle>
        <CardDescription className="text-xs">Scores are normalised so 1.0 is each detector's threshold.</CardDescription>
      </CardHeader>
      <CardContent className="p-4">
        <FieldGroup className="gap-5">
          {Object.entries(byCat).map(([cat, list]) => (
            <FieldSet key={cat} className="gap-2">
              <FieldLegend variant="label" className="text-muted-foreground mb-0 text-xs font-medium tracking-wide uppercase">
                {CATEGORY[cat] ?? cat}
              </FieldLegend>
              <div className="grid gap-1">
                {list.map((d) => {
                  const id = `det-${d.name}`;
                  const on = chosen.has(d.name);
                  return (
                    <Label
                      key={d.name}
                      htmlFor={id}
                      className={cn("hover:bg-muted/60 flex cursor-pointer items-start gap-2.5 rounded-md border border-transparent px-2 py-1.5 font-normal", on && "border-primary/25 bg-accent/50")}
                    >
                      <Checkbox
                        id={id}
                        checked={on}
                        className="mt-0.5"
                        onCheckedChange={(v) =>
                          setChosen((s) => {
                            const n = new Set(s);
                            if (v) n.add(d.name);
                            else n.delete(d.name);
                            return n;
                          })
                        }
                      />
                      <span className="min-w-0">
                        <span className="block font-mono text-[13px] font-semibold">{d.name}</span>
                        <span className="text-muted-foreground block text-xs leading-snug">{d.description}</span>
                      </span>
                    </Label>
                  );
                })}
              </div>
            </FieldSet>
          ))}
          <Field>
            <FieldLabel>Group by</FieldLabel>
            <FilterSelect
              label="Group by"
              size="default"
              allLabel="No grouping"
              value={groupBy}
              onChange={setGroupBy}
              className="w-full"
              options={[...sug.group_by.map((c) => ({ value: c, label: c })), ...prof.dataset.columns.filter((c) => !sug.group_by.includes(c)).map((c) => ({ value: c, label: `${c} (high cardinality)` }))]}
            />
            <FieldDescription className="text-xs">Fits each detector within groups, so a west-region price on a north order stands out (contextual anomalies).</FieldDescription>
          </Field>
          <Field>
            <FieldLabel id="sens-label">Sensitivity</FieldLabel>
            <ToggleGroup type="single" variant="outline" value={sensitivity} onValueChange={(v) => v && setSensitivity(v)} aria-labelledby="sens-label" className="w-full">
              {["low", "medium", "high"].map((v) => (
                <ToggleGroupItem key={v} value={v} className="flex-1 capitalize">
                  {v}
                </ToggleGroupItem>
              ))}
            </ToggleGroup>
            <FieldDescription className="text-xs">Low raises every threshold 1.5×, high lowers it to 0.7×. Feedback-tuned thresholds still apply.</FieldDescription>
          </Field>
          {sug.numeric_columns.length ? (
            <FieldSet className="gap-2">
              <FieldLegend variant="label">Columns to score</FieldLegend>
              <div className="flex flex-wrap gap-x-4 gap-y-2">
                {sug.numeric_columns.map((c) => (
                  <Label key={c} className="flex items-center gap-2 font-mono text-xs font-normal">
                    <Checkbox
                      checked={cols.has(c)}
                      onCheckedChange={(v) =>
                        setCols((s) => {
                          const n = new Set(s);
                          if (v) n.add(c);
                          else n.delete(c);
                          return n;
                        })
                      }
                    />
                    {c}
                  </Label>
                ))}
              </div>
              <FieldDescription className="text-xs">Numeric columns; id-like columns are excluded.</FieldDescription>
            </FieldSet>
          ) : null}
          <Collapsible>
            <CollapsibleTrigger className="group text-muted-foreground hover:text-foreground flex items-center gap-1 rounded text-sm font-medium outline-none focus-visible:ring-[3px] focus-visible:ring-ring/50">
              <ChevronDownIcon className="size-4 transition-transform group-data-[state=closed]:-rotate-90" aria-hidden /> More options
            </CollapsibleTrigger>
            <CollapsibleContent className="mt-3 space-y-4">
              <Field>
                <FieldLabel>Combine detectors</FieldLabel>
                <FilterSelect
                  label="Combine detectors"
                  size="default"
                  value={combine}
                  onChange={setCombine}
                  className="w-full"
                  options={[
                    { value: "any", label: "Any detector flags it" },
                    { value: "vote", label: "At least 2 detectors agree" },
                    { value: "all", label: "Every detector agrees" },
                  ]}
                />
              </Field>
              <Field>
                <FieldLabel>Time column</FieldLabel>
                <FilterSelect label="Time column" size="default" allLabel="None" value={timeColumn} onChange={setTimeColumn} className="w-full" options={prof.dataset.columns.map((c) => ({ value: c, label: c }))} />
                <FieldDescription className="text-xs">Rows are sorted by it before time-series detectors run.</FieldDescription>
              </Field>
            </CollapsibleContent>
          </Collapsible>
          {!chosen.size ? <p className="text-sev-high text-sm">Pick at least one detector.</p> : null}
          {error ? <InlineError>{error}</InlineError> : null}
          <Button size="lg" onClick={run} disabled={!chosen.size || running} className="w-full">
            {running ? <Spinner /> : <PlayIcon />} {running ? "Analyzing…" : "Run analysis"}
          </Button>
          {running ? <AnalysisProgress job={job} title={`Analyzing ${prof.dataset.name}`} /> : null}
        </FieldGroup>
      </CardContent>
    </Card>
  );
}

export default function AnalyzeDatasetPage() {
  const id = useParams().id as string;
  const prof = useProfile(id);
  const detectors = useDetectors();
  const setupRef = useRef<HTMLDivElement>(null);
  const p = prof.data;
  useTitle(p ? `Profile ${p.dataset.name}` : "Profile");
  const q = p?.quality;
  const missing = q ? Object.values(q.null_counts || {}).reduce((a, b) => a + b, 0) : 0;

  if (prof.error) return <ErrorState error={prof.error} retry={() => prof.refetch()} />;

  return (
    <div className="animate-fade-in space-y-6">
      <PageHeader
        crumbs={[{ label: "Analyze", to: "/analyze" }, { label: "Profile" }]}
        title={p ? p.dataset.name : <Skeleton className="h-8 w-64" />}
        description={p ? `${fmtInt(p.dataset.rows)} rows · ${p.dataset.columns.length} columns · ${fmtBytes(p.dataset.size)} · uploaded ${fmtTime(p.dataset.created_at)}` : undefined}
        actions={
          <Button
            onClick={() => {
              document.getElementById("detector-setup")?.scrollIntoView({ behavior: "smooth", block: "start" });
              setTimeout(() => document.querySelector<HTMLButtonElement>("#detector-setup button[data-slot=checkbox]")?.focus({ preventScroll: true }), 400);
            }}
            className="lg:hidden"
          >
            Set up detection
          </Button>
        }
      >
        <Stepper current={2} links={{ 1: "/analyze" }} />
      </PageHeader>
      {!q ? (
        <KpiSkeleton n={5} />
      ) : (
        <KpiGrid
          items={[
            { label: "Quality score", value: fmtPct(q.score), tone: q.score < 0.9 ? "alert" : "default", sub: "weighted mean of the four below" },
            { label: "Completeness", value: fmtPct(q.completeness), sub: `${fmtInt(missing)} missing cells` },
            { label: "Validity", value: fmtPct(q.validity), sub: `${fmtInt(p?.validation.invalid_rows ?? 0)} rows break the inferred schema` },
            { label: "Uniqueness", value: fmtPct(q.uniqueness), sub: `${fmtInt(q.duplicate_rows)} duplicate rows` },
            { label: "Freshness", value: q.freshness === null ? "–" : fmtPct(q.freshness), sub: q.newest_timestamp ? `newest ${q.newest_timestamp.slice(0, 16).replace("T", " ")}` : "no timestamp column" },
          ]}
        />
      )}
      <div className="grid gap-6 lg:grid-cols-[minmax(0,1fr)_360px]">
        <section aria-labelledby="cols-title" className="min-w-0 space-y-3">
          <div>
            <h2 id="cols-title" className="text-sm font-semibold">
              Columns
            </h2>
            <p className="text-muted-foreground text-xs">Inferred type, statistics and distribution. Red bars count values beyond the 1st/99th percentile.</p>
          </div>
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 xl:grid-cols-3">
            {p ? p.columns.map((c) => <ColumnCard key={c.name} c={c} />) : Array.from({ length: 6 }, (_, i) => <Skeleton key={i} className="h-44 rounded-lg" />)}
          </div>
        </section>
        <div ref={setupRef}>
          {p && detectors.data ? (
            <DetectorSetup prof={p} detectors={detectors.data} datasetId={id} />
          ) : detectors.error ? (
            <ErrorState error={detectors.error} />
          ) : (
            <Skeleton className="h-[560px] rounded-xl" />
          )}
          <p className="text-muted-foreground mt-3 text-xs">
            Earlier analyses of this file are listed on <Link className="underline underline-offset-4" to="/analyze">Analyze</Link> and in <Link className="underline underline-offset-4" to="/runs?kind=analysis">Runs</Link>.
          </p>
        </div>
      </div>
    </div>
  );
}
