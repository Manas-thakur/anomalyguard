// Review inbox: keyboard-first split view. The list (server paging and
// filters) is on the left and the open item on the right; on a phone the item
// opens as a bottom sheet. j/k move, a approve, r reject, m mark normal,
// e edit, x select, Shift+click selects a range, and a bulk bar appears while
// items are selected.

import { ArrowRightIcon, CheckIcon, ChevronLeftIcon, ChevronRightIcon, InboxIcon, ThumbsDownIcon, UploadIcon, XIcon } from "lucide-react";
import { useCallback, useEffect, useImperativeHandle, useMemo, useReducer, useRef, useState } from "react";
import { Link } from "react-router";
import { toast } from "sonner";

import {
  Confirmation,
  ConfirmationAction,
  ConfirmationActions,
  ConfirmationBody,
  ConfirmationRequest,
  ConfirmationTitle,
} from "@/components/ai-elements/confirmation";
import { EmptyState, ErrorState, LoadingRows, PageHeader, SeverityBadge, StatusBadge, TimeAgo, useTitle } from "@/components/common";
import { FilterSelect, SearchInput, useUrlState } from "@/components/filters";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { Field, FieldDescription, FieldLabel } from "@/components/ui/field";
import { Input } from "@/components/ui/input";
import { Kbd } from "@/components/ui/kbd";
import { ResizableHandle, ResizablePanel, ResizablePanelGroup } from "@/components/ui/resizable";
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle } from "@/components/ui/sheet";
import { Spinner } from "@/components/ui/spinner";
import { Table, TableBody, TableCell, TableRow } from "@/components/ui/table";
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group";
import { useIsMobile } from "@/hooks/use-mobile";
import { api } from "@/lib/api";
import { fmtInt, fmtNum, fmtValue, parseTyped, runLabel } from "@/lib/format";
import { inboxCommand, inboxReducer, initialInbox, isSelected, isTypingTarget, selectionCount } from "@/lib/keyboard";
import { queryClient, useReview, useReviewFacets, useReviewItem } from "@/lib/queries";
import type { BulkResult, ReviewItem } from "@/lib/types";
import { cn } from "@/lib/utils";

const STATUSES = ["pending", "approved", "applied", "rejected", "all"] as const;
const VERB: Record<string, string> = { approve: "Approved", reject: "Rejected", false_positive: "Marked normal", apply: "Applied" };
const show = (v: unknown) => (v === null || v === undefined ? "null" : fmtValue(v));

function invalidateReview() {
  queryClient.invalidateQueries({ queryKey: ["review"] });
  queryClient.invalidateQueries({ queryKey: ["summary"] });
  queryClient.invalidateQueries({ queryKey: ["health"] });
}

function KeysHint() {
  return (
    <dl className="text-muted-foreground grid grid-cols-[auto_1fr] items-center gap-x-3 gap-y-1.5 text-xs">
      {[
        ["j k", "move"],
        ["a", "approve"],
        ["r", "reject"],
        ["m", "mark normal"],
        ["e", "edit value"],
        ["x", "select"],
      ].map(([k, v]) => (
        <div key={k} className="contents">
          <dt className="flex gap-1">
            {k.split(" ").map((x) => (
              <Kbd key={x}>{x}</Kbd>
            ))}
          </dt>
          <dd>{v}</dd>
        </div>
      ))}
    </dl>
  );
}

interface DetailHandle {
  focusEdit: () => void;
  value: () => unknown;
  note: () => string | null;
}

function ItemDetail({
  id,
  fallback,
  onAction,
  ref,
  busy,
}: {
  id: number;
  fallback: ReviewItem | undefined;
  onAction: (action: "approve" | "reject" | "false_positive" | "apply") => void;
  ref: React.Ref<DetailHandle>;
  busy: string | null;
}) {
  const q = useReviewItem(id);
  const it = q.data?.item ?? fallback;
  const pending = it?.status === "pending";
  const initial = it ? (pending ? (it.suggestion ?? it.value) : it.resolved_value) : null;
  const [value, setValue] = useState<string>(initial === null || initial === undefined ? "" : String(initial));
  const [note, setNote] = useState("");
  const inputRef = useRef<HTMLInputElement>(null);
  const [seenId, setSeenId] = useState(id);
  const [seenInitial, setSeenInitial] = useState(initial);
  if (seenId !== id || seenInitial !== initial) {
    setSeenId(id);
    setSeenInitial(initial);
    setValue(initial === null || initial === undefined ? "" : String(initial));
    setNote("");
  }

  useImperativeHandle(
    ref,
    () => ({
      focusEdit: () => {
        inputRef.current?.focus();
        inputRef.current?.select();
      },
      value: () => parseTyped(value),
      note: () => note.trim() || null,
    }),
    [value, note],
  );

  if (q.error) return <ErrorState error={q.error} retry={() => q.refetch()} />;
  if (!it) return <LoadingRows rows={6} />;
  const data = q.data;

  return (
    <div className="space-y-5 p-4 sm:p-5">
      <header className="space-y-1.5">
        <div className="text-muted-foreground flex flex-wrap items-center gap-2 text-xs">
          <StatusBadge status={it.status} />
          {it.detector ? <span className="font-mono">{it.detector}</span> : null}
          <span>·</span>
          <TimeAgo value={it.created_at} />
        </div>
        <h2 className="font-mono text-lg font-semibold break-all">
          {it.column || "whole row"}
          <span className="text-muted-foreground font-normal"> · row {String(it.row_index ?? "–")}</span>
        </h2>
        <p className="text-muted-foreground text-sm">
          {it.run_id ? (
            <Link to={`/runs/${it.run_id}`} className="hover:text-foreground underline-offset-4 hover:underline">
              {runLabel(it.pipeline)} · run #{it.run_id}
            </Link>
          ) : (
            runLabel(it.pipeline)
          )}
        </p>
      </header>

      {!it.column ? (
        <div className="bg-muted/40 rounded-lg border p-3 text-sm">
          <p className="font-medium">Unusual combination of values</p>
          <p className="text-muted-foreground text-xs">A multivariate detector flagged the whole row. Approve or reject records the decision; mark as normal teaches the detector.</p>
        </div>
      ) : (
      <div className="grid grid-cols-[1fr_auto_1fr] items-center gap-3 rounded-lg border p-3">
        <div className="min-w-0">
          <p className="text-muted-foreground text-xs">Current value</p>
          <p className="text-sev-high truncate font-mono text-xl font-semibold" title={show(it.value)}>
            {show(it.value)}
          </p>
        </div>
        <ArrowRightIcon className="text-muted-foreground size-4" aria-hidden />
        <div className="min-w-0">
          <p className="text-muted-foreground text-xs">{pending ? "Suggested" : "Final"}</p>
          {pending && (it.suggestion === null || it.suggestion === undefined) ? (
            <p className="text-muted-foreground text-sm">No suggestion</p>
          ) : (
            <p className="text-ok truncate font-mono text-xl font-semibold">{show(pending ? it.suggestion : it.resolved_value)}</p>
          )}
          {pending && it.suggestion_confidence ? <p className="text-muted-foreground text-xs">confidence {fmtNum(it.suggestion_confidence, 2)}</p> : null}
        </div>
      </div>
      )}

      <p className="text-sm">{it.reason}</p>

      {it.column ? (
        <Field>
          <FieldLabel htmlFor="final-value" className="flex items-center gap-2">
            Final value <Kbd>e</Kbd>
          </FieldLabel>
          <Input
            ref={inputRef}
            id="final-value"
            className="font-mono"
            value={value}
            disabled={!pending}
            onChange={(e) => setValue(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && pending) {
                e.preventDefault();
                onAction("approve");
              }
              if (e.key === "Escape") {
                e.preventDefault();
                (e.target as HTMLInputElement).blur();
                document.getElementById("inbox-list")?.focus({ preventScroll: true });
              }
            }}
            aria-describedby="final-hint"
          />
          <FieldDescription id="final-hint" className="text-xs">
            {pending ? "Approve writes this value. Numbers are stored as numbers; leave empty for null. Enter approves." : it.reviewer_note ? `Note: ${it.reviewer_note}` : "Already resolved."}
          </FieldDescription>
        </Field>
      ) : null}
      {pending ? <Input placeholder="Optional note" aria-label="Reviewer note" value={note} onChange={(e) => setNote(e.target.value)} className="h-8 text-sm" /> : null}

      {pending ? (
        <div className="flex flex-wrap gap-2">
          <Button onClick={() => onAction("approve")} disabled={busy !== null}>
            {busy === "approve" ? <Spinner /> : <CheckIcon />} Approve <Kbd className="bg-primary-foreground/20 text-primary-foreground">a</Kbd>
          </Button>
          <Button variant="outline" onClick={() => onAction("reject")} disabled={busy !== null}>
            {busy === "reject" ? <Spinner /> : <XIcon />} Reject <Kbd>r</Kbd>
          </Button>
          <Button variant="outline" onClick={() => onAction("false_positive")} disabled={busy !== null}>
            {busy === "false_positive" ? <Spinner /> : <ThumbsDownIcon />} Mark normal <Kbd>m</Kbd>
          </Button>
        </div>
      ) : it.status === "approved" ? (
        <Button onClick={() => onAction("apply")} disabled={busy !== null}>
          {busy === "apply" ? <Spinner /> : <UploadIcon />} Apply to cleaned data
        </Button>
      ) : null}

      {data?.findings.length ? (
        <section className="space-y-2">
          <h3 className="text-muted-foreground text-xs font-medium tracking-wide uppercase">Findings on this row</h3>
          <ul className="divide-y rounded-lg border">
            {data.findings.map((f) => (
              <li key={f.id} className="space-y-1 px-3 py-2">
                <div className="flex flex-wrap items-center gap-2">
                  <SeverityBadge severity={f.severity} />
                  <span className="font-mono text-xs">{f.column || "(row)"}</span>
                  <span className="text-muted-foreground font-mono text-xs">{f.detector}</span>
                </div>
                <p className="text-sm">{f.reason}</p>
              </li>
            ))}
          </ul>
        </section>
      ) : null}

      {data?.row ? (
        <details className="group" open>
          <summary className="text-muted-foreground hover:text-foreground cursor-pointer text-xs font-medium tracking-wide uppercase select-none">Full row</summary>
          <div className="mt-2 rounded-lg border">
            <Table>
              <TableBody>
                {Object.entries(data.row).map(([k, v]) => (
                  <TableRow key={k} className={cn(k === it.column && "bg-sev-high-soft/60 hover:bg-sev-high-soft/60")}>
                    <TableCell className="text-muted-foreground w-1/3 font-mono text-xs">{k}</TableCell>
                    <TableCell className={cn("font-mono text-xs", k === it.column && "text-sev-high font-semibold")}>{show(v)}</TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>
        </details>
      ) : null}
    </div>
  );
}

export default function ReviewPage() {
  useTitle("Review inbox");
  const isMobile = useIsMobile();
  const [s, set] = useUrlState({ status: "pending", pipeline: "", column: "", detector: "", run: "", q: "", offset: 0, limit: 50 });
  const filters = useMemo(() => ({ status: s.status, pipeline: s.pipeline, column: s.column, detector: s.detector, run_id: s.run || undefined, q: s.q }), [s.status, s.pipeline, s.column, s.detector, s.run, s.q]);
  const list = useReview({ ...filters, offset: s.offset, limit: s.limit });
  const facets = useReviewFacets(s.status);
  const [st, dispatch] = useReducer(inboxReducer, initialInbox);
  const [sheetOpen, setSheetOpen] = useState(false);
  const [busy, setBusy] = useState<string | null>(null);
  const [confirmApply, setConfirmApply] = useState(false);
  const detail = useRef<DetailHandle | null>(null);
  const listRef = useRef<HTMLUListElement>(null);
  // where the cursor lands after a page change: first or last item
  const [want, setWant] = useState<"first" | "last" | null>(null);
  const items = useMemo(() => list.data?.items ?? [], [list.data]);
  const total = list.data?.total ?? 0;

  // sync the reducer with the page the server returned
  const idsKey = items.map((i) => i.id).join(",");
  const [seenKey, setSeenKey] = useState<string | null>(null);
  if (list.data && idsKey !== seenKey) {
    setSeenKey(idsKey);
    const ids = items.map((i) => i.id);
    dispatch({ type: "load", ids, keepActive: want === null && seenKey !== null, preferFirst: !isMobile || want !== null });
    if (want === "last" && ids.length) dispatch({ type: "open", index: ids.length - 1 });
    if (want !== null) setWant(null);
  }

  const activeItem = st.active >= 0 ? items[st.active] : undefined;
  const nSelected = selectionCount(st, total);
  const isPendingView = s.status === "pending" || s.status === "all";

  const setFilter = useCallback(
    (patch: Partial<typeof s>) => {
      dispatch({ type: "clear" });
      setWant("first");
      set({ ...patch, offset: 0 });
    },
    [set],
  );

  const page = useCallback(
    (dir: 1 | -1, land: "first" | "last" = "first") => {
      const next = s.offset + dir * s.limit;
      if (next < 0 || next >= total) return false;
      setWant(land);
      if (!st.allMatching) dispatch({ type: "clear" });
      set({ offset: next });
      return true;
    },
    [s.offset, s.limit, total, st.allMatching, set],
  );

  useEffect(() => {
    if (!activeItem) return;
    document.getElementById(`ri-${activeItem.id}`)?.scrollIntoView({ block: "nearest" });
  }, [activeItem]);

  async function single(action: "approve" | "reject" | "false_positive" | "apply") {
    const it = activeItem;
    if (!it || busy) return;
    if (action !== "apply" && it.status !== "pending") {
      toast(`#${it.id} is already ${it.status}.`);
      return;
    }
    setBusy(action);
    try {
      if (action === "approve") await api.post(`/api/review/${it.id}/approve`, { value: it.column ? (detail.current?.value() ?? it.suggestion ?? it.value) : null, note: detail.current?.note() ?? null });
      else if (action === "reject") await api.post(`/api/review/${it.id}/reject`, { note: detail.current?.note() ?? null });
      else if (action === "false_positive") {
        const r = await api.post<{ feedback: number[] }>(`/api/review/${it.id}/false-positive`, { note: detail.current?.note() ?? null });
        if (!r.feedback.length) toast(`${it.detector || "This check"} is not a tunable detector, so no feedback was recorded.`);
      } else {
        const r = await api.post<BulkResult>("/api/review/bulk", { action: "apply", ids: [it.id] });
        toast(r.applied ? `Wrote #${it.id} into the cleaned file.` : "This item's run has no cleaned file to write to.");
      }
      if (action !== "apply") toast.success(`${VERB[action]} #${it.id}`, { duration: 2500 });
      if (s.status === "pending" && action !== "apply") dispatch({ type: "remove", id: it.id });
      if (isMobile) setSheetOpen(false);
      invalidateReview();
    } catch (err) {
      toast.error((err as Error).message);
    } finally {
      setBusy(null);
    }
  }

  async function bulk(action: "approve" | "reject" | "false_positive" | "apply") {
    const body: Record<string, unknown> = { action };
    if (st.allMatching) {
      body.all_matching = true;
      body.filter = filters;
    } else body.ids = st.selected;
    setBusy(`bulk-${action}`);
    try {
      const r = await api.post<BulkResult>("/api/review/bulk", body);
      const parts = [`${fmtInt(r.updated)} updated`];
      if (r.applied) parts.push(`${fmtInt(r.applied)} written to cleaned data`);
      if (r.not_applicable) parts.push(`${fmtInt(r.not_applicable)} not written (no cleaned file for that run)`);
      if (r.skipped) parts.push(`${fmtInt(r.skipped)} skipped (not pending)`);
      toast.success(`${VERB[action]}: ${parts.join(", ")}.`);
      dispatch({ type: "clear" });
      setConfirmApply(false);
      invalidateReview();
    } catch (err) {
      toast.error((err as Error).message);
    } finally {
      setBusy(null);
    }
  }

  // keyboard
  const handlers = useRef({ single, bulk, page });
  useEffect(() => {
    handlers.current = { single, bulk, page };
  });
  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if (e.defaultPrevented) return;
      const cmd = inboxCommand(e);
      if (!cmd) return;
      if (cmd === "escape") {
        if (isTypingTarget(e.target)) return;
        if (nSelected) {
          e.preventDefault();
          dispatch({ type: "clear" });
        }
        return;
      }
      if (isTypingTarget(e.target) || document.querySelector("[role=dialog][data-state=open]:not([data-inbox-sheet])")) return;
      const h = handlers.current;
      switch (cmd) {
        case "next":
          e.preventDefault();
          if (st.active >= items.length - 1) h.page(1, "first");
          else dispatch({ type: "move", delta: 1 });
          break;
        case "prev":
          e.preventDefault();
          if (st.active <= 0) h.page(-1, "last");
          else dispatch({ type: "move", delta: -1 });
          break;
        case "open":
          if (document.activeElement === listRef.current && st.active >= 0) {
            e.preventDefault();
            if (isMobile) setSheetOpen(true);
          }
          break;
        case "toggle":
        case "range":
          if (st.active >= 0) {
            e.preventDefault();
            dispatch({ type: "toggle", index: st.active, range: cmd === "range" });
          }
          break;
        case "approve":
        case "reject":
        case "normal": {
          e.preventDefault();
          const action = cmd === "normal" ? "false_positive" : cmd;
          if (nSelected) void h.bulk(action);
          else void h.single(action);
          break;
        }
        case "edit":
          if (detail.current && activeItem?.status === "pending" && activeItem.column) {
            e.preventDefault();
            if (isMobile) setSheetOpen(true);
            setTimeout(() => detail.current?.focusEdit(), isMobile ? 250 : 0);
          }
          break;
      }
    }
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [st.active, items.length, nSelected, isMobile, activeItem]);

  const counts = facets.data?.counts;
  const filtered = Boolean(s.pipeline || s.column || s.detector || s.q || s.run);
  const from = total ? s.offset + 1 : 0;
  const to = Math.min(s.offset + s.limit, total);
  const allOnPage = items.length > 0 && items.every((i) => isSelected(st, i.id));
  const someOnPage = items.some((i) => isSelected(st, i.id));

  const listPane = (
    <div className="flex h-full min-h-0 flex-col">
      <div className="flex items-center gap-3 border-b px-3 py-2">
        <Checkbox
          aria-label="Select every item on this page"
          checked={allOnPage ? true : someOnPage ? "indeterminate" : false}
          onCheckedChange={(v) => dispatch({ type: "selectPage", on: v === true })}
          disabled={!items.length}
        />
        <span className="text-muted-foreground flex-1 text-xs tabular">{total ? `${fmtInt(from)}–${fmtInt(to)} of ${fmtInt(total)}` : "0 items"}</span>
        <Button variant="ghost" size="icon" className="size-7" aria-label="Previous page" disabled={s.offset <= 0} onClick={() => page(-1)}>
          <ChevronLeftIcon />
        </Button>
        <Button variant="ghost" size="icon" className="size-7" aria-label="Next page" disabled={s.offset + s.limit >= total} onClick={() => page(1)}>
          <ChevronRightIcon />
        </Button>
      </div>
      {nSelected ? (
        <div role="region" aria-label="Bulk actions" className="bg-accent/60 border-primary/20 animate-fade-in space-y-2 border-b px-3 py-2.5">
          <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-sm">
            <strong className="tabular">{fmtInt(nSelected)} selected</strong>
            {allOnPage && !st.allMatching && total > items.length ? (
              <Button variant="link" size="sm" className="h-auto p-0" onClick={() => dispatch({ type: "selectAllMatching" })}>
                Select all {fmtInt(total)} matching
              </Button>
            ) : null}
            <Button variant="link" size="sm" className="text-muted-foreground h-auto p-0" onClick={() => dispatch({ type: "clear" })}>
              Clear <Kbd className="ml-1">Esc</Kbd>
            </Button>
          </div>
          {confirmApply ? (
            <Confirmation state="requested" className="bg-card">
              <ConfirmationRequest>
                <ConfirmationTitle>Write {fmtInt(nSelected)} items into the cleaned data?</ConfirmationTitle>
                <ConfirmationBody>Pending items are approved first. Values are written into the cleaned CSV of the analysis they came from; items from pipeline runs stay approved.</ConfirmationBody>
              </ConfirmationRequest>
              <ConfirmationActions>
                <ConfirmationAction variant="ghost" onClick={() => setConfirmApply(false)}>
                  Cancel
                </ConfirmationAction>
                <ConfirmationAction onClick={() => bulk("apply")} disabled={busy !== null}>
                  {busy === "bulk-apply" ? <Spinner /> : <UploadIcon />} Apply
                </ConfirmationAction>
              </ConfirmationActions>
            </Confirmation>
          ) : (
            <div className="flex flex-wrap gap-1.5">
              {isPendingView ? (
                <>
                  <Button size="sm" onClick={() => bulk("approve")} disabled={busy !== null}>
                    {busy === "bulk-approve" ? <Spinner /> : <CheckIcon />} Approve <Kbd className="bg-primary-foreground/20 text-primary-foreground">a</Kbd>
                  </Button>
                  <Button size="sm" variant="outline" onClick={() => bulk("reject")} disabled={busy !== null}>
                    Reject <Kbd>r</Kbd>
                  </Button>
                  <Button size="sm" variant="outline" onClick={() => bulk("false_positive")} disabled={busy !== null}>
                    Mark normal <Kbd>m</Kbd>
                  </Button>
                </>
              ) : null}
              <Button size="sm" variant="outline" onClick={() => setConfirmApply(true)} disabled={busy !== null}>
                <UploadIcon /> Apply to cleaned data
              </Button>
            </div>
          )}
        </div>
      ) : null}
      {list.error ? (
        <ErrorState error={list.error} retry={() => list.refetch()} />
      ) : !list.data ? (
        <LoadingRows rows={8} />
      ) : !items.length ? (
        filtered || s.status !== "pending" ? (
          <EmptyState icon={InboxIcon} title="No items match these filters">
            {filtered ? (
              <Button variant="outline" size="sm" onClick={() => setFilter({ pipeline: "", column: "", detector: "", q: "", run: "" })}>
                Clear filters
              </Button>
            ) : null}
          </EmptyState>
        ) : (
          <EmptyState icon={InboxIcon} title="Inbox zero" description="Values a fix could not settle appear here. Confirm an incident or preview a fix in Analyze to queue some.">
            <Button variant="outline" size="sm" asChild>
              <Link to="/">See incidents</Link>
            </Button>
          </EmptyState>
        )
      ) : (
        <ul
          id="inbox-list"
          ref={listRef}
          role="listbox"
          aria-label="Review items"
          aria-multiselectable="true"
          aria-activedescendant={activeItem ? `ri-${activeItem.id}` : undefined}
          tabIndex={0}
          className={cn("min-h-0 flex-1 overflow-y-auto outline-none focus-visible:ring-[3px] focus-visible:ring-inset focus-visible:ring-ring/40", list.isFetching && "opacity-70")}
        >
          {items.map((it, i) => {
            const sel = isSelected(st, it.id);
            const active = i === st.active;
            const after = it.status === "pending" ? it.suggestion : it.resolved_value;
            return (
              <li
                key={it.id}
                id={`ri-${it.id}`}
                role="option"
                aria-selected={active}
                onClick={(e) => {
                  if (e.shiftKey) {
                    e.preventDefault();
                    dispatch({ type: "toggle", index: i, range: true });
                    return;
                  }
                  if (e.metaKey || e.ctrlKey) {
                    dispatch({ type: "toggle", index: i });
                    return;
                  }
                  dispatch({ type: "open", index: i });
                  if (isMobile) setSheetOpen(true);
                }}
                className={cn(
                  "relative flex cursor-pointer items-start gap-3 border-b px-3 py-2.5 select-none",
                  active ? "bg-accent" : "hover:bg-muted/50",
                  sel && !active && "bg-primary/5",
                )}
              >
                {active ? <span aria-hidden className="bg-primary absolute inset-y-0 left-0 w-0.5" /> : null}
                <span
                  onClick={(e) => {
                    e.stopPropagation();
                    dispatch({ type: "toggle", index: i, range: e.shiftKey });
                  }}
                  className="pt-0.5"
                >
                  <Checkbox checked={sel} tabIndex={-1} aria-label={`Select item ${it.id}`} />
                </span>
                <span className="min-w-0 flex-1 space-y-0.5">
                  <span className="flex min-w-0 items-center gap-1.5 text-sm">
                    <span className="truncate font-mono font-medium">{it.column || "whole row"}</span>
                    {it.column ? (
                      <>
                        <span className="text-sev-high truncate font-mono">{show(it.value)}</span>
                        {after !== null && after !== undefined ? (
                          <>
                            <ArrowRightIcon className="text-muted-foreground size-3 shrink-0" aria-label="to" />
                            <span className="text-ok truncate font-mono">{show(after)}</span>
                          </>
                        ) : null}
                      </>
                    ) : (
                      <span className="text-muted-foreground">unusual combination</span>
                    )}
                  </span>
                  <span className="text-muted-foreground block truncate text-xs">{[runLabel(it.pipeline || "–"), `row ${String(it.row_index ?? "–")}`, it.detector].filter(Boolean).join(" · ")}</span>
                </span>
                {it.status !== "pending" ? <StatusBadge status={it.status} className="text-[11px]" /> : null}
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );

  const detailPane = activeItem ? (
    <ItemDetail key={activeItem.id} id={activeItem.id} fallback={activeItem} onAction={single} ref={detail} busy={busy} />
  ) : (
    <div className="flex h-full flex-col items-center justify-center gap-4 p-8 text-center">
      <p className="text-muted-foreground text-sm">Select an item to review it.</p>
      <KeysHint />
    </div>
  );

  return (
    <div className="animate-fade-in flex flex-col gap-4">
      <PageHeader
        title="Review inbox"
        description="Values a fix could not settle safely. Approve the suggested or edited value, reject to keep the original, or mark as normal to teach the detector. Press ? for shortcuts."
      />
      <div role="toolbar" aria-label="Review filters" className="flex flex-col gap-2 xl:flex-row xl:items-center">
        <ToggleGroup type="single" variant="outline" size="sm" value={s.status} onValueChange={(v) => v && setFilter({ status: v })} aria-label="Status" className="max-w-full overflow-x-auto">
          {STATUSES.map((v) => (
            <ToggleGroupItem key={v} value={v} className="gap-1.5 px-2.5 text-xs capitalize">
              {v}
              {v !== "all" && counts ? <span className="text-muted-foreground tabular">{fmtInt(counts[v as keyof typeof counts] ?? 0)}</span> : null}
            </ToggleGroupItem>
          ))}
        </ToggleGroup>
        <div className="flex flex-wrap items-center gap-2 xl:ml-auto">
          <FilterSelect label="Source" allLabel="All sources" value={s.pipeline} onChange={(v) => setFilter({ pipeline: v })} options={(facets.data?.pipelines ?? []).map((p) => ({ value: p.value, label: `${runLabel(p.value)} · ${fmtInt(p.count)}` }))} />
          <FilterSelect label="Column" allLabel="All columns" value={s.column} onChange={(v) => setFilter({ column: v })} options={(facets.data?.columns ?? []).map((p) => ({ value: p.value, label: `${p.value} · ${fmtInt(p.count)}` }))} />
          <FilterSelect label="Detector" allLabel="All detectors" value={s.detector} onChange={(v) => setFilter({ detector: v })} options={(facets.data?.detectors ?? []).map((p) => ({ value: p.value, label: `${p.value} · ${fmtInt(p.count)}` }))} />
          <SearchInput value={s.q} onChange={(v) => setFilter({ q: v })} placeholder="Search  /" label="Search review items" className="sm:w-52" />
        </div>
      </div>
      {s.run ? (
        <div className="bg-accent/50 flex flex-wrap items-center justify-between gap-2 rounded-lg border px-3 py-2 text-sm">
          <span>
            Showing items from <Link className="font-medium underline underline-offset-4" to={`/runs/${s.run}`}>run #{s.run}</Link>.
          </span>
          <Button size="sm" variant="outline" onClick={() => setFilter({ run: "" })}>
            Show all runs
          </Button>
        </div>
      ) : null}
      <div className="bg-card h-[calc(100dvh-14rem)] min-h-[480px] overflow-hidden rounded-xl border shadow-xs">
        {isMobile ? (
          listPane
        ) : (
          <ResizablePanelGroup orientation="horizontal">
            <ResizablePanel defaultSize="42%" minSize="28%">
              {listPane}
            </ResizablePanel>
            <ResizableHandle withHandle />
            <ResizablePanel defaultSize="58%" minSize="32%">
              <section aria-label="Item details" className="h-full overflow-y-auto">
                {detailPane}
              </section>
            </ResizablePanel>
          </ResizablePanelGroup>
        )}
      </div>
      {isMobile ? (
        <Sheet open={sheetOpen && Boolean(activeItem)} onOpenChange={setSheetOpen}>
          <SheetContent
            side="bottom"
            className="max-h-[88dvh] overflow-y-auto rounded-t-xl p-0"
            data-inbox-sheet
            onOpenAutoFocus={(e) => {
              // focus the sheet itself rather than its first control (a time with a tooltip)
              e.preventDefault();
              (e.currentTarget as HTMLElement).focus();
            }}
          >
            <SheetHeader className="sr-only">
              <SheetTitle>Review item</SheetTitle>
              <SheetDescription>Approve, reject or mark the value as normal</SheetDescription>
            </SheetHeader>
            {detailPane}
          </SheetContent>
        </Sheet>
      ) : null}
    </div>
  );
}
