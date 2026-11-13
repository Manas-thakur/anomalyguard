// Shared building blocks: page header, KPI strip, empty/error/loading states,
// severity and status badges, relative times and a clickable bar list.

import { AlertTriangleIcon, ChevronRightIcon, RotateCwIcon, type LucideIcon } from "lucide-react";
import { Fragment, useEffect, type ReactNode } from "react";
import { Link } from "react-router";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardAction, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Empty, EmptyContent, EmptyDescription, EmptyHeader, EmptyMedia, EmptyTitle } from "@/components/ui/empty";
import { Skeleton } from "@/components/ui/skeleton";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { fmtAgo, parseTime, titleCase } from "@/lib/format";
import type { Severity } from "@/lib/types";
import { cn } from "@/lib/utils";

export function useTitle(title: string | null | undefined) {
  useEffect(() => {
    document.title = title ? `${title} · AnomalyGuard` : "AnomalyGuard";
  }, [title]);
}

export interface Crumb {
  label: string;
  to?: string;
}

export function PageHeader({
  title,
  description,
  crumbs,
  actions,
  children,
}: {
  title: ReactNode;
  description?: ReactNode;
  crumbs?: Crumb[];
  actions?: ReactNode;
  children?: ReactNode;
}) {
  return (
    <header className="flex flex-col gap-3 pb-1">
      {crumbs?.length ? (
        <nav aria-label="Breadcrumb" className="text-muted-foreground flex min-w-0 flex-wrap items-center gap-1 text-xs">
          {crumbs.map((c, i) => (
            <Fragment key={`${c.label}-${i}`}>
              {i > 0 && <ChevronRightIcon className="size-3 opacity-60" aria-hidden />}
              {c.to ? (
                <Link to={c.to} className="hover:text-foreground truncate rounded-sm underline-offset-4 hover:underline">
                  {c.label}
                </Link>
              ) : (
                <span aria-current="page" className="text-foreground/80 truncate">
                  {c.label}
                </span>
              )}
            </Fragment>
          ))}
        </nav>
      ) : null}
      <div className="flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between">
        <div className="min-w-0 space-y-1">
          <h1 className="text-2xl font-semibold tracking-tight text-balance break-words">{title}</h1>
          {description ? <p className="text-muted-foreground max-w-3xl text-sm text-pretty">{description}</p> : null}
        </div>
        {actions ? <div className="flex shrink-0 flex-wrap items-center gap-2">{actions}</div> : null}
      </div>
      {children}
    </header>
  );
}

export interface Kpi {
  label: string;
  value: ReactNode;
  sub?: ReactNode;
  tone?: "alert" | "ok" | "default";
  icon?: LucideIcon;
}

export function KpiGrid({ items, className }: { items: Kpi[]; className?: string }) {
  return (
    <dl className={cn("grid grid-cols-2 gap-3 md:grid-cols-3 xl:grid-cols-5", items.length === 4 && "xl:grid-cols-4", items.length === 6 && "xl:grid-cols-6", className)}>
      {items.map((k) => (
        <div key={k.label} className="bg-card relative overflow-hidden rounded-xl border px-4 py-3.5 shadow-xs">
          {k.tone === "alert" ? <span aria-hidden className="bg-sev-high absolute inset-y-0 left-0 w-0.5" /> : null}
          <dt className="text-muted-foreground flex items-center gap-1.5 text-xs font-medium">
            {k.icon ? <k.icon className="size-3.5" aria-hidden /> : null}
            {k.label}
          </dt>
          <dd className="mt-1.5 text-2xl font-semibold tracking-tight tabular">{k.value}</dd>
          {k.sub ? <dd className={cn("mt-0.5 truncate text-xs", k.tone === "alert" ? "text-sev-high font-medium" : "text-muted-foreground")}>{k.sub}</dd> : null}
        </div>
      ))}
    </dl>
  );
}

export function KpiSkeleton({ n = 4 }: { n?: number }) {
  return (
    <div className="grid grid-cols-2 gap-3 md:grid-cols-4" aria-hidden>
      {Array.from({ length: n }, (_, i) => (
        <div key={i} className="bg-card rounded-xl border px-4 py-3.5">
          <Skeleton className="h-3 w-20" />
          <Skeleton className="mt-3 h-7 w-16" />
          <Skeleton className="mt-2 h-3 w-24" />
        </div>
      ))}
    </div>
  );
}

export function Section({
  title,
  description,
  actions,
  children,
  flush = false,
  className,
  id,
}: {
  title?: ReactNode;
  description?: ReactNode;
  actions?: ReactNode;
  children: ReactNode;
  flush?: boolean;
  className?: string;
  id?: string;
}) {
  return (
    <Card id={id} className={cn("gap-0 overflow-hidden py-0 shadow-xs", className)}>
      {title || actions ? (
        <CardHeader className="border-b px-4 py-3.5 [.border-b]:pb-3.5">
          {title ? <CardTitle className="text-sm font-semibold">{title}</CardTitle> : null}
          {description ? <CardDescription className="text-xs">{description}</CardDescription> : null}
          {actions ? <CardAction className="flex flex-wrap items-center gap-2">{actions}</CardAction> : null}
        </CardHeader>
      ) : null}
      <CardContent className={cn(flush ? "p-0" : "p-4")}>{children}</CardContent>
    </Card>
  );
}

export function LoadingRows({ rows = 5, className }: { rows?: number; className?: string }) {
  return (
    <div className={cn("space-y-3 p-4", className)} aria-busy="true" aria-label="Loading">
      {Array.from({ length: rows }, (_, i) => (
        <Skeleton key={i} className="h-4" style={{ width: `${90 - ((i * 17) % 45)}%` }} />
      ))}
    </div>
  );
}

export function EmptyState({
  icon: Icon,
  title,
  description,
  children,
  className,
}: {
  icon?: LucideIcon;
  title: string;
  description?: ReactNode;
  children?: ReactNode;
  className?: string;
}) {
  return (
    <Empty className={cn("border-0 py-10", className)}>
      <EmptyHeader>
        {Icon ? (
          <EmptyMedia variant="icon">
            <Icon aria-hidden />
          </EmptyMedia>
        ) : null}
        <EmptyTitle className="text-base">{title}</EmptyTitle>
        {description ? <EmptyDescription>{description}</EmptyDescription> : null}
      </EmptyHeader>
      {children ? <EmptyContent className="flex-row flex-wrap justify-center">{children}</EmptyContent> : null}
    </Empty>
  );
}

export function ErrorState({ error, retry, className }: { error: unknown; retry?: () => void; className?: string }) {
  const message = error instanceof Error ? error.message : String(error);
  const status = (error as { status?: number })?.status;
  return (
    <div role="alert" className={cn("flex flex-col items-center gap-3 px-4 py-10 text-center", className)}>
      <div className="bg-sev-high-soft text-sev-high flex size-10 items-center justify-center rounded-full">
        <AlertTriangleIcon className="size-5" aria-hidden />
      </div>
      <div className="space-y-1">
        <p className="font-medium">{status === 0 || message.includes("fetch") ? "Could not reach the server" : "Something went wrong"}</p>
        <p className="text-muted-foreground max-w-md text-sm break-words">{message}</p>
      </div>
      {retry ? (
        <Button variant="outline" size="sm" onClick={retry}>
          <RotateCwIcon /> Try again
        </Button>
      ) : null}
    </div>
  );
}

const SEV_CLASS: Record<Severity, string> = {
  high: "bg-sev-high-soft text-sev-high border-sev-high/25",
  medium: "bg-sev-medium-soft text-sev-medium border-sev-medium/25",
  low: "bg-sev-low-soft text-sev-low border-sev-low/20",
};

export function SeverityBadge({ severity, children, className }: { severity: Severity; children?: ReactNode; className?: string }) {
  return (
    <Badge variant="outline" className={cn("gap-1.5 rounded-md font-medium", SEV_CLASS[severity] ?? SEV_CLASS.low, className)}>
      <SeverityDot severity={severity} />
      {children ?? titleCase(severity)}
    </Badge>
  );
}

export function SeverityDot({ severity, className }: { severity: Severity; className?: string }) {
  return (
    <span
      aria-hidden
      className={cn(
        "inline-block size-2 shrink-0 rounded-full",
        severity === "high" ? "bg-sev-high" : severity === "medium" ? "bg-sev-medium" : "bg-sev-low",
        className,
      )}
    />
  );
}

const STATUS_CLASS: Record<string, string> = {
  success: "bg-ok-soft text-ok border-ok/25",
  approved: "bg-ok-soft text-ok border-ok/25",
  applied: "bg-accent text-accent-foreground border-primary/20",
  installed: "bg-ok-soft text-ok border-ok/25",
  ok: "bg-ok-soft text-ok border-ok/25",
  failed: "bg-sev-high-soft text-sev-high border-sev-high/25",
  interrupted: "bg-sev-high-soft text-sev-high border-sev-high/25",
  invalid: "bg-sev-high-soft text-sev-high border-sev-high/25",
  rejected: "bg-sev-low-soft text-sev-low border-sev-low/20",
  running: "bg-accent text-accent-foreground border-primary/20",
  queued: "bg-accent text-accent-foreground border-primary/20",
  pending: "bg-sev-medium-soft text-sev-medium border-sev-medium/25",
  empty: "bg-sev-low-soft text-sev-low border-sev-low/20",
  warning: "bg-sev-medium-soft text-sev-medium border-sev-medium/25",
  missing: "bg-sev-medium-soft text-sev-medium border-sev-medium/25",
  error: "bg-sev-high-soft text-sev-high border-sev-high/25",
  critical: "bg-sev-high-soft text-sev-high border-sev-high/25",
  info: "bg-sev-low-soft text-sev-low border-sev-low/20",
};

export function StatusBadge({ status, className, children }: { status: string; className?: string; children?: ReactNode }) {
  return (
    <Badge variant="outline" className={cn("rounded-md font-medium", !children && "capitalize", STATUS_CLASS[status] ?? STATUS_CLASS.info, className)}>
      {children ?? status}
    </Badge>
  );
}

export function TimeAgo({ value, className }: { value: string | null | undefined; className?: string }) {
  const d = parseTime(value);
  if (!d) return <span className={className}>–</span>;
  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <time dateTime={value ?? undefined} className={cn("whitespace-nowrap", className)} tabIndex={0}>
          {fmtAgo(value)}
        </time>
      </TooltipTrigger>
      <TooltipContent>{d.toLocaleString()}</TooltipContent>
    </Tooltip>
  );
}

export interface BarItem {
  label: string;
  value: number;
  active?: boolean;
  onClick?: () => void;
}

/** Horizontal bars with labels; each row can act as a filter toggle. */
export function BarList({ items, format = String, empty = "Nothing to show." }: { items: BarItem[]; format?: (v: number) => string; empty?: string }) {
  if (!items.length) return <p className="text-muted-foreground text-sm">{empty}</p>;
  const max = Math.max(...items.map((i) => i.value), 1);
  return (
    <ul className="space-y-1">
      {items.map((it) => {
        const inner = (
          <>
            <span className="relative z-10 min-w-0 flex-1 truncate font-mono text-xs">{it.label}</span>
            <span className="relative z-10 shrink-0 text-xs font-medium tabular">{format(it.value)}</span>
            <span
              aria-hidden
              className={cn("absolute inset-y-0 left-0 rounded-md transition-[width]", it.active ? "bg-primary/20" : "bg-primary/10")}
              style={{ width: `${Math.max(2, (it.value / max) * 100)}%` }}
            />
          </>
        );
        return (
          <li key={it.label}>
            {it.onClick ? (
              <button
                type="button"
                onClick={it.onClick}
                aria-pressed={it.active}
                className="hover:bg-muted focus-visible:ring-ring/50 relative flex w-full items-center gap-3 rounded-md px-2 py-1.5 text-left outline-none focus-visible:ring-[3px]"
                title={`Filter by ${it.label}`}
              >
                {inner}
              </button>
            ) : (
              <div className="relative flex items-center gap-3 rounded-md px-2 py-1.5">{inner}</div>
            )}
          </li>
        );
      })}
    </ul>
  );
}

export function KeyValue({ items, className }: { items: [ReactNode, ReactNode][]; className?: string }) {
  return (
    <dl className={cn("grid grid-cols-1 gap-x-4 gap-y-1 text-sm sm:grid-cols-[minmax(7rem,auto)_1fr] sm:gap-y-2.5 [&_dd]:mb-1.5 sm:[&_dd]:mb-0", className)}>
      {items.map(([k, v], i) => (
        <Fragment key={i}>
          <dt className="text-muted-foreground">{k}</dt>
          <dd className="min-w-0 break-words">{v}</dd>
        </Fragment>
      ))}
    </dl>
  );
}

export function InlineError({ children }: { children: ReactNode }) {
  return (
    <div role="alert" className="border-sev-high/30 bg-sev-high-soft text-sev-high flex items-start gap-2 rounded-lg border px-3 py-2 text-sm">
      <AlertTriangleIcon className="mt-0.5 size-4 shrink-0" aria-hidden />
      <div className="min-w-0 break-words">{children}</div>
    </div>
  );
}
