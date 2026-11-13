// Settings: server configuration, API key, detector thresholds (edit, reset,
// tune from feedback), notifiers, optional extras and environment variables.

import { BellIcon, GaugeIcon, KeyRoundIcon, RotateCcwIcon, SaveIcon, ServerIcon, SlidersHorizontalIcon, WandSparklesIcon } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";

import { EmptyState, ErrorState, KeyValue, LoadingRows, PageHeader, Section, StatusBadge, TimeAgo, useTitle } from "@/components/common";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Spinner } from "@/components/ui/spinner";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { api } from "@/lib/api";
import { fmtInt, fmtPct } from "@/lib/format";
import { queryClient, useSettings } from "@/lib/queries";
import type { Precision, Settings, Threshold } from "@/lib/types";

const refresh = () => queryClient.invalidateQueries({ queryKey: ["settings"] });

async function setMultiplier(name: string, value: number) {
  try {
    await api.put(`/api/thresholds/${encodeURIComponent(name)}`, { multiplier: value });
    toast.success(`${name} threshold set to ×${value.toFixed(2)}`);
    refresh();
  } catch (err) {
    toast.error((err as Error).message);
  }
}

function ThresholdRow({ name, t, p }: { name: string; t?: Threshold; p?: Precision }) {
  const [value, setValue] = useState(String(t ? t.multiplier : 1));
  const [busy, setBusy] = useState<string | null>(null);
  return (
    <TableRow>
      <TableCell className="font-mono text-xs">{name}</TableCell>
      <TableCell>
        <div className="flex items-center gap-1.5">
          <Input type="number" step="0.05" min="0.1" max="10" value={value} onChange={(e) => setValue(e.target.value)} aria-label={`Threshold multiplier for ${name}`} className="h-8 w-20 tabular" />
          <Button
            size="sm"
            variant="outline"
            disabled={busy !== null || Number(value) === (t?.multiplier ?? 1)}
            onClick={async () => {
              setBusy("save");
              await setMultiplier(name, Number(value));
              setBusy(null);
            }}
          >
            {busy === "save" ? <Spinner /> : <SaveIcon />} Save
          </Button>
          <Button
            size="sm"
            variant="ghost"
            disabled={!t || busy !== null}
            onClick={async () => {
              setBusy("reset");
              try {
                await api.del(`/api/thresholds/${encodeURIComponent(name)}`);
                toast.success(`${name} back to ×1.00`);
                setValue("1");
                refresh();
              } catch (err) {
                toast.error((err as Error).message);
              } finally {
                setBusy(null);
              }
            }}
          >
            <RotateCcwIcon /> Reset
          </Button>
        </div>
      </TableCell>
      <TableCell className="text-right tabular">{p ? fmtInt(p.true_positive) : "–"}</TableCell>
      <TableCell className="text-right tabular">{p ? fmtInt(p.false_positive) : "–"}</TableCell>
      <TableCell className="text-right tabular">{p && p.precision !== null ? fmtPct(p.precision, 0) : "–"}</TableCell>
      <TableCell className="text-muted-foreground hidden text-xs md:table-cell">
        {t ? (
          <>
            {t.reason || ""} · <TimeAgo value={t.updated_at} />
          </>
        ) : (
          "default"
        )}
      </TableCell>
    </TableRow>
  );
}

function Thresholds({ s }: { s: Settings }) {
  const thr = Object.fromEntries((s.thresholds ?? []).map((t) => [t.detector, t]));
  const prec = s.precision ?? {};
  const names = [...new Set([...Object.keys(thr), ...Object.keys(prec)])].sort();
  const [tuning, setTuning] = useState(false);
  const [name, setName] = useState("");
  const [mult, setMult] = useState("1.2");
  return (
    <Section
      title={
        <span className="flex items-center gap-2">
          <SlidersHorizontalIcon className="text-primary size-4" aria-hidden /> Detector thresholds
        </span>
      }
      description="A multiplier above 1 makes a detector flag less. The next pipeline run and every new analysis apply it."
      actions={
        <Button
          size="sm"
          disabled={tuning}
          onClick={async () => {
            setTuning(true);
            try {
              const r = await api.post<{ changes: { detector: string; old: number; new: number }[] }>("/api/feedback/tune");
              if (r.changes.length) toast.success("Thresholds tuned", { description: r.changes.map((c) => `${c.detector}: ×${c.old.toFixed(2)} → ×${c.new.toFixed(2)}`).join("; "), duration: 9000 });
              else toast("No changes", { description: "Each detector needs at least 3 new reviews, and precision below 80% (or at least 95% to relax).", duration: 9000 });
              refresh();
            } catch (err) {
              toast.error((err as Error).message);
            } finally {
              setTuning(false);
            }
          }}
        >
          {tuning ? <Spinner /> : <WandSparklesIcon />} Tune from feedback
        </Button>
      }
      flush
    >
      {names.length ? (
        <Table>
          <TableHeader className="bg-muted/40">
            <TableRow>
              <TableHead className="text-xs">Detector</TableHead>
              <TableHead className="text-xs">Multiplier</TableHead>
              <TableHead className="text-right text-xs">Confirmed</TableHead>
              <TableHead className="text-right text-xs">False positives</TableHead>
              <TableHead className="text-right text-xs">Precision</TableHead>
              <TableHead className="hidden text-xs md:table-cell">Last change</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {names.map((n) => (
              <ThresholdRow key={`${n}-${thr[n]?.multiplier ?? 1}`} name={n} t={thr[n]} p={prec[n]} />
            ))}
          </TableBody>
        </Table>
      ) : (
        <EmptyState icon={GaugeIcon} title="No feedback or overrides yet" description="Mark findings as false positives on a run or in the review inbox, then tune here." className="py-8" />
      )}
      <form
        className="flex flex-wrap items-center gap-2 border-t px-4 py-3"
        onSubmit={async (e) => {
          e.preventDefault();
          if (!name.trim()) return;
          await setMultiplier(name.trim(), Number(mult));
          setName("");
        }}
      >
        <span className="text-muted-foreground text-sm">Override a detector:</span>
        <Input value={name} onChange={(e) => setName(e.target.value)} placeholder="detector, e.g. mad" aria-label="Detector name" className="h-8 w-48 font-mono" />
        <Input type="number" step="0.05" min="0.1" max="10" value={mult} onChange={(e) => setMult(e.target.value)} aria-label="Multiplier" className="h-8 w-20 tabular" />
        <Button size="sm" variant="outline" type="submit" disabled={!name.trim()}>
          Set
        </Button>
      </form>
    </Section>
  );
}

const EXTRA_HELP: Record<string, string> = { server: "web app and REST API", parquet: "Parquet sources, sinks and uploads", sql: "PostgreSQL, MySQL and other SQLAlchemy databases" };

export default function SettingsPage() {
  useTitle("Settings");
  const q = useSettings();
  const s = q.data;
  const [hasKey, setHasKey] = useState(api.hasKey);

  return (
    <div className="animate-fade-in space-y-6">
      <PageHeader title="Settings" description="Server configuration, detector thresholds and notifier status. Configuration is read from environment variables at start-up." />
      {q.error ? (
        <ErrorState error={q.error} retry={() => q.refetch()} />
      ) : !s ? (
        <LoadingRows rows={10} />
      ) : (
        <>
          <div className="grid gap-6 lg:grid-cols-2">
            <Section
              title={
                <span className="flex items-center gap-2">
                  <ServerIcon className="text-primary size-4" aria-hidden /> Server
                </span>
              }
            >
              <KeyValue
                items={[
                  ["Version", <span className="font-mono">{s.version}</span>],
                  ["State directory", <span className="font-mono text-xs break-all">{s.state.state_dir}</span>],
                  ["Database", <span className="font-mono text-xs break-all">{s.state.db}</span>],
                  ["Working directory", <span className="font-mono text-xs break-all">{s.cwd}</span>],
                  ["Uploads", `${fmtInt(s.state.uploads)} datasets, limit ${s.server.max_upload_mb} MB per file`],
                  ["Pipeline folders", <span className="font-mono text-xs">{s.server.pipeline_dirs.join(", ")}</span>],
                  ["Job workers", String(s.server.workers)],
                  ["CORS origins", s.server.cors_origins.length ? s.server.cors_origins.join(", ") : "same origin only"],
                ]}
              />
            </Section>
            <Section
              title={
                <span className="flex items-center gap-2">
                  <KeyRoundIcon className="text-primary size-4" aria-hidden /> API key
                </span>
              }
            >
              <div className="space-y-3 text-sm">
                {s.server.auth_enabled ? <StatusBadge status="applied">required</StatusBadge> : <StatusBadge status="info">not required</StatusBadge>}
                <p className="text-muted-foreground">
                  {s.server.auth_enabled
                    ? "Every /api request must send the key in the X-API-Key header (or Authorization: Bearer). The browser asks once and keeps it in local storage."
                    : "Anyone who can reach this server can use the API. Set ANOMALYGUARD_API_KEY before exposing it beyond localhost."}
                </p>
                {s.server.auth_enabled ? (
                  <Button
                    variant="outline"
                    size="sm"
                    disabled={!hasKey}
                    onClick={() => {
                      api.setKey("");
                      setHasKey(false);
                      toast("Key removed from this browser", { description: "You will be asked again on the next request." });
                    }}
                  >
                    Forget the key in this browser
                  </Button>
                ) : null}
              </div>
            </Section>
          </div>
          <Thresholds s={s} />
          <div className="grid gap-6 lg:grid-cols-2">
            <Section
              title={
                <span className="flex items-center gap-2">
                  <BellIcon className="text-primary size-4" aria-hidden /> Notifiers
                </span>
              }
              description="Alert channels configured in the pipelines found on disk"
              flush
            >
              {(() => {
                const items = s.notifiers.flatMap((p) => [
                  ...(p.notifiers ?? []).map((n) => ({ ...n, pipeline: p.pipeline })),
                  ...(p.error ? [{ pipeline: p.pipeline, type: "config", ok: false, detail: p.error, min_severity: undefined }] : []),
                ]);
                if (!items.length) return <EmptyState icon={BellIcon} title="No notifiers" description="Add alerts.notifiers to a pipeline (console, file, webhook, slack, email)." className="py-8" />;
                return (
                  <ul className="divide-y">
                    {items.map((n, i) => (
                      <li key={i} className="flex items-start gap-3 px-4 py-2.5">
                        <div className="min-w-0 flex-1 space-y-0.5">
                          <div className="flex flex-wrap items-center gap-2">
                            <StatusBadge status={n.ok ? "ok" : "warning"}>{n.ok ? "ok" : "check"}</StatusBadge>
                            <span className="text-sm font-medium">{n.type}</span>
                            <span className="text-muted-foreground text-xs">{n.pipeline}</span>
                          </div>
                          {n.detail ? <p className="text-muted-foreground font-mono text-xs break-all">{n.detail}</p> : null}
                        </div>
                        {n.min_severity ? <span className="text-muted-foreground shrink-0 text-xs">≥ {n.min_severity}</span> : null}
                      </li>
                    ))}
                  </ul>
                );
              })()}
            </Section>
            <Section title="Optional extras" flush>
              <ul className="divide-y">
                {Object.entries(s.extras).map(([name, e]) => (
                  <li key={name} className="flex flex-wrap items-center gap-3 px-4 py-2.5">
                    <div className="min-w-0 flex-1">
                      <p className="font-mono text-sm font-medium">{name}</p>
                      <p className="text-muted-foreground text-xs">{EXTRA_HELP[name] ?? ""}</p>
                    </div>
                    {e.installed ? (
                      <StatusBadge status="installed" />
                    ) : (
                      <span className="flex items-center gap-2">
                        <StatusBadge status="missing" />
                        <code className="bg-muted rounded px-1.5 py-0.5 font-mono text-xs">pip install "anomalyguard[{name}]"</code>
                      </span>
                    )}
                  </li>
                ))}
              </ul>
            </Section>
          </div>
          <Section title="Environment variables" description="Secret values are never shown, only whether they are set." flush>
            <Table>
              <TableHeader className="bg-muted/40">
                <TableRow>
                  <TableHead className="text-xs">Variable</TableHead>
                  <TableHead className="text-xs">Status</TableHead>
                  <TableHead className="hidden text-xs sm:table-cell">Used for</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {s.env.map((e) => (
                  <TableRow key={e.name}>
                    <TableCell className="font-mono text-xs">{e.name}</TableCell>
                    <TableCell>{e.set ? e.value ? <span className="font-mono text-xs">{e.value}</span> : <StatusBadge status="ok">set</StatusBadge> : <Badge variant="outline" className="text-muted-foreground rounded-md">not set</Badge>}</TableCell>
                    <TableCell className="text-muted-foreground hidden text-sm sm:table-cell">{e.purpose}</TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </Section>
        </>
      )}
    </div>
  );
}
