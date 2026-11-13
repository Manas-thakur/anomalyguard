// Background jobs (analyses and pipeline runs) as a queue in the header.

import { CheckCircle2Icon, CircleDashedIcon, LayersIcon, XCircleIcon } from "lucide-react";
import { Link } from "react-router";

import {
  Queue,
  QueueItem,
  QueueItemContent,
  QueueItemDescription,
  QueueList,
  QueueSection,
  QueueSectionContent,
  QueueSectionLabel,
  QueueSectionTrigger,
} from "@/components/ai-elements/queue";
import { Shimmer } from "@/components/ai-elements/shimmer";
import { TimeAgo } from "@/components/common";
import { Button } from "@/components/ui/button";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { Progress } from "@/components/ui/progress";
import { useJobs } from "@/lib/queries";
import type { Job } from "@/lib/types";

function jobLink(j: Job): string | null {
  const r = j.result as { run_id?: number; analysis_id?: string } | null;
  if (j.kind === "analysis" && (r?.analysis_id || j.params.analysis_id)) return `/analyze/a/${r?.analysis_id ?? j.params.analysis_id}`;
  if (r?.run_id) return `/runs/${r.run_id}`;
  if (j.kind === "pipeline" && j.params.id) return `/pipelines/${j.params.id}`;
  return null;
}

export function JobsMenu() {
  const jobs = useJobs();
  const list = jobs.data ?? [];
  const active = list.filter((j) => j.status === "queued" || j.status === "running");
  const done = list.filter((j) => !(j.status === "queued" || j.status === "running"));

  return (
    <Popover>
      <PopoverTrigger asChild>
        <Button variant="ghost" size="sm" className="relative gap-1.5" aria-label={active.length ? `${active.length} jobs running` : "Background jobs"}>
          <LayersIcon />
          <span className="hidden md:inline">Jobs</span>
          {active.length ? (
            <span className="bg-primary text-primary-foreground absolute -top-0.5 -right-0.5 flex size-4 items-center justify-center rounded-full text-[10px] font-semibold tabular md:static md:size-auto md:px-1.5">
              {active.length}
            </span>
          ) : null}
        </Button>
      </PopoverTrigger>
      <PopoverContent align="end" className="w-[min(92vw,380px)] p-0">
        <Queue className="rounded-md border-0 shadow-none">
          <p className="px-1 pt-1 text-sm font-semibold">Background jobs</p>
          {!list.length ? <p className="text-muted-foreground px-1 pb-2 text-sm">No jobs yet. Analyses and pipeline runs started here appear in this queue.</p> : null}
          {active.length ? (
            <QueueSection>
              <QueueSectionTrigger>
                <QueueSectionLabel count={active.length} label="running" icon={<CircleDashedIcon className="size-4 animate-spin motion-reduce:animate-none" />} />
              </QueueSectionTrigger>
              <QueueSectionContent>
                <QueueList>
                  {active.map((j) => (
                    <QueueItem key={j.id}>
                      <div className="flex items-center gap-2">
                        <Shimmer className="text-sm">{j.label}</Shimmer>
                      </div>
                      <Progress value={Math.max(4, j.progress * 100)} className="h-1" aria-label={`${j.label} progress`} />
                      <QueueItemDescription className="ml-0">{j.message || j.status}</QueueItemDescription>
                    </QueueItem>
                  ))}
                </QueueList>
              </QueueSectionContent>
            </QueueSection>
          ) : null}
          {done.length ? (
            <QueueSection defaultOpen={!active.length}>
              <QueueSectionTrigger>
                <QueueSectionLabel count={done.length} label="finished" icon={<CheckCircle2Icon className="size-4" />} />
              </QueueSectionTrigger>
              <QueueSectionContent>
                <QueueList className="[&_div.max-h-40]:max-h-64">
                  {done.map((j) => {
                    const to = jobLink(j);
                    return (
                      <QueueItem key={j.id}>
                        <div className="flex items-start gap-2">
                          {j.status === "success" ? <CheckCircle2Icon className="text-ok mt-0.5 size-3.5 shrink-0" aria-label="succeeded" /> : <XCircleIcon className="text-sev-high mt-0.5 size-3.5 shrink-0" aria-label={j.status} />}
                          <QueueItemContent className="text-foreground">
                            {to ? (
                              <Link to={to} className="hover:underline">
                                {j.label}
                              </Link>
                            ) : (
                              j.label
                            )}
                          </QueueItemContent>
                          <TimeAgo value={j.finished_at ?? j.created_at} className="text-muted-foreground ml-auto shrink-0 text-xs" />
                        </div>
                        {j.error ? <QueueItemDescription className="text-sev-high ml-5 line-clamp-2">{j.error}</QueueItemDescription> : null}
                      </QueueItem>
                    );
                  })}
                </QueueList>
              </QueueSectionContent>
            </QueueSection>
          ) : null}
        </Queue>
      </PopoverContent>
    </Popover>
  );
}
