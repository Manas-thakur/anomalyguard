// Ctrl/Cmd+K: go to any page, open a run by number, analyze a sample dataset,
// run a pipeline, create a pipeline or switch the theme.

import {
  ActivityIcon,
  FileUpIcon,
  HashIcon,
  InboxIcon,
  KeyboardIcon,
  ListIcon,
  MonitorIcon,
  MoonIcon,
  PlayIcon,
  PlusIcon,
  SettingsIcon,
  SunIcon,
  WorkflowIcon,
} from "lucide-react";
import { useState } from "react";
import { useNavigate } from "react-router";

import { CommandDialog, CommandEmpty, CommandGroup, CommandInput, CommandItem, CommandList, CommandSeparator, CommandShortcut } from "@/components/ui/command";
import { StatusBadge } from "@/components/common";
import { analyzeSample, runPipeline } from "@/lib/actions";
import { fuzzy } from "@/lib/keyboard";
import { runLabel } from "@/lib/format";
import { usePipelines, useRuns } from "@/lib/queries";
import { useTheme } from "@/lib/theme";

const PAGES = [
  { label: "Health", to: "/", icon: ActivityIcon, keys: "G H" },
  { label: "Runs", to: "/runs", icon: ListIcon, keys: "G R" },
  { label: "Review inbox", to: "/review", icon: InboxIcon, keys: "G I" },
  { label: "Analyze a file", to: "/analyze", icon: FileUpIcon, keys: "G A" },
  { label: "Pipelines", to: "/pipelines", icon: WorkflowIcon, keys: "G P" },
  { label: "Settings", to: "/settings", icon: SettingsIcon, keys: "G S" },
];

export function CommandPalette({ open, onOpenChange, onShortcuts }: { open: boolean; onOpenChange: (o: boolean) => void; onShortcuts: () => void }) {
  const navigate = useNavigate();
  const { resolved, setChoice } = useTheme();
  const [search, setSearch] = useState("");
  const pipelines = usePipelines();
  const runs = useRuns({ limit: 8 });
  const runNumber = /^#?\s*(\d+)$/.exec(search.trim())?.[1];

  const run = (fn: () => void) => {
    onOpenChange(false);
    setSearch("");
    fn();
  };

  return (
    <CommandDialog
      open={open}
      onOpenChange={(o) => {
        onOpenChange(o);
        if (!o) setSearch("");
      }}
      title="Command palette"
      description="Jump to a page, open a run, analyze a sample or run a pipeline"
      className="sm:max-w-xl"
      filter={(value, s, keywords) => {
        if (value.startsWith("open-run-number")) return 1;
        const score = fuzzy(s, `${value} ${(keywords ?? []).join(" ")}`);
        return score < 0 ? 0 : 0.01 + Math.min(score, 200) / 200;
      }}
    >
      <CommandInput placeholder="Type a command, a page, or a run number…" value={search} onValueChange={setSearch} />
      <CommandList className="max-h-[min(60vh,420px)]">
        <CommandEmpty>No matching commands. Type a run number to open it.</CommandEmpty>
        {runNumber ? (
          <CommandGroup heading="Runs">
            <CommandItem value={`open-run-number ${runNumber}`} onSelect={() => run(() => navigate(`/runs/${runNumber}`))}>
              <HashIcon /> Open run #{runNumber}
            </CommandItem>
          </CommandGroup>
        ) : null}
        <CommandGroup heading="Go to">
          {PAGES.map((p) => (
            <CommandItem key={p.to} value={`Go to ${p.label}`} onSelect={() => run(() => navigate(p.to))}>
              <p.icon /> {p.label}
              <CommandShortcut>{p.keys}</CommandShortcut>
            </CommandItem>
          ))}
        </CommandGroup>
        <CommandGroup heading="Actions">
          <CommandItem value="Analyze sample dataset: orders" keywords={["1,000 rows", "grouped by region"]} onSelect={() => run(() => analyzeSample("orders", navigate))}>
            <PlayIcon /> Analyze sample dataset: orders
            <span className="text-muted-foreground ml-auto text-xs">1,000 rows, by region</span>
          </CommandItem>
          <CommandItem value="Analyze sample dataset: sensor readings" keywords={["hourly", "seasonal", "level shift"]} onSelect={() => run(() => analyzeSample("sensor", navigate))}>
            <PlayIcon /> Analyze sample dataset: sensor readings
            <span className="text-muted-foreground ml-auto text-xs">hourly, seasonal</span>
          </CommandItem>
          <CommandItem value="Upload a file to analyze" onSelect={() => run(() => navigate("/analyze"))}>
            <FileUpIcon /> Upload a file to analyze
          </CommandItem>
          <CommandItem value="Create a pipeline" keywords={["new", "template"]} onSelect={() => run(() => navigate("/pipelines?new=1"))}>
            <PlusIcon /> Create a pipeline
          </CommandItem>
        </CommandGroup>
        {pipelines.data?.pipelines.length ? (
          <CommandGroup heading="Run a pipeline">
            {pipelines.data.pipelines.map((p) => (
              <CommandItem
                key={p.id}
                value={`Run pipeline: ${p.name || p.file}`}
                keywords={[p.file, p.description ?? ""]}
                disabled={!p.valid}
                onSelect={() => run(() => void runPipeline(p, navigate))}
              >
                <PlayIcon /> Run pipeline: {p.name || p.file}
                {!p.valid ? <StatusBadge status="invalid" className="ml-auto" /> : <span className="text-muted-foreground ml-auto truncate text-xs">{p.file}</span>}
              </CommandItem>
            ))}
          </CommandGroup>
        ) : null}
        {runs.data?.items.length ? (
          <CommandGroup heading="Recent runs">
            {runs.data.items.slice(0, 6).map((r) => (
              <CommandItem key={r.id} value={`Open run #${r.id} ${runLabel(r.pipeline)}`} onSelect={() => run(() => navigate(`/runs/${r.id}`))}>
                <ListIcon /> Run #{r.id} · {runLabel(r.pipeline)}
                <StatusBadge status={r.status} className="ml-auto" />
              </CommandItem>
            ))}
          </CommandGroup>
        ) : null}
        <CommandSeparator />
        <CommandGroup heading="Preferences">
          <CommandItem value={resolved === "dark" ? "Switch to light theme" : "Switch to dark theme"} onSelect={() => run(() => setChoice(resolved === "dark" ? "light" : "dark"))}>
            {resolved === "dark" ? <SunIcon /> : <MoonIcon />} {resolved === "dark" ? "Switch to light theme" : "Switch to dark theme"}
          </CommandItem>
          <CommandItem value="Follow the system theme" onSelect={() => run(() => setChoice("system"))}>
            <MonitorIcon /> Follow the system theme
          </CommandItem>
          <CommandItem value="Keyboard shortcuts help" onSelect={() => run(onShortcuts)}>
            <KeyboardIcon /> Keyboard shortcuts
            <CommandShortcut>?</CommandShortcut>
          </CommandItem>
        </CommandGroup>
      </CommandList>
    </CommandDialog>
  );
}
