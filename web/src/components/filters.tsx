// Filter controls: a Select with an "all" option (Radix Select has no empty
// value), a debounced search box, and URL-backed filter state.

import { SearchIcon, XIcon } from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";
import { useSearchParams } from "react-router";

import { InputGroup, InputGroupAddon, InputGroupButton, InputGroupInput } from "@/components/ui/input-group";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { cn } from "@/lib/utils";

const ALL = "__all__";

export interface Option {
  value: string;
  label: string;
}

export function FilterSelect({
  value,
  onChange,
  options,
  allLabel,
  label,
  className,
  size = "sm",
}: {
  value: string;
  onChange: (v: string) => void;
  options: Option[];
  allLabel?: string;
  label: string;
  className?: string;
  size?: "sm" | "default";
}) {
  const known = options.some((o) => o.value === value);
  return (
    <Select value={value === "" && allLabel ? ALL : value} onValueChange={(v) => onChange(v === ALL ? "" : v)}>
      <SelectTrigger size={size} aria-label={label} className={cn("min-w-[140px] max-w-full", className)}>
        <SelectValue placeholder={label} />
      </SelectTrigger>
      <SelectContent>
        {allLabel ? <SelectItem value={ALL}>{allLabel}</SelectItem> : null}
        {options.map((o) => (
          <SelectItem key={o.value} value={o.value}>
            {o.label}
          </SelectItem>
        ))}
        {value && !known ? <SelectItem value={value}>{value}</SelectItem> : null}
      </SelectContent>
    </Select>
  );
}

export function SearchInput({ value, onChange, placeholder, label, className, delay = 300 }: { value: string; onChange: (v: string) => void; placeholder: string; label: string; className?: string; delay?: number }) {
  const [text, setText] = useState(value);
  const [synced, setSynced] = useState(value);
  if (value !== synced) {
    // the URL changed underneath us (back/forward): follow it
    setSynced(value);
    setText(value);
  }
  useEffect(() => {
    if (text === value) return;
    const t = setTimeout(() => onChange(text.trim()), delay);
    return () => clearTimeout(t);
  }, [text, value, onChange, delay]);
  return (
    <InputGroup className={cn("h-8 w-full sm:w-64", className)}>
      <InputGroupAddon>
        <SearchIcon aria-hidden />
      </InputGroupAddon>
      <InputGroupInput type="search" value={text} onChange={(e) => setText(e.target.value)} placeholder={placeholder} aria-label={label} className="[&::-webkit-search-cancel-button]:hidden" />
      {text ? (
        <InputGroupAddon align="inline-end">
          <InputGroupButton size="icon-xs" aria-label="Clear search" onClick={() => setText("")}>
            <XIcon />
          </InputGroupButton>
        </InputGroupAddon>
      ) : null}
    </InputGroup>
  );
}

/** Filter state kept in the query string, so views can be linked and survive reloads. */
export function useUrlState<T extends Record<string, string | number>>(defaults: T) {
  const [params, setParams] = useSearchParams();
  const state = useMemo(() => {
    const out = { ...defaults };
    for (const k of Object.keys(defaults) as (keyof T)[]) {
      const raw = params.get(k as string);
      if (raw === null) continue;
      out[k] = (typeof defaults[k] === "number" ? Number(raw) || defaults[k] : raw) as T[keyof T];
    }
    return out;
    // defaults is a literal at each call site
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [params]);
  const set = useCallback(
    (patch: Partial<T>) => {
      setParams(
        (prev) => {
          const next = new URLSearchParams(prev);
          for (const [k, v] of Object.entries(patch)) {
            if (v === undefined || v === "" || v === defaults[k]) next.delete(k);
            else next.set(k, String(v));
          }
          return next;
        },
        { replace: true },
      );
    },
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [setParams],
  );
  return [state, set] as const;
}
