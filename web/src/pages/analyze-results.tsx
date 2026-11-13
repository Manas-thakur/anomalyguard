// Analyze, steps 4-5: incidents first, the highlighted data second, and
// Fix & export (per-column remediation, diff, downloads, send to review).

import { AlertTriangleIcon, ExternalLinkIcon, RotateCwIcon } from "lucide-react";
import { Link, useParams } from "react-router";

import { DataGrid, type GridState } from "@/components/analyze/data-grid";
import { FixPanel } from "@/components/analyze/fix-panel";
import { AnalysisProgress, Stepper } from "@/components/analyze/steps";
import { EmptyState, ErrorState, InlineError, KpiGrid, KpiSkeleton, PageHeader, useTitle } from "@/components/common";
import { useUrlState } from "@/components/filters";
import { IncidentList } from "@/components/incidents/incident-list";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { fmtInt, fmtPct } from "@/lib/format";
import { useAnalysis, useRunIncidents } from "@/lib/queries";

export default function AnalyzeResultsPage() {
  const id = useParams().id as string;
  const q = useAnalysis(id);
  const a = q.data;
  const [s, set] = useUrlState({ tab: "incidents", incident: "", offset: 0, limit: 50, column: "", detector: "", severity: "", all: "", sort: "score" });
  const incidents = useRunIncidents(a?.run_id ?? -1, false);
  useTitle(a ? `Analysis of ${a.dataset}` : "Analysis");

  if (q.error) return <ErrorState error={q.error} retry={() => q.refetch()} />;
  const tab = ["data", "fix"].includes(s.tab) ? s.tab : "incidents";
  const links: Record<number, string> = a ? { 1: "/analyze", 2: `/analyze/d/${a.dataset_id}`, 3: `/analyze/d/${a.dataset_id}` } : {};

  if (a && (a.status === "queued" || a.status === "running")) {
    return (
      <div className="space-y-6">
        <PageHeader crumbs={[{ label: "Analyze", to: "/analyze" }, { label: a.dataset }]} title={a.dataset} description="Analysis running. This page updates when it finishes.">
          <Stepper current={3} links={links} />
        </PageHeader>
        <AnalysisProgress job={null} title={`Analyzing ${a.dataset}`} />
      </div>
    );
  }
  if (a?.status === "failed") {
    return (
      <div className="space-y-6">
        <PageHeader crumbs={[{ label: "Analyze", to: "/analyze" }, { label: a.dataset }]} title={a.dataset} />
        <InlineError>{a.error || "The analysis failed."}</InlineError>
        <Button asChild variant="outline">
          <Link to={`/analyze/d/${a.dataset_id}`}>Change options and retry</Link>
        </Button>
      </div>
    );
  }

  const sm = a?.summary;
  const o = a?.options;
  const grid: GridState = { offset: s.offset, limit: s.limit, column: s.column, detector: s.detector, severity: s.severity, all: s.all, sort: s.sort };

  return (
    <div className="animate-fade-in space-y-6">
      <PageHeader
        crumbs={[{ label: "Analyze", to: "/analyze" }, ...(a ? [{ label: a.dataset, to: `/analyze/d/${a.dataset_id}` }] : []), { label: "Results" }]}
        title={a?.dataset ?? "Analysis"}
        description={
          o ? (
            <span className="flex flex-wrap items-center gap-1.5">
              {o.detectors.map((d) => (
                <Badge key={d} variant="secondary" className="rounded-md font-mono text-[11px]">
                  {d}
                </Badge>
              ))}
              <span>
                {o.group_by ? `by ${o.group_by} · ` : ""}sensitivity {o.sensitivity} · combine {o.combine}
              </span>
            </span>
          ) : undefined
        }
        actions={
          a ? (
            <>
              <Button variant="outline" asChild>
                <Link to={`/analyze/d/${a.dataset_id}`}>
                  <RotateCwIcon /> Re-run with other options
                </Link>
              </Button>
              {a.run_id ? (
                <Button variant="outline" asChild>
                  <Link to={`/runs/${a.run_id}`}>
                    <ExternalLinkIcon /> Run #{a.run_id}
                  </Link>
                </Button>
              ) : null}
            </>
          ) : null
        }
      >
        <Stepper current={tab === "fix" ? 5 : 4} links={links} />
      </PageHeader>
      {!sm ? (
        <KpiSkeleton n={5} />
      ) : (
        <KpiGrid
          items={[
            { label: "Rows", value: fmtInt(sm.rows), sub: `${fmtInt(sm.columns)} columns` },
            { label: "Anomalous rows", value: fmtInt(sm.n_anomalies), sub: fmtPct(sm.anomaly_rate), tone: sm.anomaly_rate > 0.05 ? "alert" : "default" },
            { label: "Findings", value: fmtInt(sm.n_findings), sub: "cell and row flags" },
            { label: "High severity", value: fmtInt(a?.breakdown?.by_severity?.high ?? 0), sub: "score at least 3× threshold" },
            { label: "Columns affected", value: fmtInt(Object.keys(sm.anomalies_by_column || {}).filter((c) => c !== "(row)").length) },
          ]}
        />
      )}
      <Tabs value={tab} onValueChange={(v) => set({ tab: v, incident: "" })} className="gap-4">
        <TabsList className="w-full justify-start overflow-x-auto overflow-y-hidden [scrollbar-width:none] sm:w-fit">
          <TabsTrigger value="incidents" className="gap-1.5">
            Incidents
            {incidents.data?.open ? (
              <Badge variant="secondary" className="h-5 rounded-full px-1.5 text-[11px] tabular">
                {incidents.data.open}
              </Badge>
            ) : null}
          </TabsTrigger>
          <TabsTrigger value="data">Data</TabsTrigger>
          <TabsTrigger value="fix">Fix &amp; export</TabsTrigger>
        </TabsList>
        <TabsContent value="incidents">
          {a?.run_id ? (
            <IncidentList runId={a.run_id} focus={s.incident || null} onShowColumn={(column) => set({ tab: "data", column, detector: "", severity: "", offset: 0 })} />
          ) : a ? (
            <EmptyState icon={AlertTriangleIcon} title="No run recorded" />
          ) : null}
        </TabsContent>
        <TabsContent value="data">{a ? <DataGrid analysisId={id} breakdown={a.breakdown ?? { by_column: {}, by_detector: {}, by_severity: {}, findings: 0, rows: 0 }} state={grid} onState={(p) => set(p)} /> : null}</TabsContent>
        <TabsContent value="fix">{a ? <FixPanel analysis={a} /> : null}</TabsContent>
      </Tabs>
    </div>
  );
}
