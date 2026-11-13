// Analyze, step 1: drop a file (or start from a sample) and see earlier uploads.

import type { ColumnDef } from "@tanstack/react-table";
import { ActivityIcon, DatabaseIcon, FileSpreadsheetIcon, ShoppingCartIcon, Trash2Icon, UploadCloudIcon } from "lucide-react";
import { useRef, useState } from "react";
import { Link, useNavigate } from "react-router";
import { toast } from "sonner";

import { Stepper } from "@/components/analyze/steps";
import { EmptyState, ErrorState, InlineError, PageHeader, Section, TimeAgo, useTitle } from "@/components/common";
import { DataTable } from "@/components/data-table";
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
  AlertDialogTrigger,
} from "@/components/ui/alert-dialog";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Progress } from "@/components/ui/progress";
import { Spinner } from "@/components/ui/spinner";
import { analyzeSample, SAMPLE_PRESETS, type SampleKind } from "@/lib/actions";
import { api } from "@/lib/api";
import { fmtBytes, fmtInt } from "@/lib/format";
import { refreshAll, useAnalyses, useDatasets } from "@/lib/queries";
import type { Analysis, Dataset } from "@/lib/types";
import { cn } from "@/lib/utils";

const ACCEPT = ".csv,.tsv,.json,.jsonl,.ndjson,.parquet,.pq,.gz";
const FORMATS = ["CSV", "TSV", "JSON", "JSONL", "Parquet", ".gz"];

function DeleteDataset({ d }: { d: Dataset }) {
  const [busy, setBusy] = useState(false);
  return (
    <AlertDialog>
      <AlertDialogTrigger asChild>
        <Button variant="ghost" size="icon" className="size-8" aria-label={`Delete ${d.name}`}>
          <Trash2Icon />
        </Button>
      </AlertDialogTrigger>
      <AlertDialogContent>
        <AlertDialogHeader>
          <AlertDialogTitle>Delete {d.name}?</AlertDialogTitle>
          <AlertDialogDescription>
            The uploaded file and its analyses are removed from the state directory. Runs already recorded stay in the history. This cannot be undone.
          </AlertDialogDescription>
        </AlertDialogHeader>
        <AlertDialogFooter>
          <AlertDialogCancel>Cancel</AlertDialogCancel>
          <AlertDialogAction
            className="bg-destructive hover:bg-destructive/90 text-white"
            disabled={busy}
            onClick={async (e) => {
              e.preventDefault();
              setBusy(true);
              try {
                await api.del(`/api/datasets/${d.id}`);
                toast.success(`Deleted ${d.name}`);
                refreshAll();
              } catch (err) {
                toast.error((err as Error).message);
              } finally {
                setBusy(false);
              }
            }}
          >
            {busy ? <Spinner /> : null} Delete
          </AlertDialogAction>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  );
}

export default function AnalyzeUploadPage() {
  useTitle("Analyze");
  const navigate = useNavigate();
  const input = useRef<HTMLInputElement>(null);
  const [over, setOver] = useState(false);
  const [upload, setUpload] = useState<{ name: string; size: number; progress: number; error?: string } | null>(null);
  const [sampling, setSampling] = useState<SampleKind | null>(null);
  const datasets = useDatasets();
  const analyses = useAnalyses();

  async function start(file: File) {
    setUpload({ name: file.name, size: file.size, progress: 0 });
    try {
      const meta = await api.upload<Dataset>("/api/datasets", file, (f) => setUpload((u) => (u ? { ...u, progress: f } : u)));
      refreshAll();
      navigate(`/analyze/d/${meta.id}`);
    } catch (err) {
      setUpload((u) => (u ? { ...u, error: (err as Error).message } : u));
    } finally {
      if (input.current) input.current.value = "";
    }
  }

  async function sample(kind: SampleKind) {
    setSampling(kind);
    await analyzeSample(kind, navigate);
    setSampling(null);
  }

  const latest: Record<string, Analysis> = {};
  for (const a of analyses.data ?? []) if (!latest[a.dataset_id]) latest[a.dataset_id] = a;

  const columns: ColumnDef<Dataset, unknown>[] = [
    {
      id: "name",
      header: "File",
      cell: ({ row: { original: d } }) => (
        <Link to={`/analyze/d/${d.id}`} className="flex items-center gap-2 font-medium hover:underline">
          <FileSpreadsheetIcon className="text-muted-foreground size-4 shrink-0" aria-hidden />
          <span className="truncate">{d.name}</span>
        </Link>
      ),
    },
    { id: "rows", header: "Rows", meta: { align: "right" }, cell: ({ row }) => fmtInt(row.original.rows) },
    { id: "cols", header: "Columns", meta: { align: "right", hideBelow: "sm" }, cell: ({ row }) => fmtInt(row.original.columns.length) },
    { id: "size", header: "Size", meta: { align: "right", hideBelow: "md" }, cell: ({ row }) => <span className="text-muted-foreground">{fmtBytes(row.original.size)}</span> },
    { id: "uploaded", header: "Uploaded", meta: { hideBelow: "md" }, cell: ({ row }) => <TimeAgo value={row.original.created_at} className="text-muted-foreground text-sm" /> },
    {
      id: "latest",
      header: "Latest analysis",
      cell: ({ row: { original: d } }) => {
        const a = latest[d.id];
        if (!a) return <span className="text-muted-foreground text-sm">none</span>;
        return (
          <Link to={`/analyze/a/${a.id}`} className="text-primary text-sm font-medium hover:underline">
            {a.summary ? `${fmtInt(a.summary.n_anomalies)} anomalous rows` : a.status}
          </Link>
        );
      },
    },
    { id: "actions", header: () => <span className="sr-only">Actions</span>, meta: { align: "right" }, cell: ({ row }) => <DeleteDataset d={row.original} /> },
  ];

  return (
    <div className="animate-fade-in space-y-6">
      <PageHeader title="Analyze a file" description="Profile a dataset, find anomalies with a reason for each one, preview fixes and export the cleaned file.">
        <Stepper current={1} />
      </PageHeader>

      <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_340px]">
        <div
          role="button"
          tabIndex={0}
          aria-label="Upload a data file: drop it here or press Enter to choose one"
          onClick={() => input.current?.click()}
          onKeyDown={(e) => {
            if (e.key === "Enter" || e.key === " ") {
              e.preventDefault();
              input.current?.click();
            }
          }}
          onDragOver={(e) => {
            e.preventDefault();
            setOver(true);
          }}
          onDragLeave={() => setOver(false)}
          onDrop={(e) => {
            e.preventDefault();
            setOver(false);
            const f = e.dataTransfer.files[0];
            if (f) start(f);
          }}
          className={cn(
            "bg-card group flex min-h-[240px] cursor-pointer flex-col items-center justify-center gap-3 rounded-xl border-2 border-dashed p-8 text-center transition-colors outline-none focus-visible:ring-[3px] focus-visible:ring-ring/50",
            over ? "border-primary bg-accent/60" : "hover:border-primary/50 hover:bg-accent/20",
          )}
        >
          <div className={cn("bg-accent text-primary flex size-12 items-center justify-center rounded-full transition-transform", over && "scale-110")}>
            <UploadCloudIcon className="size-6" aria-hidden />
          </div>
          <div className="space-y-1">
            <p className="text-base font-semibold">{over ? "Release to upload" : "Drop a data file here"}</p>
            <p className="text-muted-foreground max-w-md text-sm">or click to choose one. The file is stored under the server's state directory, profiled, and kept until you delete it.</p>
          </div>
          <div className="flex flex-wrap justify-center gap-1.5">
            {FORMATS.map((f) => (
              <Badge key={f} variant="secondary" className="rounded-md font-mono text-[11px]">
                {f}
              </Badge>
            ))}
          </div>
          <input ref={input} type="file" accept={ACCEPT} hidden onChange={(e) => e.target.files?.[0] && start(e.target.files[0])} />
        </div>
        <div className="space-y-3">
          <p className="text-muted-foreground text-sm">No file handy? Start with a sample that has known anomalies:</p>
          {(Object.keys(SAMPLE_PRESETS) as SampleKind[]).map((k) => {
            const s = SAMPLE_PRESETS[k];
            const Icon = k === "orders" ? ShoppingCartIcon : ActivityIcon;
            return (
              <button
                key={k}
                type="button"
                onClick={() => sample(k)}
                disabled={sampling !== null}
                className="bg-card hover:border-primary/50 hover:bg-accent/30 flex w-full items-start gap-3 rounded-xl border p-3.5 text-left shadow-xs transition-colors outline-none focus-visible:ring-[3px] focus-visible:ring-ring/50 disabled:opacity-60"
              >
                <span className="bg-accent text-primary flex size-9 shrink-0 items-center justify-center rounded-lg">{sampling === k ? <Spinner /> : <Icon className="size-4" aria-hidden />}</span>
                <span className="min-w-0">
                  <span className="block text-sm font-semibold">
                    {s.label} <span className="text-muted-foreground font-normal">· {s.rows}</span>
                  </span>
                  <span className="text-muted-foreground block text-xs">{s.hint}</span>
                </span>
              </button>
            );
          })}
        </div>
      </div>

      {upload ? (
        <div className="bg-card space-y-2 rounded-xl border p-4" aria-live="polite">
          <div className="flex items-center justify-between gap-2 text-sm">
            <span className="truncate font-medium">{upload.name}</span>
            <span className="text-muted-foreground shrink-0">{fmtBytes(upload.size)}</span>
          </div>
          {upload.error ? (
            <InlineError>
              <strong>Upload failed.</strong> {upload.error}
            </InlineError>
          ) : (
            <>
              <Progress value={upload.progress * 100} aria-label="Upload progress" />
              <p className="text-muted-foreground text-xs">{upload.progress < 1 ? `Uploading… ${Math.round(upload.progress * 100)}%` : "Reading and profiling…"}</p>
            </>
          )}
        </div>
      ) : null}

      <Section title="Uploaded datasets" description="Open one to profile it again or run another analysis" flush>
        {datasets.error ? (
          <ErrorState error={datasets.error} retry={() => datasets.refetch()} />
        ) : (
          <DataTable
            caption="Uploaded datasets"
            columns={columns}
            data={datasets.data ?? []}
            loading={datasets.isLoading}
            getRowId={(d) => d.id}
            onRowClick={(d) => navigate(`/analyze/d/${d.id}`)}
            rowLabel={(d) => `${d.name}, ${d.rows} rows`}
            empty={<EmptyState icon={DatabaseIcon} title="No uploads yet" description="Drop a file above, or start with one of the sample datasets to see how detection and fixes work." />}
          />
        )}
      </Section>
    </div>
  );
}
