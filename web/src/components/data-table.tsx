// TanStack Table on top of the shadcn table: server-side paging and sorting,
// clickable rows that stay keyboard accessible, and a pager with page sizes.

import {
  flexRender,
  getCoreRowModel,
  useReactTable,
  type ColumnDef,
  type OnChangeFn,
  type SortingState,
} from "@tanstack/react-table";
import { ArrowDownIcon, ArrowUpDownIcon, ArrowUpIcon, ChevronLeftIcon, ChevronRightIcon } from "lucide-react";
import type { ReactNode } from "react";

import { Button } from "@/components/ui/button";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { fmtInt } from "@/lib/format";
import { cn } from "@/lib/utils";

declare module "@tanstack/react-table" {
  // eslint-disable-next-line @typescript-eslint/no-unused-vars
  interface ColumnMeta<TData, TValue> {
    align?: "right";
    className?: string;
    headClassName?: string;
    hideBelow?: "sm" | "md" | "lg";
  }
}

const HIDE: Record<string, string> = { sm: "hidden sm:table-cell", md: "hidden md:table-cell", lg: "hidden lg:table-cell" };

export interface DataTableProps<T> {
  columns: ColumnDef<T, unknown>[];
  data: T[];
  getRowId?: (row: T, index: number) => string;
  onRowClick?: (row: T) => void;
  rowLabel?: (row: T) => string;
  rowClassName?: (row: T) => string | undefined;
  sorting?: SortingState;
  onSortingChange?: OnChangeFn<SortingState>;
  loading?: boolean;
  empty?: ReactNode;
  caption?: string;
  className?: string;
  dense?: boolean;
}

export function DataTable<T>({
  columns,
  data,
  getRowId,
  onRowClick,
  rowLabel,
  rowClassName,
  sorting,
  onSortingChange,
  loading,
  empty,
  caption,
  className,
  dense,
}: DataTableProps<T>) {
  // TanStack Table returns non-memoizable functions; the compiler lint is advisory here
  // eslint-disable-next-line react-hooks/incompatible-library
  const table = useReactTable({
    data,
    columns,
    getRowId,
    getCoreRowModel: getCoreRowModel(),
    manualSorting: true,
    manualPagination: true,
    enableSortingRemoval: false,
    state: sorting ? { sorting } : {},
    onSortingChange,
  });

  return (
    <div className={cn("relative w-full", className)} aria-busy={loading || undefined}>
      <Table className={cn(dense && "[&_td]:py-1.5")}>
        {caption ? <caption className="sr-only">{caption}</caption> : null}
        <TableHeader className="bg-muted/40 sticky top-0 z-10">
          {table.getHeaderGroups().map((hg) => (
            <TableRow key={hg.id} className="hover:bg-transparent">
              {hg.headers.map((header) => {
                const meta = header.column.columnDef.meta;
                const sortable = header.column.getCanSort() && Boolean(onSortingChange);
                const dir = header.column.getIsSorted();
                return (
                  <TableHead
                    key={header.id}
                    aria-sort={sortable ? (dir === "asc" ? "ascending" : dir === "desc" ? "descending" : "none") : undefined}
                    className={cn("text-muted-foreground h-9 text-xs font-medium", meta?.align === "right" && "text-right", meta?.hideBelow && HIDE[meta.hideBelow], meta?.headClassName)}
                  >
                    {header.isPlaceholder ? null : sortable ? (
                      <button
                        type="button"
                        onClick={header.column.getToggleSortingHandler()}
                        className={cn("hover:text-foreground -mx-1 inline-flex items-center gap-1 rounded px-1 py-0.5 outline-none focus-visible:ring-[3px] focus-visible:ring-ring/50", meta?.align === "right" && "flex-row-reverse")}
                      >
                        {flexRender(header.column.columnDef.header, header.getContext())}
                        {dir === "asc" ? <ArrowUpIcon className="size-3" aria-hidden /> : dir === "desc" ? <ArrowDownIcon className="size-3" aria-hidden /> : <ArrowUpDownIcon className="size-3 opacity-40" aria-hidden />}
                      </button>
                    ) : (
                      flexRender(header.column.columnDef.header, header.getContext())
                    )}
                  </TableHead>
                );
              })}
            </TableRow>
          ))}
        </TableHeader>
        <TableBody className={cn(loading && data.length > 0 && "opacity-60 transition-opacity")}>
          {loading && !data.length
            ? Array.from({ length: 6 }, (_, i) => (
                <TableRow key={`s${i}`} className="hover:bg-transparent">
                  {columns.map((_c, j) => (
                    <TableCell key={j}>
                      <Skeleton className="h-4" style={{ width: `${40 + ((i * 13 + j * 29) % 50)}%` }} />
                    </TableCell>
                  ))}
                </TableRow>
              ))
            : table.getRowModel().rows.map((row) => (
                <TableRow
                  key={row.id}
                  className={cn(onRowClick && "cursor-pointer", rowClassName?.(row.original))}
                  onClick={
                    onRowClick
                      ? (e) => {
                          if ((e.target as Element).closest("a, button, input, [role=checkbox], [data-no-row-click]")) return;
                          onRowClick(row.original);
                        }
                      : undefined
                  }
                  onKeyDown={
                    onRowClick
                      ? (e) => {
                          if (e.key === "Enter" && e.target === e.currentTarget) onRowClick(row.original);
                        }
                      : undefined
                  }
                  tabIndex={onRowClick ? 0 : undefined}
                  aria-label={rowLabel?.(row.original)}
                >
                  {row.getVisibleCells().map((cell) => {
                    const meta = cell.column.columnDef.meta;
                    return (
                      <TableCell key={cell.id} className={cn(meta?.align === "right" && "text-right tabular", meta?.hideBelow && HIDE[meta.hideBelow], meta?.className)}>
                        {flexRender(cell.column.columnDef.cell, cell.getContext())}
                      </TableCell>
                    );
                  })}
                </TableRow>
              ))}
        </TableBody>
      </Table>
      {!loading && !data.length && empty ? <div className="border-t">{empty}</div> : null}
    </div>
  );
}

export function Pager({
  offset,
  limit,
  total,
  onChange,
  sizes = [25, 50, 100],
  noun = "rows",
}: {
  offset: number;
  limit: number;
  total: number;
  onChange: (offset: number, limit: number) => void;
  sizes?: number[];
  noun?: string;
}) {
  if (!total) return null;
  const from = offset + 1;
  const to = Math.min(offset + limit, total);
  const page = Math.floor(offset / limit) + 1;
  const pages = Math.max(1, Math.ceil(total / limit));
  return (
    <div className="text-muted-foreground flex flex-wrap items-center justify-between gap-2 border-t px-3 py-2 text-xs">
      <span className="tabular">
        {fmtInt(from)}–{fmtInt(to)} of {fmtInt(total)} {noun}
      </span>
      <div className="flex items-center gap-2">
        <Select value={String(limit)} onValueChange={(v) => onChange(0, Number(v))}>
          <SelectTrigger size="sm" className="h-7 w-auto gap-1 text-xs" aria-label="Rows per page">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {sizes.map((s) => (
              <SelectItem key={s} value={String(s)}>
                {s} / page
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
        <span className="tabular hidden sm:inline">
          Page {page} of {pages}
        </span>
        <Button variant="outline" size="icon" className="size-7" aria-label="Previous page" disabled={offset <= 0} onClick={() => onChange(Math.max(0, offset - limit), limit)}>
          <ChevronLeftIcon />
        </Button>
        <Button variant="outline" size="icon" className="size-7" aria-label="Next page" disabled={offset + limit >= total} onClick={() => onChange(offset + limit, limit)}>
          <ChevronRightIcon />
        </Button>
      </div>
    </div>
  );
}
