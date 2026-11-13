// JSON API client. Adds the API key header, turns error bodies into ApiError,
// reads list totals from X-Total-Count and asks for a key once on a 401.

import type { Job } from "./types";

export const KEY_STORE = "ag.apiKey";

export class ApiError extends Error {
  status: number;
  body: unknown;
  constructor(status: number, message: string, body?: unknown) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.body = body;
  }
}

export type Params = Record<string, string | number | boolean | null | undefined>;

/** Build "?a=1&b=x", skipping empty values. */
export function queryString(params?: Params): string {
  if (!params) return "";
  const u = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) {
    if (v === undefined || v === null || v === "") continue;
    u.set(k, String(v));
  }
  const s = u.toString();
  return s ? `?${s}` : "";
}

/** The message in a FastAPI error body (`detail` may be a string or a list). */
export function errorMessage(status: number, statusText: string, body: unknown): string {
  const detail = body && typeof body === "object" ? (body as { detail?: unknown }).detail : undefined;
  if (typeof detail === "string" && detail) return detail;
  if (Array.isArray(detail)) {
    return detail
      .map((d) => (d && typeof d === "object" && "msg" in d ? String((d as { msg: unknown }).msg) : JSON.stringify(d)))
      .join("; ");
  }
  return `${status} ${statusText}`.trim();
}

/** Parse a filename out of a Content-Disposition header. */
export function filenameFrom(header: string | null, fallback: string): string {
  if (!header) return fallback;
  const star = /filename\*=(?:UTF-8'')?([^;]+)/i.exec(header);
  if (star) return decodeURIComponent(star[1].trim().replace(/^"|"$/g, ""));
  const plain = /filename="?([^";]+)"?/i.exec(header);
  return plain ? plain[1] : fallback;
}

interface Storage {
  getItem(key: string): string | null;
  setItem(key: string, value: string): void;
  removeItem(key: string): void;
}

export interface ClientOptions {
  fetch?: typeof fetch;
  storage?: Storage | null;
}

export type KeyPrompt = () => Promise<string | null>;

export function createClient({ fetch: f, storage }: ClientOptions = {}) {
  const doFetch = f ?? ((...args: Parameters<typeof fetch>) => fetch(...args));
  let key = "";
  try {
    key = storage?.getItem(KEY_STORE) ?? "";
  } catch {
    key = "";
  }
  let prompt: KeyPrompt | null = null;
  let pending: Promise<string | null> | null = null;

  function setKey(next: string) {
    key = next;
    try {
      if (next) storage?.setItem(KEY_STORE, next);
      else storage?.removeItem(KEY_STORE);
    } catch {
      /* storage blocked: keep the key in memory for this tab */
    }
  }

  function headers(extra: Record<string, string> = {}): Record<string, string> {
    const h: Record<string, string> = { Accept: "application/json", ...extra };
    if (key) h["X-API-Key"] = key;
    return h;
  }

  /** Ask for a key once, even if several requests fail at the same time. */
  function askForKey(): Promise<string | null> {
    if (!prompt) return Promise.resolve(null);
    if (!pending) {
      pending = prompt().finally(() => {
        pending = null;
      });
    }
    return pending;
  }

  async function raw(method: string, path: string, opts: { params?: Params; body?: unknown; retry?: boolean } = {}): Promise<Response> {
    const init: RequestInit = { method, headers: headers() };
    if (opts.body !== undefined) {
      init.headers = headers({ "Content-Type": "application/json" });
      init.body = JSON.stringify(opts.body);
    }
    const res = await doFetch(path + queryString(opts.params), init);
    if (res.status === 401 && opts.retry !== false) {
      const next = await askForKey();
      if (next) {
        setKey(next);
        return raw(method, path, { ...opts, retry: false });
      }
    }
    if (!res.ok) {
      let body: unknown = null;
      try {
        body = await res.json();
      } catch {
        /* not JSON */
      }
      throw new ApiError(res.status, errorMessage(res.status, res.statusText, body), body);
    }
    return res;
  }

  async function json<T>(method: string, path: string, opts: { params?: Params; body?: unknown } = {}): Promise<T> {
    const res = await raw(method, path, opts);
    if (res.status === 204) return null as T;
    return (await res.json()) as T;
  }

  return {
    get hasKey() {
      return Boolean(key);
    },
    setKey,
    onKeyRequired(fn: KeyPrompt | null) {
      prompt = fn;
    },
    get: <T>(path: string, params?: Params) => json<T>("GET", path, { params }),
    post: <T>(path: string, body?: unknown, params?: Params) => json<T>("POST", path, { body: body ?? {}, params }),
    put: <T>(path: string, body: unknown) => json<T>("PUT", path, { body }),
    del: <T>(path: string) => json<T>("DELETE", path),
    /** GET a list endpoint that reports its total in X-Total-Count. */
    async list<T>(path: string, params?: Params): Promise<{ items: T[]; total: number }> {
      const res = await raw("GET", path, { params });
      const items = (await res.json()) as T[];
      const header = res.headers.get("X-Total-Count");
      return { items, total: header === null ? items.length : Number(header) };
    },
    /** Fetch a file with the auth header and return it with its filename. */
    async file(path: string): Promise<{ blob: Blob; name: string }> {
      const res = await raw("GET", path);
      return { blob: await res.blob(), name: filenameFrom(res.headers.get("Content-Disposition"), path.split("/").pop() || "download") };
    },
    /** Check a key against /api/auth without storing it. */
    async checkKey(candidate: string): Promise<boolean> {
      try {
        const res = await doFetch("/api/auth", { headers: { Accept: "application/json", "X-API-Key": candidate } });
        const body = (await res.json()) as { authenticated?: boolean };
        return Boolean(body.authenticated);
      } catch {
        return false;
      }
    },
    /** Multipart upload with progress (XMLHttpRequest: fetch has no upload progress). */
    upload<T>(url: string, file: File, onProgress?: (fraction: number) => void): Promise<T> {
      const send = (retry: boolean): Promise<T> =>
        new Promise((resolve, reject) => {
          const xhr = new XMLHttpRequest();
          xhr.open("POST", url);
          if (key) xhr.setRequestHeader("X-API-Key", key);
          xhr.upload.onprogress = (e) => {
            if (e.lengthComputable && onProgress) onProgress(e.loaded / e.total);
          };
          xhr.onerror = () => reject(new ApiError(0, "Network error while uploading"));
          xhr.onload = async () => {
            let body: unknown = null;
            try {
              body = JSON.parse(xhr.responseText);
            } catch {
              /* not JSON */
            }
            if (xhr.status === 401 && retry) {
              const next = await askForKey();
              if (next) {
                setKey(next);
                resolve(send(false));
                return;
              }
            }
            if (xhr.status >= 200 && xhr.status < 300) resolve(body as T);
            else reject(new ApiError(xhr.status, errorMessage(xhr.status, xhr.statusText || "Upload failed", body), body));
          };
          const form = new FormData();
          form.append("file", file, file.name);
          xhr.send(form);
        });
      return send(true);
    },
  };
}

export type ApiClient = ReturnType<typeof createClient>;

function browserStorage(): Storage | null {
  try {
    return typeof window !== "undefined" ? window.localStorage : null;
  } catch {
    return null;
  }
}

export const api = createClient({ storage: browserStorage() });

export const FINISHED_JOB = ["success", "failed", "interrupted"] as const;

/** Poll a job until it finishes; resolves with the final record. */
export async function waitForJob(
  client: Pick<ApiClient, "get">,
  jobId: string,
  { onUpdate, interval = 600, signal }: { onUpdate?: (job: Job) => void; interval?: number; signal?: AbortSignal } = {},
): Promise<Job> {
  for (;;) {
    if (signal?.aborted) throw new DOMException("aborted", "AbortError");
    const job = await client.get<Job>(`/api/jobs/${jobId}`);
    onUpdate?.(job);
    if ((FINISHED_JOB as readonly string[]).includes(job.status)) return job;
    await new Promise((r) => setTimeout(r, interval));
  }
}

/** Save a blob through a temporary link. */
export function saveBlob(blob: Blob, name: string) {
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = name;
  document.body.append(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 2000);
}

export async function download(path: string): Promise<string> {
  const { blob, name } = await api.file(path);
  saveBlob(blob, name);
  return name;
}
