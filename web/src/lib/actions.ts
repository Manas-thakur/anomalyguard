// Long-running actions shared by pages and the command palette: run a pipeline
// as a background job, or create and analyze a sample dataset in one step.

import { toast } from "sonner";

import { api, waitForJob } from "./api";
import { fmtInt, fmtPct } from "./format";
import { refreshAll } from "./queries";
import type { Analysis, Dataset, Job, Pipeline } from "./types";

type Navigate = (to: string) => void;

export async function runPipeline(p: Pick<Pipeline, "id" | "name" | "file">, navigate: Navigate, onUpdate?: (job: Job) => void): Promise<Job | null> {
  const name = p.name || p.file;
  const id = toast.loading(`Running ${name}…`, { description: "You can leave this page; the run continues on the server." });
  try {
    const { job } = await api.post<{ job: Job }>(`/api/pipelines/${p.id}/run`);
    refreshAll();
    const done = await waitForJob(api, job.id, { interval: 700, onUpdate });
    if (done.status === "success") {
      const r = done.result as { run_id: number; metrics: { n_anomalies: number; anomaly_rate: number } };
      toast.success(`${name}: run #${r.run_id} finished`, {
        id,
        description: `${fmtInt(r.metrics.n_anomalies)} anomalous rows (${fmtPct(r.metrics.anomaly_rate)}).`,
        action: { label: "Open run", onClick: () => navigate(`/runs/${r.run_id}`) },
        duration: 9000,
      });
    } else {
      toast.error(`${name} failed`, { id, description: done.error ?? done.status, duration: 12000 });
    }
    refreshAll();
    return done;
  } catch (err) {
    toast.error(`Could not run ${name}`, { id, description: (err as Error).message });
    return null;
  }
}

export const SAMPLE_PRESETS = {
  orders: { label: "Orders", rows: "1,000 rows", hint: "E-commerce orders with price, quantity, delivery and data-entry anomalies" },
  sensor: { label: "Sensor readings", rows: "1,440 rows", hint: "Hourly readings with spikes, a level shift and seasonal drift" },
} as const;

export type SampleKind = keyof typeof SAMPLE_PRESETS;

export async function analyzeSample(kind: SampleKind, navigate: Navigate) {
  const id = toast.loading(`Generating the ${SAMPLE_PRESETS[kind].label.toLowerCase()} sample and analyzing it…`);
  try {
    const meta = await api.post<Dataset>("/api/datasets/sample", { kind });
    const body =
      kind === "orders"
        ? { dataset_id: meta.id, detectors: ["mad", "iforest"], group_by: "region" }
        : { dataset_id: meta.id, detectors: ["mad", "seasonal", "cusum"], time_column: "timestamp" };
    const res = await api.post<{ analysis: Analysis; job: Job }>("/api/analyses", body);
    const job = await waitForJob(api, res.job.id);
    if (job.status !== "success") throw new Error(job.error || `Job ${job.status}`);
    toast.success(`Analyzed ${meta.name}`, { id, duration: 3000 });
    refreshAll();
    navigate(`/analyze/a/${res.analysis.id}`);
  } catch (err) {
    toast.error("Sample analysis failed", { id, description: (err as Error).message });
  }
}
