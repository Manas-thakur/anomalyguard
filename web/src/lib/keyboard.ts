// Pure keyboard logic: the review inbox's cursor/selection reducer, the inbox key
// map, and the "g then letter" navigation sequence. Kept free of React and the
// DOM so it can be unit tested.

export interface InboxState {
  /** ids on the current page, in order */
  ids: number[];
  /** index of the open item, -1 for none */
  active: number;
  /** anchor index for Shift ranges */
  anchor: number;
  selected: number[];
  /** "Select all N matching": every item that matches the filters, across pages */
  allMatching: boolean;
}

export type InboxAction =
  | { type: "load"; ids: number[]; keepActive?: boolean; preferFirst?: boolean }
  | { type: "move"; delta: number }
  | { type: "open"; index: number }
  | { type: "toggle"; index: number; range?: boolean }
  | { type: "selectPage"; on: boolean }
  | { type: "selectAllMatching" }
  | { type: "clear" }
  | { type: "remove"; id: number };

export const initialInbox: InboxState = { ids: [], active: -1, anchor: -1, selected: [], allMatching: false };

const clamp = (v: number, lo: number, hi: number) => Math.max(lo, Math.min(hi, v));

export function inboxReducer(state: InboxState, action: InboxAction): InboxState {
  switch (action.type) {
    case "load": {
      const ids = action.ids;
      let active = action.keepActive ? Math.min(state.active, ids.length - 1) : -1;
      if (active < 0 && ids.length && action.preferFirst) active = 0;
      const keep = new Set(ids);
      return {
        ids,
        active,
        anchor: active,
        selected: action.keepActive ? state.selected.filter((id) => keep.has(id)) : [],
        allMatching: action.keepActive ? state.allMatching : false,
      };
    }
    case "move": {
      if (!state.ids.length) return state;
      const active = clamp((state.active < 0 ? (action.delta > 0 ? -1 : 0) : state.active) + action.delta, 0, state.ids.length - 1);
      return { ...state, active, anchor: state.selected.length ? state.anchor : active };
    }
    case "open": {
      if (action.index < 0 || action.index >= state.ids.length) return state;
      return { ...state, active: action.index, anchor: state.selected.length ? state.anchor : action.index };
    }
    case "toggle": {
      if (action.index < 0 || action.index >= state.ids.length) return state;
      // leaving "all matching" turns it into an explicit selection of this page
      const base = new Set(state.allMatching ? state.ids : state.selected);
      if (action.range && state.anchor >= 0) {
        const [a, b] = state.anchor < action.index ? [state.anchor, action.index] : [action.index, state.anchor];
        for (let k = a; k <= b; k += 1) base.add(state.ids[k]);
        return { ...state, selected: [...base], allMatching: false };
      }
      const id = state.ids[action.index];
      if (base.has(id)) base.delete(id);
      else base.add(id);
      return { ...state, selected: [...base], anchor: action.index, allMatching: false };
    }
    case "selectPage":
      return { ...state, selected: action.on ? [...new Set([...state.selected, ...state.ids])] : state.selected.filter((id) => !state.ids.includes(id)), allMatching: false };
    case "selectAllMatching":
      return { ...state, selected: [...new Set([...state.selected, ...state.ids])], allMatching: true };
    case "clear":
      return { ...state, selected: [], allMatching: false };
    case "remove": {
      const at = state.ids.indexOf(action.id);
      if (at < 0) return { ...state, selected: state.selected.filter((x) => x !== action.id) };
      const ids = state.ids.filter((x) => x !== action.id);
      let active = state.active;
      if (at < active) active -= 1;
      if (active >= ids.length) active = ids.length - 1;
      return { ...state, ids, active, anchor: active, selected: state.selected.filter((x) => x !== action.id) };
    }
  }
}

export const selectionCount = (s: InboxState, total: number) => (s.allMatching ? total : s.selected.length);
export const isSelected = (s: InboxState, id: number) => s.allMatching || s.selected.includes(id);

export type InboxCommand =
  | "next"
  | "prev"
  | "open"
  | "toggle"
  | "range"
  | "approve"
  | "reject"
  | "normal"
  | "edit"
  | "escape";

export interface KeyLike {
  key: string;
  shiftKey?: boolean;
  metaKey?: boolean;
  ctrlKey?: boolean;
  altKey?: boolean;
}

/** Map a key press in the inbox to a command (null: not ours). */
export function inboxCommand(e: KeyLike): InboxCommand | null {
  if (e.metaKey || e.ctrlKey || e.altKey) return null;
  switch (e.key) {
    case "j":
    case "ArrowDown":
      return "next";
    case "k":
    case "ArrowUp":
      return "prev";
    case "Enter":
      return "open";
    case "x":
      return e.shiftKey ? "range" : "toggle";
    case "X":
      return "range";
    case "a":
      return "approve";
    case "r":
      return "reject";
    case "m":
      return "normal";
    case "e":
      return "edit";
    case "Escape":
      return "escape";
    default:
      return null;
  }
}

export const GO_KEYS: Record<string, string> = {
  h: "/",
  r: "/runs",
  i: "/review",
  a: "/analyze",
  p: "/pipelines",
  s: "/settings",
};

/**
 * "g" then a letter within `windowMs` navigates. Returns the next pending
 * timestamp and the path to go to (if any).
 */
export function goSequence(pending: number, key: string, now: number, windowMs = 1200): { pending: number; to: string | null } {
  if (pending && now - pending < windowMs && GO_KEYS[key]) return { pending: 0, to: GO_KEYS[key] };
  return { pending: key === "g" ? now : 0, to: null };
}

/** Score a fuzzy (subsequence) match; higher is better, -1 for no match. */
export function fuzzy(query: string, text: string): number {
  const q = query.toLowerCase().trim();
  if (!q) return 0;
  const t = text.toLowerCase();
  const at = t.indexOf(q);
  if (at >= 0) return 100 - at + (at === 0 || t[at - 1] === " " ? 20 : 0);
  let i = 0;
  let score = 0;
  let prev = -2;
  for (let k = 0; k < t.length && i < q.length; k += 1) {
    if (t[k] === q[i]) {
      score += k === prev + 1 ? 3 : 1;
      prev = k;
      i += 1;
    }
  }
  return i === q.length ? score : -1;
}

/** True when a key press belongs to a text field (or an open dialog). */
export function isTypingTarget(target: EventTarget | null): boolean {
  if (!target || typeof (target as Element).closest !== "function") return false;
  const el = target as Element;
  return Boolean(el.closest("input, textarea, select, [contenteditable=''], [contenteditable='true'], [role='dialog'], [role='alertdialog'], [cmdk-root]"));
}
