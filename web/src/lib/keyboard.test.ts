import { describe, expect, it } from "vitest";

import { fuzzy, goSequence, inboxCommand, inboxReducer, initialInbox, isSelected, selectionCount, type InboxState } from "./keyboard";

const loaded = (ids: number[], active = 0): InboxState => ({ ...inboxReducer(initialInbox, { type: "load", ids, preferFirst: true }), active, anchor: active });

describe("inbox reducer", () => {
  it("opens the first item on load when asked and keeps the cursor on reload", () => {
    const s = inboxReducer(initialInbox, { type: "load", ids: [10, 11, 12], preferFirst: true });
    expect(s.active).toBe(0);
    const narrow = inboxReducer(initialInbox, { type: "load", ids: [10, 11, 12] });
    expect(narrow.active).toBe(-1);
    const moved = inboxReducer(s, { type: "move", delta: 2 });
    const reloaded = inboxReducer(moved, { type: "load", ids: [10, 11], keepActive: true });
    expect(reloaded.active).toBe(1);
  });

  it("moves with j/k and stops at the ends", () => {
    let s = loaded([1, 2, 3]);
    s = inboxReducer(s, { type: "move", delta: 1 });
    s = inboxReducer(s, { type: "move", delta: 1 });
    s = inboxReducer(s, { type: "move", delta: 1 });
    expect(s.active).toBe(2);
    s = inboxReducer(s, { type: "move", delta: -5 });
    expect(s.active).toBe(0);
  });

  it("toggles single items and selects Shift ranges from the anchor", () => {
    let s = loaded([1, 2, 3, 4, 5], 1);
    s = inboxReducer(s, { type: "toggle", index: 1 });
    expect(s.selected).toEqual([2]);
    s = inboxReducer(s, { type: "toggle", index: 3, range: true });
    expect([...s.selected].sort()).toEqual([2, 3, 4]);
    s = inboxReducer(s, { type: "toggle", index: 2 });
    expect([...s.selected].sort()).toEqual([2, 4]);
    expect(selectionCount(s, 99)).toBe(2);
  });

  it("selects the page, then every matching item, and clears", () => {
    let s = loaded([1, 2, 3]);
    s = inboxReducer(s, { type: "selectPage", on: true });
    expect(s.selected).toEqual([1, 2, 3]);
    s = inboxReducer(s, { type: "selectAllMatching" });
    expect(selectionCount(s, 250)).toBe(250);
    expect(isSelected(s, 999)).toBe(true);
    // deselecting one item turns "all matching" into an explicit selection
    s = inboxReducer(s, { type: "toggle", index: 0 });
    expect(s.allMatching).toBe(false);
    expect(s.selected).toEqual([2, 3]);
    s = inboxReducer(s, { type: "clear" });
    expect(selectionCount(s, 250)).toBe(0);
  });

  it("drops a decided item and keeps the cursor in place", () => {
    let s = loaded([1, 2, 3], 1);
    s = inboxReducer(s, { type: "remove", id: 2 });
    expect(s.ids).toEqual([1, 3]);
    expect(s.active).toBe(1);
    s = inboxReducer(s, { type: "remove", id: 3 });
    expect(s.active).toBe(0);
  });
});

describe("key maps", () => {
  it("maps inbox keys to commands", () => {
    expect(inboxCommand({ key: "j" })).toBe("next");
    expect(inboxCommand({ key: "ArrowUp" })).toBe("prev");
    expect(inboxCommand({ key: "x" })).toBe("toggle");
    expect(inboxCommand({ key: "x", shiftKey: true })).toBe("range");
    expect(inboxCommand({ key: "m" })).toBe("normal");
    expect(inboxCommand({ key: "a", ctrlKey: true })).toBeNull();
    expect(inboxCommand({ key: "q" })).toBeNull();
  });

  it("navigates with g then a letter inside the window", () => {
    let r = goSequence(0, "g", 1000);
    expect(r).toEqual({ pending: 1000, to: null });
    r = goSequence(r.pending, "r", 1500);
    expect(r.to).toBe("/runs");
    expect(goSequence(1000, "r", 5000).to).toBeNull();
    expect(goSequence(1000, "h", 1100).to).toBe("/");
  });

  it("ranks fuzzy matches", () => {
    expect(fuzzy("run", "Run pipeline: orders")).toBeGreaterThan(fuzzy("run", "Go to Pipelines rerun"));
    expect(fuzzy("rpo", "Run pipeline: orders")).toBeGreaterThan(0);
    expect(fuzzy("zzz", "Health")).toBe(-1);
  });
});
