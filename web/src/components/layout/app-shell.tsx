// App shell: grouped sidebar (a Sheet on phones), header with search, jobs and
// theme, the command palette, the shortcuts dialog and global key handling.

import {
  ActivityIcon,
  BookOpenIcon,
  FileUpIcon,
  InboxIcon,
  KeyboardIcon,
  ListIcon,
  MonitorIcon,
  MoonIcon,
  SearchIcon,
  SettingsIcon,
  SunIcon,
  WorkflowIcon,
} from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { Link, useLocation, useNavigate } from "react-router";

import { ApiKeyDialog } from "@/components/layout/api-key-dialog";
import { CommandPalette } from "@/components/layout/command-palette";
import { JobsMenu } from "@/components/layout/jobs-menu";
import { ShortcutsDialog } from "@/components/layout/shortcuts-dialog";
import { MOD, UIContext } from "@/components/layout/ui-context";
import { Button } from "@/components/ui/button";
import { DropdownMenu, DropdownMenuContent, DropdownMenuLabel, DropdownMenuRadioGroup, DropdownMenuRadioItem, DropdownMenuTrigger } from "@/components/ui/dropdown-menu";
import { Kbd } from "@/components/ui/kbd";
import { Separator } from "@/components/ui/separator";
import {
  Sidebar,
  SidebarContent,
  SidebarFooter,
  SidebarGroup,
  SidebarGroupContent,
  SidebarGroupLabel,
  SidebarHeader,
  SidebarInset,
  SidebarMenu,
  SidebarMenuBadge,
  SidebarMenuButton,
  SidebarMenuItem,
  SidebarProvider,
  SidebarRail,
  SidebarTrigger,
  useSidebar,
} from "@/components/ui/sidebar";
import { goSequence, isTypingTarget } from "@/lib/keyboard";
import { fmtInt } from "@/lib/format";
import { useSummary } from "@/lib/queries";
import { useTheme, type ThemeChoice } from "@/lib/theme";

interface NavItem {
  label: string;
  to: string;
  icon: typeof ActivityIcon;
  match?: string[];
  badge?: boolean;
}

const NAV: { label: string; items: NavItem[] }[] = [
  {
    label: "Monitor",
    items: [
      { label: "Health", to: "/", icon: ActivityIcon },
      { label: "Runs", to: "/runs", icon: ListIcon },
    ],
  },
  {
    label: "Triage",
    items: [
      { label: "Review inbox", to: "/review", icon: InboxIcon, badge: true },
      { label: "Analyze a file", to: "/analyze", icon: FileUpIcon },
    ],
  },
  {
    label: "Configure",
    items: [
      { label: "Pipelines", to: "/pipelines", icon: WorkflowIcon },
      { label: "Settings", to: "/settings", icon: SettingsIcon },
    ],
  },
];

export function Logo({ className }: { className?: string }) {
  return (
    <svg viewBox="0 0 24 24" aria-hidden className={className}>
      <rect width="24" height="24" rx="6" fill="var(--primary)" />
      <path d="M5 15.5l3.6-3.6 3 3L19 7.5" fill="none" stroke="var(--primary-foreground)" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round" />
      <circle cx="19" cy="7.5" r="1.9" fill="var(--primary-foreground)" />
    </svg>
  );
}

function ThemeMenu() {
  const { choice, resolved, setChoice } = useTheme();
  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button variant="ghost" size="icon" className="size-8" aria-label={`Theme: ${choice}`}>
          {resolved === "dark" ? <MoonIcon /> : <SunIcon />}
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end" className="w-40">
        <DropdownMenuLabel>Theme</DropdownMenuLabel>
        <DropdownMenuRadioGroup value={choice} onValueChange={(v) => setChoice(v as ThemeChoice)}>
          <DropdownMenuRadioItem value="system">
            <MonitorIcon /> System
          </DropdownMenuRadioItem>
          <DropdownMenuRadioItem value="light">
            <SunIcon /> Light
          </DropdownMenuRadioItem>
          <DropdownMenuRadioItem value="dark">
            <MoonIcon /> Dark
          </DropdownMenuRadioItem>
        </DropdownMenuRadioGroup>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}

function AppSidebar({ onPalette, onShortcuts, version }: { onPalette: () => void; onShortcuts: () => void; version?: string }) {
  const { pathname } = useLocation();
  const summary = useSummary();
  const pending = summary.data?.review.pending ?? 0;
  const { setOpenMobile, isMobile } = useSidebar();

  useEffect(() => {
    if (isMobile) setOpenMobile(false);
  }, [pathname, isMobile, setOpenMobile]);

  return (
    <Sidebar collapsible="icon" aria-label="Main navigation">
      <SidebarHeader className="gap-3 pt-3">
        <Link to="/" className="flex items-center gap-2 rounded-md px-1.5 py-1 outline-none focus-visible:ring-[3px] focus-visible:ring-ring/50 group-data-[collapsible=icon]:px-0">
          <Logo className="size-7 shrink-0" />
          <span className="truncate text-[15px] font-semibold tracking-tight group-data-[collapsible=icon]:hidden">AnomalyGuard</span>
        </Link>
        <button
          type="button"
          onClick={onPalette}
          className="bg-background text-muted-foreground hover:text-foreground hover:border-ring/40 flex h-8 items-center gap-2 rounded-md border px-2 text-sm shadow-xs outline-none focus-visible:ring-[3px] focus-visible:ring-ring/50 group-data-[collapsible=icon]:hidden"
        >
          <SearchIcon className="size-4" aria-hidden />
          <span className="flex-1 text-left">Search or jump to…</span>
          <Kbd>{MOD} K</Kbd>
        </button>
      </SidebarHeader>
      <SidebarContent>
        {NAV.map((group) => (
          <SidebarGroup key={group.label}>
            <SidebarGroupLabel>{group.label}</SidebarGroupLabel>
            <SidebarGroupContent>
              <SidebarMenu>
                {group.items.map((item) => {
                  const active = (item.match ?? [item.to]).some((m) => (m === "/" ? pathname === "/" : pathname === m || pathname.startsWith(`${m}/`)));
                  return (
                    <SidebarMenuItem key={item.to}>
                      <SidebarMenuButton asChild isActive={active} tooltip={item.label}>
                        <Link to={item.to} aria-current={active ? "page" : undefined}>
                          <item.icon />
                          <span>{item.label}</span>
                        </Link>
                      </SidebarMenuButton>
                      {item.badge && pending ? (
                        <SidebarMenuBadge className="bg-primary/10 text-primary rounded-full px-1.5 text-[11px]" aria-label={`${pending} pending`}>
                          {pending > 999 ? "999+" : fmtInt(pending)}
                        </SidebarMenuBadge>
                      ) : null}
                    </SidebarMenuItem>
                  );
                })}
              </SidebarMenu>
            </SidebarGroupContent>
          </SidebarGroup>
        ))}
      </SidebarContent>
      <SidebarFooter>
        <SidebarMenu>
          <SidebarMenuItem>
            <SidebarMenuButton onClick={onShortcuts} tooltip="Keyboard shortcuts">
              <KeyboardIcon />
              <span>Shortcuts</span>
              <Kbd className="ml-auto">?</Kbd>
            </SidebarMenuButton>
          </SidebarMenuItem>
          <SidebarMenuItem>
            <SidebarMenuButton asChild tooltip="API reference">
              <a href="/api/docs" target="_blank" rel="noopener">
                <BookOpenIcon />
                <span>API reference</span>
              </a>
            </SidebarMenuButton>
          </SidebarMenuItem>
        </SidebarMenu>
        <p className="text-muted-foreground px-2 pb-1 text-xs group-data-[collapsible=icon]:hidden">{version ? `AnomalyGuard v${version}` : "AnomalyGuard"}</p>
      </SidebarFooter>
      <SidebarRail />
    </Sidebar>
  );
}

export function AppShell({ children }: { children: ReactNode }) {
  const navigate = useNavigate();
  const [palette, setPalette] = useState(false);
  const [shortcuts, setShortcuts] = useState(false);
  const [version, setVersion] = useState<string>();
  const pendingG = useRef(0);

  useEffect(() => {
    fetch("/health")
      .then((r) => r.json())
      .then((h: { version?: string }) => setVersion(h.version))
      .catch(() => {});
  }, []);

  const openPalette = useCallback(() => setPalette(true), []);
  const openShortcuts = useCallback(() => setShortcuts(true), []);

  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if ((e.metaKey || e.ctrlKey) && !e.altKey && e.key.toLowerCase() === "k") {
        e.preventDefault();
        setPalette((o) => !o);
        return;
      }
      if (e.defaultPrevented || e.metaKey || e.ctrlKey || e.altKey || isTypingTarget(e.target) || document.querySelector("[role=dialog][data-state=open]")) return;
      if (e.key === "?") {
        e.preventDefault();
        setShortcuts(true);
        return;
      }
      if (e.key === "/") {
        const search = document.querySelector<HTMLInputElement>("main input[type=search]");
        if (search) {
          e.preventDefault();
          search.focus();
          search.select();
        }
        return;
      }
      const { pending, to } = goSequence(pendingG.current, e.key, Date.now());
      pendingG.current = pending;
      if (to) {
        e.preventDefault();
        navigate(to);
      }
    }
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [navigate]);

  const ui = useMemo(() => ({ openPalette, openShortcuts }), [openPalette, openShortcuts]);

  return (
    <UIContext.Provider value={ui}>
      <a href="#main" className="bg-primary text-primary-foreground sr-only z-50 rounded-md px-3 py-2 focus:not-sr-only focus:fixed focus:top-2 focus:left-2">
        Skip to content
      </a>
      <SidebarProvider>
        <AppSidebar onPalette={openPalette} onShortcuts={openShortcuts} version={version} />
        <SidebarInset className="min-w-0">
          <header className="bg-background/85 sticky top-0 z-30 flex h-12 items-center gap-2 border-b px-3 backdrop-blur supports-[backdrop-filter]:bg-background/70 md:px-4">
            <SidebarTrigger className="-ml-1" aria-label="Toggle navigation" />
            <Separator orientation="vertical" className="mr-1 data-[orientation=vertical]:h-4" />
            <Link to="/" className="flex items-center gap-2 font-semibold md:hidden">
              <Logo className="size-6" />
              <span className="text-sm">AnomalyGuard</span>
            </Link>
            <div className="ml-auto flex items-center gap-1">
              <Button variant="ghost" size="icon" className="size-8" aria-label="Search and commands" title={`Search and commands (${MOD} K)`} onClick={openPalette}>
                <SearchIcon />
              </Button>
              <JobsMenu />
              <ThemeMenu />
            </div>
          </header>
          <main id="main" tabIndex={-1} className="mx-auto w-full max-w-[1400px] min-w-0 flex-1 px-4 py-6 outline-none md:px-6 lg:px-8">
            {children}
          </main>
        </SidebarInset>
      </SidebarProvider>
      <CommandPalette open={palette} onOpenChange={setPalette} onShortcuts={openShortcuts} />
      <ShortcutsDialog open={shortcuts} onOpenChange={setShortcuts} />
      <ApiKeyDialog />
    </UIContext.Provider>
  );
}
