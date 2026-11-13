import { describe, expect, it } from "vitest";

import { fmtAgo, fmtBytes, fmtDelta, fmtInt, fmtMs, fmtNum, fmtPct, fmtPoints, fmtSchedule, fmtValue, parseTyped, runLabel } from "./format";

describe("formatters", () => {
  it("formats integers and percentages", () => {
    expect(fmtInt(1234.4)).toBe("1,234");
    expect(fmtInt(null)).toBe("–");
    expect(fmtPct(0.0491)).toBe("4.9%");
    expect(fmtPct(1, 0)).toBe("100%");
  });

  it("trims statistics but keeps raw data values exact", () => {
    expect(fmtNum(47.4612345)).toBe("47.46");
    expect(fmtNum(3454.47)).toBe("3,454.5");
    expect(fmtNum("abc")).toBe("abc");
    expect(fmtValue(100787)).toBe("100787");
    expect(fmtValue(0.1 + 0.2)).toBe("0.3");
    expect(fmtValue(null)).toBe("null");
    expect(fmtValue(false)).toBe("false");
  });

  it("describes the change past the expected band", () => {
    expect(fmtDelta(16.7401)).toBe("+1,674% above range");
    expect(fmtDelta(0.4604)).toBe("+46% above range");
    expect(fmtDelta(-0.05)).toBe("−5.0% below range");
    expect(fmtDelta(0)).toBe("within range");
    expect(fmtDelta(null)).toBeNull();
  });

  it("formats durations, sizes, schedules and trends", () => {
    expect(fmtMs(521.4)).toBe("521 ms");
    expect(fmtMs(2500)).toBe("2.5 s");
    expect(fmtMs(125000)).toBe("2 min 5 s");
    expect(fmtBytes(63543)).toBe("62.1 KB");
    expect(fmtSchedule(3600)).toBe("every 1 h");
    expect(fmtSchedule(null)).toBe("manual");
    expect(fmtPoints(0.0123)).toBe("+1.2");
    expect(fmtPoints(-0.004)).toBe("−0.4");
    expect(fmtPoints(0.0001)).toBe("0.0");
  });

  it("formats relative times", () => {
    const now = Date.parse("2026-11-13T12:00:00Z");
    expect(fmtAgo("2026-11-13T11:59:50Z", now)).toBe("just now");
    expect(fmtAgo("2026-11-13T11:42:00Z", now)).toBe("18 min ago");
    expect(fmtAgo("2026-11-13T07:00:00Z", now)).toBe("5 h ago");
    expect(fmtAgo("2026-11-10T12:00:00Z", now)).toBe("3 d ago");
  });

  it("labels analysis runs by file name", () => {
    expect(runLabel("analysis:orders.csv")).toBe("orders.csv");
    expect(runLabel("orders_quality")).toBe("orders_quality");
  });

  it("parses what a reviewer typed", () => {
    expect(parseTyped("42")).toBe(42);
    expect(parseTyped("-1.5e3")).toBe(-1500);
    expect(parseTyped("  ")).toBeNull();
    expect(parseTyped("null")).toBeNull();
    expect(parseTyped("true")).toBe(true);
    expect(parseTyped("north")).toBe("north");
  });
});
