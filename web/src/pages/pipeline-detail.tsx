// One pipeline: edit and validate its YAML, run it now (with live job
// progress), and see its summary, recent runs and jobs.

import { CheckCircle2Icon, FileSearchIcon, PlayIcon, RotateCcwIcon, SaveIcon, ShieldCheckIcon } from "lucide-react";
import { useState } from "react";
import { Link, useNavigate, useParams } from "react-router";
import { toast } from "sonner";

import { Shimmer } from "@/components/ai-elements/shimmer";
import { EmptyState, ErrorState, InlineError, KeyValue, LoadingRows, PageHeader, Section, StatusBadge, TimeAgo, useTitle } from "@/components/common";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Progress } from "@/components/ui/progress";
import { Spinner } from "@/components/ui/spinner";
import { Textarea } from "@/components/ui/textarea";
import { runPipeline } from "@/lib/actions";
import { api } from "@/lib/api";
import { fmtInt, fmtMs, fmtPct, fmtSchedule } from "@/lib/format";
import { queryClient, usePipeline } from "@/lib/queries";
import type { Job, PipelineDetail } from "@/lib/types";

function Editor({ p }: { p: PipelineDetail }) {
  const [text, setText] = useState(p.yaml);
  const [base, setBase] = useState(p.yaml);
  const [check, setCheck] = useState<{ valid: boolean; error?: string; warnings?: string[] } | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  if (p.yaml !== base) {
    setBase(p.yaml);
    setText(p.yaml);
  }
  const dirty = text !== p.yaml;
  const lines = text.split("\n").length;

  async function validate() {
    setBusy("validate");
    try {
      setCheck(await api.post<{ valid: boolean; error?: string; warnings?: string[] }>("/api/pipelines/validate", { yaml: text }));
    } catch (err) {
      toast.error((err as Error).message);
    } finally {
      setBusy(null);
    }
  }
  async function save() {
    setBusy("save");
    try {
      await api.put(`/api/pipelines/${p.id}`, { yaml: text });
      toast.success(`Saved ${p.file}`);
      setCheck(null);
      queryClient.invalidateQueries({ queryKey: ["pipeline", p.id] });
      queryClient.invalidateQueries({ queryKey: ["pipelines"] });
    } catch (err) {
      setCheck({ valid: false, error: (err as Error).message });
    } finally {
      setBusy(null);
    }
  }

  return (
    <Section
      title="Configuration"
      description={<span className="font-mono">{p.path}</span>}
      actions={dirty ? <Badge variant="outline" className="bg-sev-medium-soft text-sev-medium border-sev-medium/25 rounded-md">Unsaved changes</Badge> : null}
    >
      <div className="space-y-3">
        <div className="bg-muted/30 flex overflow-hidden rounded-lg border focus-within:ring-[3px] focus-within:ring-ring/50">
          <div aria-hidden className="text-muted-foreground/70 bg-muted/50 border-r px-2 py-2 text-right font-mono text-xs leading-5 select-none">
            {Array.from({ length: lines }, (_, i) => (
              <div key={i}>{i + 1}</div>
            ))}
          </div>
          <Textarea
            value={text}
            spellCheck={false}
            aria-label="Pipeline YAML"
            aria-invalid={check && !check.valid ? true : undefined}
            onChange={(e) => {
              setText(e.target.value);
              setCheck(null);
            }}
            onKeyDown={(e) => {
              if (e.key === "Tab" && !e.shiftKey) {
                e.preventDefault();
                const t = e.currentTarget;
                t.setRangeText("  ", t.selectionStart, t.selectionEnd, "end");
                setText(t.value);
              }
              if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "s") {
                e.preventDefault();
                if (dirty) void save();
              }
            }}
            className="min-h-[360px] resize-y rounded-none border-0 bg-transparent font-mono text-xs leading-5 whitespace-pre shadow-none focus-visible:ring-0 dark:bg-transparent"
            style={{ height: `${Math.min(44, Math.max(18, lines + 2)) * 20}px` }}
          />
        </div>
        <div aria-live="polite">
          {check ? (
            check.valid ? (
              <div className="border-ok/30 bg-ok-soft text-ok flex items-start gap-2 rounded-lg border px-3 py-2 text-sm">
                <CheckCircle2Icon className="mt-0.5 size-4 shrink-0" aria-hidden />
                <span>
                  <strong>Valid.</strong> {check.warnings?.length ? `Warnings: ${check.warnings.join("; ")}` : "The config parses and every detector, rule and policy is known."}
                </span>
              </div>
            ) : (
              <InlineError>{check.error}</InlineError>
            )
          ) : null}
        </div>
        <div className="flex flex-wrap gap-2">
          <Button variant="outline" onClick={validate} disabled={busy !== null}>
            {busy === "validate" ? <Spinner /> : <ShieldCheckIcon />} Validate
          </Button>
          <Button onClick={save} disabled={!dirty || busy !== null}>
            {busy === "save" ? <Spinner /> : <SaveIcon />} Save
          </Button>
          <Button
            variant="ghost"
            disabled={!dirty || busy !== null}
            onClick={() => {
              setText(p.yaml);
              setCheck(null);
            }}
          >
            <RotateCcwIcon /> Discard changes
          </Button>
        </div>
      </div>
    </Section>
  );
}

export default function PipelineDetailPage() {
  const id = useParams().id as string;
  const navigate = useNavigate();
  const q = usePipeline(id);
  const p = q.data;
  const [job, setJob] = useState<Job | null>(null);
  const [running, setRunning] = useState(false);
  useTitle(p ? p.name || p.file : "Pipeline");

  if (q.error)
    return (q.error as { status?: number }).status === 404 ? (
      <div className="bg-card mt-6 rounded-xl border">
        <EmptyState icon={FileSearchIcon} title="Pipeline not found" description="The file may have been moved or renamed.">
          <Button variant="outline" asChild>
            <Link to="/pipelines">All pipelines</Link>
          </Button>
        </EmptyState>
      </div>
    ) : (
      <ErrorState error={q.error} retry={() => q.refetch()} />
    );
  if (!p) return <LoadingRows rows={10} />;

  async function run() {
    if (!p) return;
    setRunning(true);
    setJob(null);
    const done = await runPipeline(p, navigate, setJob);
    setRunning(false);
    setJob(done);
    queryClient.invalidateQueries({ queryKey: ["pipeline", id] });
  }

  const runs = p.recent_runs ?? [];
  return (
    <div className="animate-fade-in space-y-6">
      <PageHeader
        crumbs={[{ label: "Pipelines", to: "/pipelines" }, { label: p.file }]}
        title={p.name || p.file}
        description={p.description || p.path}
        actions={
          <Button onClick={run} disabled={!p.valid || running}>
            {running ? <Spinner /> : <PlayIcon />} {running ? "Running…" : "Run now"}
          </Button>
        }
      />
      {!p.valid ? (
        <InlineError>
          <strong>Invalid configuration.</strong> {p.error}
        </InlineError>
      ) : null}
      {running || job ? (
        <div className="bg-card space-y-2 rounded-xl border p-4" aria-live="polite">
          <div className="flex items-center justify-between gap-2 text-sm">
            {running ? <Shimmer className="font-medium">{`Running ${p.name}`}</Shimmer> : <span className="font-medium">{job?.status === "success" ? `Finished ${p.name}` : `${p.name} ${job?.status}`}</span>}
            {job?.status === "success" && (job.result as { run_id?: number })?.run_id ? (
              <Button variant="link" size="sm" className="h-auto p-0" asChild>
                <Link to={`/runs/${(job.result as { run_id: number }).run_id}`}>Open run #{(job.result as { run_id: number }).run_id}</Link>
              </Button>
            ) : null}
          </div>
          <Progress value={Math.max(4, (job?.status === "success" ? 1 : (job?.progress ?? 0.05)) * 100)} className="h-1.5" aria-label="Run progress" />
          {job?.error ? <InlineError>{job.error}</InlineError> : <p className="text-muted-foreground text-xs">{job?.message ?? "Queued"}</p>}
        </div>
      ) : null}
      <div className="grid gap-6 lg:grid-cols-[minmax(0,1fr)_340px]">
        <div className="min-w-0">
          <Editor p={p} />
        </div>
        <div className="space-y-6">
          <Section title="Summary">
            <KeyValue
              items={[
                ["Source", <span className="font-mono text-xs break-all">{p.source || "–"}</span>],
                [
                  "Detectors",
                  <span className="flex flex-wrap gap-1">
                    {(p.detectors ?? []).map((d, i) => (
                      <Badge key={`${d}-${i}`} variant="secondary" className="rounded-md font-mono text-[11px]">
                        {d}
                      </Badge>
                    ))}
                  </span>,
                ],
                ["Remediation", p.remediation ? "on" : "report only"],
                ["Notifiers", (p.notifiers ?? []).join(", ") || "console (default)"],
                [
                  "Schedule",
                  <span>
                    {p.valid ? fmtSchedule(p.interval_seconds) : "–"}
                    <span className="text-muted-foreground block text-xs">
                      Scheduled runs need <code className="font-mono">anomalyguard run {p.file} --schedule</code>
                    </span>
                  </span>,
                ],
                ["Runs", fmtInt(p.runs || 0)],
              ]}
            />
          </Section>
          <Section title="Recent runs" flush>
            {runs.length ? (
              <ul className="divide-y">
                {runs.map((r) => (
                  <li key={r.id}>
                    <Link to={`/runs/${r.id}`} className="hover:bg-muted/50 block space-y-1 px-4 py-2.5 outline-none focus-visible:bg-muted/60">
                      <span className="flex items-center gap-2">
                        <span className="font-mono text-sm font-medium">{r.run_number ? `run ${r.run_number}` : `#${r.id}`}</span>
                        {r.run_number ? <span className="text-muted-foreground font-mono text-xs">#{r.id}</span> : null}
                        <StatusBadge status={r.status} />
                        <TimeAgo value={r.started_at} className="text-muted-foreground ml-auto text-xs" />
                      </span>
                      <span className="text-muted-foreground block text-xs">
                        {fmtInt(r.rows)} rows · {fmtPct(r.anomaly_rate)} anomalous · {fmtMs(r.duration_ms)}
                      </span>
                    </Link>
                  </li>
                ))}
              </ul>
            ) : (
              <EmptyState icon={PlayIcon} title="Never run" description="Run it now, or from the CLI." className="py-6" />
            )}
          </Section>
          {p.jobs?.length ? (
            <Section title="Jobs started here" flush>
              <ul className="divide-y">
                {p.jobs.map((j) => (
                  <li key={j.id} className="space-y-1 px-4 py-2.5">
                    <span className="flex items-center gap-2">
                      <StatusBadge status={j.status} />
                      <TimeAgo value={j.created_at} className="text-muted-foreground text-xs" />
                    </span>
                    {j.error ? (
                      <p className="text-sev-high text-xs">{j.error}</p>
                    ) : (j.result as { run_id?: number })?.run_id ? (
                      <Link className="text-xs hover:underline" to={`/runs/${(j.result as { run_id: number }).run_id}`}>
                        run #{(j.result as { run_id: number }).run_id}
                      </Link>
                    ) : null}
                  </li>
                ))}
              </ul>
            </Section>
          ) : null}
        </div>
      </div>
    </div>
  );
}
