import { describe, expect, it, vi } from "vitest";

import { ApiError, createClient, errorMessage, filenameFrom, KEY_STORE, queryString, waitForJob } from "./api";
import type { Job } from "./types";

function memoryStorage(init: Record<string, string> = {}) {
  const m = new Map(Object.entries(init));
  return {
    getItem: (k: string) => m.get(k) ?? null,
    setItem: (k: string, v: string) => void m.set(k, v),
    removeItem: (k: string) => void m.delete(k),
    m,
  };
}

const json = (body: unknown, init: ResponseInit = {}) =>
  new Response(JSON.stringify(body), { status: 200, ...init, headers: { "Content-Type": "application/json", ...((init.headers as Record<string, string>) ?? {}) } });

type FetchArgs = [string, RequestInit | undefined];

describe("api client", () => {
  it("builds query strings without empty values", () => {
    expect(queryString({ a: 1, b: "", c: null, d: undefined, e: false, f: "x y" })).toBe("?a=1&e=false&f=x+y");
    expect(queryString({})).toBe("");
  });

  it("reads FastAPI error details", () => {
    expect(errorMessage(404, "Not Found", { detail: "run not found" })).toBe("run not found");
    expect(errorMessage(422, "Unprocessable", { detail: [{ msg: "field required" }, { msg: "bad" }] })).toBe("field required; bad");
    expect(errorMessage(500, "Server Error", null)).toBe("500 Server Error");
  });

  it("parses download filenames", () => {
    expect(filenameFrom('attachment; filename="run3_cleaned.csv"', "x")).toBe("run3_cleaned.csv");
    expect(filenameFrom("attachment; filename*=UTF-8''r%C3%A9sum%C3%A9.md", "x")).toBe("résumé.md");
    expect(filenameFrom(null, "fallback.json")).toBe("fallback.json");
  });

  it("sends the stored key and reads X-Total-Count", async () => {
    const calls: FetchArgs[] = [];
    const fetch = async (url: string, init?: RequestInit) => {
      calls.push([url, init]);
      return json([{ id: 1 }, { id: 2 }], { headers: { "X-Total-Count": "57" } });
    };
    const client = createClient({ fetch: fetch as typeof globalThis.fetch, storage: memoryStorage({ [KEY_STORE]: "s3cret" }) });
    const out = await client.list<{ id: number }>("/api/runs", { limit: 2, status: "" });
    expect(out).toEqual({ items: [{ id: 1 }, { id: 2 }], total: 57 });
    expect(calls[0][0]).toBe("/api/runs?limit=2");
    expect((calls[0][1]?.headers as Record<string, string>)["X-API-Key"]).toBe("s3cret");
  });

  it("raises ApiError with the server's message", async () => {
    const client = createClient({ fetch: (async () => json({ detail: "run not found" }, { status: 404, statusText: "Not Found" })) as typeof globalThis.fetch, storage: null });
    await expect(client.get("/api/runs/9")).rejects.toMatchObject({ name: "ApiError", status: 404, message: "run not found" });
    expect(new ApiError(0, "x")).toBeInstanceOf(Error);
  });

  it("asks for a key once on 401, stores it and retries", async () => {
    const storage = memoryStorage();
    let calls = 0;
    const fetch = async (_url: string, init?: RequestInit) => {
      calls += 1;
      const key = (init?.headers as Record<string, string> | undefined)?.["X-API-Key"];
      return key === "good" ? json({ ok: true }) : json({ detail: "Missing or invalid API key" }, { status: 401 });
    };
    const client = createClient({ fetch: fetch as typeof globalThis.fetch, storage });
    const prompt = vi.fn(async () => "good");
    client.onKeyRequired(prompt);
    const [a, b] = await Promise.all([client.get("/api/summary"), client.get("/api/health/overview")]);
    expect(a).toEqual({ ok: true });
    expect(b).toEqual({ ok: true });
    expect(prompt).toHaveBeenCalledTimes(1);
    expect(storage.m.get(KEY_STORE)).toBe("good");
    expect(calls).toBe(4);
    expect(client.hasKey).toBe(true);
  });

  it("gives up when the key prompt is dismissed", async () => {
    const client = createClient({ fetch: (async () => json({ detail: "Missing or invalid API key" }, { status: 401 })) as typeof globalThis.fetch, storage: null });
    client.onKeyRequired(async () => null);
    await expect(client.get("/api/summary")).rejects.toMatchObject({ status: 401 });
  });

  it("polls a job until it finishes", async () => {
    const states: Partial<Job>[] = [
      { status: "queued", progress: 0 },
      { status: "running", progress: 0.3 },
      { status: "success", progress: 1 },
    ];
    let i = 0;
    const client = { get: async <T,>() => ({ id: "j1", ...states[Math.min(i++, states.length - 1)] }) as T };
    const seen: string[] = [];
    const done = await waitForJob(client, "j1", { interval: 1, onUpdate: (j) => seen.push(j.status) });
    expect(done.status).toBe("success");
    expect(seen).toEqual(["queued", "running", "success"]);
  });
});
