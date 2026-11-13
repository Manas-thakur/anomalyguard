// The Analyze flow's stepper and the live progress of an analysis job, shown
// as a task list (AI Elements Task pattern) with the running step shimmering.

import { CheckIcon, CircleIcon, ListChecksIcon, XIcon } from "lucide-react";
import { Link } from "react-router";

import { Shimmer } from "@/components/ai-elements/shimmer";
import { Task, TaskContent, TaskItem, TaskTrigger } from "@/components/ai-elements/task";
import { Progress } from "@/components/ui/progress";
import { Spinner } from "@/components/ui/spinner";
import type { Job } from "@/lib/types";
import { cn } from "@/lib/utils";

export const STEP_NAMES = ["Upload", "Profile", "Detect", "Results", "Fix & export"] as const;

export function Stepper({ current, links = {} }: { current: number; links?: Record<number, string> }) {
  return (
    <nav aria-label="Analysis steps" className="overflow-x-auto overflow-y-hidden [scrollbar-width:none]">
      <ol className="flex min-w-max items-center gap-1 text-sm">
        {STEP_NAMES.map((name, i) => {
          const n = i + 1;
          const done = n < current;
          const now = n === current;
          const inner = (
            <>
              <span
                className={cn(
                  "flex size-5 shrink-0 items-center justify-center rounded-full border text-[11px] font-semibold tabular",
                  done && "bg-primary border-primary text-primary-foreground",
                  now && "border-primary text-primary bg-accent",
                  !done && !now && "text-muted-foreground",
                )}
              >
                {done ? <CheckIcon className="size-3" aria-hidden /> : n}
              </span>
              <span className={cn(now ? "text-foreground font-medium" : "text-muted-foreground")}>{name}</span>
            </>
          );
          return (
            <li key={name} className="flex items-center gap-1" aria-current={now ? "step" : undefined}>
              {i > 0 ? <span aria-hidden className={cn("mx-1 h-px w-5 sm:w-8", done || now ? "bg-primary/50" : "bg-border")} /> : null}
              {links[n] && !now ? (
                <Link to={links[n]} className="hover:bg-muted flex items-center gap-2 rounded-md px-1.5 py-1 outline-none focus-visible:ring-[3px] focus-visible:ring-ring/50">
                  {inner}
                </Link>
              ) : (
                <span className="flex items-center gap-2 px-1.5 py-1">{inner}</span>
              )}
            </li>
          );
        })}
      </ol>
    </nav>
  );
}

const JOB_STEPS = [
  { at: 0, label: "Queued" },
  { at: 0.05, label: "Loading data" },
  { at: 0.15, label: "Profiling and validating the schema" },
  { at: 0.3, label: "Running detectors" },
  { at: 0.8, label: "Saving findings and grouping incidents" },
];

/** Live progress of an analysis job. */
export function AnalysisProgress({ job, title }: { job: Job | null; title: string }) {
  const progress = job?.progress ?? 0;
  const failed = job?.status === "failed" || job?.status === "interrupted";
  const finished = job?.status === "success";
  const activeIdx = job?.status === "queued" || !job ? 0 : JOB_STEPS.reduce((acc, s, i) => (progress >= s.at && i > 0 ? i : acc), 1);
  return (
    <div className="bg-card space-y-3 rounded-xl border p-4" aria-live="polite">
      <Task>
        <TaskTrigger title={title}>
          <div className="flex w-full cursor-pointer items-center gap-2 text-sm font-medium">
            <ListChecksIcon className="text-primary size-4" aria-hidden />
            {finished ? title.replace(/^Analyzing/, "Analyzed") : failed ? `${title}: failed` : <Shimmer>{title}</Shimmer>}
          </div>
        </TaskTrigger>
        <TaskContent>
          {JOB_STEPS.slice(1).map((s, k) => {
            const i = k + 1;
            const done = finished || i < activeIdx;
            const now = !finished && i === activeIdx;
            return (
              <TaskItem key={s.label} className="flex items-center gap-2">
                {done ? (
                  <CheckIcon className="text-ok size-3.5" aria-label="done" />
                ) : now && failed ? (
                  <XIcon className="text-sev-high size-3.5" aria-label="failed" />
                ) : now ? (
                  <Spinner className="text-primary size-3.5" aria-label="running" />
                ) : (
                  <CircleIcon className="size-3 opacity-40" aria-label="pending" />
                )}
                <span className={cn(done && "text-foreground", now && !failed && "text-foreground font-medium")}>{s.label}</span>
              </TaskItem>
            );
          })}
        </TaskContent>
      </Task>
      <Progress value={Math.max(3, (finished ? 1 : progress) * 100)} className="h-1.5" aria-label="Analysis progress" />
    </div>
  );
}
