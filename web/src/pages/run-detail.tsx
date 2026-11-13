// Run detail: KPIs, incident cards with expected-band charts, the findings
// table, remediation, alerts and downloadable outputs.

import { BellIcon, DownloadIcon, ExternalLinkIcon, FileSearchIcon, InboxIcon, WrenchIcon } from "lucide-react";
import { useState } from "react";
import { Link, useParams, useSearchParams } from "react-router";
import { toast } from "sonner";

import { BarList, EmptyState, ErrorState, InlineError, KeyValue, KpiGrid, KpiSkeleton, PageHeader, Section, StatusBadge, TimeAgo, useTitle } from "@/components/common";
import { FindingsTable, type FindingFilters } from "@/components/findings-table";
import { IncidentList } from "@/components/incidents/incident-list";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Spinner } from "@/components/ui/spinner";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { download } from "@/lib/api";
import { fmtInt, fmtMs, fmtPct, fmtTime, runLabel } from "@/lib/format";
import { useRun, useRunIncidents } from "@/lib/queries";
import type { RunDetail } from "@/lib/types";

function DownloadButton({ path, label }: { path: string; label: string }) {
  const [busy, setBusy] = useState(false);
  return (
    <Button
      variant="outline"
      size="sm"
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

function Details({ run }: { run: RunDetail }) {
  const rem = run.metrics.remediation;
  const hasRem = rem || run.cells_changed || run.rows_dropped || run.flagged_for_review;
  return (
    <div className="space-y-6">
      <div className="grid gap-6 lg:grid-cols-2">
        <Section title="Remediation" description="What the run changed in the data">
          {!hasRem ? (
            <EmptyState
              icon={WrenchIcon}
              title="No remediation"
              description={run.kind === "analysis" ? "Open the analysis and use Fix & export to preview fixes." : "This pipeline has remediation turned off, or nothing needed fixing."}
              className="py-4"
            />
          ) : (
            <KeyValue
              items={[
                ["Cells changed", <span className="tabular">{fmtInt(run.cells_changed)}</span>],
                ["Rows dropped", <span className="tabular">{fmtInt(run.rows_dropped)}</span>],
                ["Rows flagged", <span className="tabular">{fmtInt(run.flagged_for_review)}</span>],
                ...(rem
                  ? ([
                      ["Rows in / out", <span className="tabular">{`${fmtInt(rem.rows_in)} / ${fmtInt(rem.rows_out)}`}</span>],
                      ...Object.entries(rem.changes_by_strategy || {}).map(([k, v]) => [<span className="font-mono text-xs">{k}</span>, <span className="tabular">{fmtInt(v)}</span>] as [React.ReactNode, React.ReactNode]),
                    ] as [React.ReactNode, React.ReactNode][])
                  : []),
              ]}
            />
          )}
        </Section>
        <Section title="Alerts sent" flush>
          {!run.alerts.length ? (
            <EmptyState icon={BellIcon} title="No alerts" description="No alert rule fired for this run." className="py-6" />
          ) : (
            <ul className="divide-y">
              {run.alerts.map((a) => (
                <li key={a.id} className="space-y-1 px-4 py-3">
                  <div className="flex flex-wrap items-center gap-2">
                    <StatusBadge status={a.severity || "info"} />
                    <span className="text-sm font-medium">{a.title}</span>
                  </div>
                  <p className="text-muted-foreground text-xs">
                    {a.status} · {a.channels || "no channels"} · <TimeAgo value={a.created_at} />
                  </p>
                </li>
              ))}
            </ul>
          )}
        </Section>
      </div>
      <Section title="Outputs" description="Files written by this run">
        {run.artifacts.length ? (
          <div className="flex flex-wrap gap-2">
            {run.artifacts.map((name) => (
              <DownloadButton key={name} path={`/api/runs/${run.id}/artifacts/${encodeURIComponent(name)}`} label={name} />
            ))}
          </div>
        ) : (
          <p className="text-muted-foreground text-sm">{run.kind === "analysis" ? "Preview fixes in Analyze to create the cleaned file and reports." : "This pipeline has no sink configured, or its outputs were moved."}</p>
        )}
      </Section>
    </div>
  );
}

export default function RunDetailPage() {
  const id = Number(useParams().id);
  const [params, setParams] = useSearchParams();
  const tab = ["findings", "details"].includes(params.get("tab") ?? "") ? (params.get("tab") as string) : "incidents";
  const focus = params.get("incident");
  const q = useRun(id);
  const incidents = useRunIncidents(id, false);
  const [filters, setFilters] = useState<FindingFilters>({ column: "", detector: "", severity: "" });
  const run = q.data;
  useTitle(run ? `${runLabel(run.pipeline)} · run #${run.id}` : `Run #${id}`);

  const setTab = (t: string) => {
    const next = new URLSearchParams(params);
    if (t === "incidents") next.delete("tab");
    else next.set("tab", t);
    next.delete("incident");
    setParams(next, { replace: true });
  };

  if (q.error) {
    return (q.error as { status?: number }).status === 404 ? (
      <div className="bg-card mt-6 rounded-xl border">
        <EmptyState icon={FileSearchIcon} title={`Run #${id} does not exist`} description="It may have been recorded in a different state directory.">
          <Button asChild variant="outline">
            <Link to="/runs">All runs</Link>
          </Button>
        </EmptyState>
      </div>
    ) : (
      <ErrorState error={q.error} retry={() => q.refetch()} />
    );
  }

  const m = run?.metrics;
  const bd = run?.breakdown;
  const filterBy = (patch: Partial<FindingFilters>) => {
    setFilters((f) => ({ ...f, ...patch }));
    setTab("findings");
  };

  return (
    <div className="animate-fade-in space-y-6">
      <PageHeader
        crumbs={[{ label: "Runs", to: "/runs" }, { label: `#${id}` }]}
        title={run ? `${runLabel(run.pipeline)} · run #${run.id}` : `Run #${id}`}
        description={
          run ? (
            <>
              {run.kind === "analysis" ? "Analysis" : "Pipeline run"} started {fmtTime(run.started_at)}, took {fmtMs(run.duration_ms)}.
              {m?.source ? ` Source: ${String(m.source).split(/[\\/]/).pop()}` : ""}
            </>
          ) : (
            "Loading…"
          )
        }
        actions={
          run ? (
            <>
              {m?.analysis_id ? (
                <Button variant="outline" asChild>
                  <Link to={`/analyze/a/${m.analysis_id}`}>
                    <ExternalLinkIcon /> Open in Analyze
                  </Link>
                </Button>
              ) : null}
              {run.review ? (
                <Button variant="outline" asChild>
                  <Link to={`/review?run=${run.id}&status=all`}>
                    <InboxIcon /> Review items ({fmtInt(run.review)})
                  </Link>
                </Button>
              ) : null}
            </>
          ) : null
        }
      />
      {run?.error ? (
        <InlineError>
          <strong>Run failed.</strong> {run.error}
        </InlineError>
      ) : null}
      {!run ? (
        <KpiSkeleton n={6} />
      ) : (
        <KpiGrid
          className="xl:grid-cols-6"
          items={[
            { label: "Status", value: <StatusBadge status={run.status} className="text-sm" /> },
            { label: "Rows", value: fmtInt(run.rows) },
            { label: "Anomalous rows", value: fmtInt(run.n_anomalies), sub: fmtPct(run.anomaly_rate) },
            { label: "Quality", value: run.quality_score === null ? "–" : fmtPct(run.quality_score), sub: run.validity !== null ? `validity ${fmtPct(run.validity)}` : undefined, tone: run.quality_score !== null && run.quality_score < 0.9 ? "alert" : "default" },
            { label: "Fixed / flagged", value: `${fmtInt(run.cells_changed)} / ${fmtInt(run.flagged_for_review)}`, sub: `${fmtInt(run.rows_dropped)} rows dropped` },
            { label: "Alerts", value: fmtInt(run.alerts_sent), tone: run.alerts_sent ? "alert" : "default", sub: run.alerts_sent ? "rules fired" : "none fired" },
          ]}
        />
      )}
      <Tabs value={tab} onValueChange={setTab} className="gap-4">
        <TabsList className="w-full justify-start overflow-x-auto overflow-y-hidden [scrollbar-width:none] sm:w-fit">
          <TabsTrigger value="incidents" className="gap-1.5">
            Incidents
            {incidents.data?.open ? (
              <Badge variant="secondary" className="h-5 rounded-full px-1.5 text-[11px] tabular">
                {incidents.data.open}
              </Badge>
            ) : null}
          </TabsTrigger>
          <TabsTrigger value="findings">Findings{bd ? ` (${fmtInt(bd.findings)})` : ""}</TabsTrigger>
          <TabsTrigger value="details">Remediation &amp; outputs</TabsTrigger>
        </TabsList>
        <TabsContent value="incidents">
          <IncidentList runId={id} focus={focus} onShowColumn={(column) => filterBy({ column, detector: "", severity: "" })} />
        </TabsContent>
        <TabsContent value="findings" className="space-y-6">
          {run && bd ? (
            <>
              <div className="grid gap-6 lg:grid-cols-2">
                <Section title="Findings by column" description={`${fmtInt(bd.findings)} stored findings on ${fmtInt(bd.rows)} rows · select to filter`}>
                  <BarList
                    items={Object.entries(bd.by_column).map(([k, v]) => ({ label: k, value: v, active: filters.column === k, onClick: () => setFilters((f) => ({ ...f, column: f.column === k ? "" : k })) }))}
                    format={fmtInt}
                    empty="No findings stored for this run."
                  />
                </Section>
                <Section title="Findings by detector" description={bd.by_severity ? `high ${fmtInt(bd.by_severity.high ?? 0)} · medium ${fmtInt(bd.by_severity.medium ?? 0)} · low ${fmtInt(bd.by_severity.low ?? 0)}` : undefined}>
                  <BarList
                    items={Object.entries(bd.by_detector).map(([k, v]) => ({ label: k, value: v, active: filters.detector === k, onClick: () => setFilters((f) => ({ ...f, detector: f.detector === k ? "" : k })) }))}
                    format={fmtInt}
                    empty="No findings stored for this run."
                  />
                </Section>
              </div>
              <Section title="Findings" description="Sort by any column header. Feedback adjusts detector thresholds when you tune them in Settings." flush>
                <FindingsTable runId={id} breakdown={bd} filters={filters} onFilters={(p) => setFilters((f) => ({ ...f, ...p }))} />
              </Section>
            </>
          ) : null}
        </TabsContent>
        <TabsContent value="details">{run ? <Details run={run} /> : null}</TabsContent>
      </Tabs>
    </div>
  );
}
