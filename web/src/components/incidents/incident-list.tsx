// Incidents of one run: open first, triaged after, muted hidden behind a toggle.

import { BellOffIcon, ShieldCheckIcon } from "lucide-react";
import { useMemo, useState } from "react";

import { EmptyState, ErrorState } from "@/components/common";
import { IncidentCard } from "@/components/incidents/incident-card";
import { Skeleton } from "@/components/ui/skeleton";
import { Switch } from "@/components/ui/switch";
import { Label } from "@/components/ui/label";
import { fmtInt } from "@/lib/format";
import { useRunIncidents } from "@/lib/queries";
import type { Incident } from "@/lib/types";

export function IncidentList({ runId, focus, onShowColumn }: { runId: number; focus?: string | null; onShowColumn?: (column: string) => void }) {
  const [showMuted, setShowMuted] = useState(false);
  const q = useRunIncidents(runId, showMuted);
  // local triage updates, so a card does not jump while the list refetches
  const [local, setLocal] = useState<Record<string, Incident>>({});

  const items = useMemo(() => {
    // order by the server's state, so a card triaged here stays where it is
    const rank = (i: Incident) => (i.muted_until ? 2 : i.status === "open" ? 0 : 1);
    const ordered = [...(q.data?.incidents ?? [])].sort((a, b) => rank(a) - rank(b));
    const base = ordered.map((i) => local[i.id] ?? i);
    return showMuted ? base : base.filter((i) => !i.muted_until);
  }, [q.data, local, showMuted]);

  if (q.error) return <ErrorState error={q.error} retry={() => q.refetch()} />;
  if (!q.data)
    return (
      <div className="space-y-3">
        {[0, 1].map((i) => (
          <Skeleton key={i} className="h-64 rounded-xl" />
        ))}
      </div>
    );

  const all = q.data.incidents.map((i) => local[i.id] ?? i);
  const open = all.filter((i) => i.status === "open" && !i.muted_until).length;
  const triaged = all.filter((i) => i.status !== "open" && !i.muted_until).length;
  const mutedCount = showMuted ? all.filter((i) => i.muted_until).length : q.data.muted + Object.values(local).filter((i) => i.muted_until && !q.data.incidents.find((x) => x.id === i.id)?.muted_until).length;

  return (
    <section aria-label="Incidents" className="space-y-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="text-sm" aria-live="polite">
          <strong className="font-semibold">{fmtInt(open)} open</strong>
          <span className="text-muted-foreground">
            {triaged ? ` · ${fmtInt(triaged)} triaged` : ""}
            {mutedCount ? ` · ${fmtInt(mutedCount)} muted` : ""}
          </span>
        </p>
        {mutedCount || showMuted ? (
          <div className="flex items-center gap-2">
            <Switch id={`muted-${runId}`} checked={showMuted} onCheckedChange={setShowMuted} />
            <Label htmlFor={`muted-${runId}`} className="text-sm font-normal">
              Show muted ({fmtInt(mutedCount)})
            </Label>
          </div>
        ) : null}
      </div>
      {!items.length ? (
        <div className="bg-card rounded-xl border">
          {mutedCount ? (
            <EmptyState icon={BellOffIcon} title="Every incident is muted" description="Show muted incidents to review them." />
          ) : (
            <EmptyState icon={ShieldCheckIcon} title="No incidents" description="Nothing in this run needs attention." />
          )}
        </div>
      ) : (
        <div className="space-y-3">
          {items.map((inc) => (
            <IncidentCard
              key={inc.id}
              inc={inc}
              focused={focus === inc.id}
              onShowColumn={onShowColumn}
              onChange={(next) => setLocal((m) => ({ ...m, [next.id]: next }))}
            />
          ))}
        </div>
      )}
    </section>
  );
}
