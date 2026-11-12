// JSON API client: adds the API key header, surfaces errors, handles 401 once.

const KEY_STORE = "ag.apiKey";

function readKey() {
  try { return localStorage.getItem(KEY_STORE) || ""; } catch { return ""; }
}

export function setKey(key) {
  try {
    if (key) localStorage.setItem(KEY_STORE, key);
    else localStorage.removeItem(KEY_STORE);
  } catch { /* storage blocked: the key lives only in memory for this tab */ }
  memoryKey = key || "";
}

let memoryKey = readKey();
export const hasKey = () => Boolean(memoryKey);

let keyPrompt = null; // set by app.js: () => Promise<string>
export function onKeyRequired(fn) { keyPrompt = fn; }

export class ApiError extends Error {
  constructor(status, message, body) {
    super(message);
    this.status = status;
    this.body = body;
  }
}

function headers(extra = {}) {
  const h = { Accept: "application/json", ...extra };
  if (memoryKey) h["X-API-Key"] = memoryKey;
  return h;
}

function qs(params) {
  if (!params) return "";
  const u = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) {
    if (v === undefined || v === null || v === "") continue;
    u.set(k, String(v));
  }
  const s = u.toString();
  return s ? `?${s}` : "";
}

async function detail(res) {
  let body = null;
  try { body = await res.json(); } catch { /* not JSON */ }
  let msg = body && body.detail;
  if (Array.isArray(msg)) msg = msg.map((d) => d.msg || JSON.stringify(d)).join("; ");
  return { body, msg: msg || `${res.status} ${res.statusText}` };
}

async function request(method, path, { params, body, raw = false, retry = true } = {}) {
  const init = { method, headers: headers() };
  if (body !== undefined) {
    init.headers["Content-Type"] = "application/json";
    init.body = JSON.stringify(body);
  }
  const res = await fetch(path + qs(params), init);
  if (res.status === 401 && retry && keyPrompt) {
    const key = await keyPrompt();
    if (key) {
      setKey(key);
      return request(method, path, { params, body, raw, retry: false });
    }
  }
  if (!res.ok) {
    const { body: b, msg } = await detail(res);
    throw new ApiError(res.status, msg, b);
  }
  if (raw) return res;
  if (res.status === 204) return null;
  return res.json();
}

export const api = {
  get: (path, params) => request("GET", path, { params }),
  post: (path, body, params) => request("POST", path, { body: body ?? {}, params }),
  put: (path, body) => request("PUT", path, { body }),
  del: (path) => request("DELETE", path),
  /** GET a list endpoint that reports its total in X-Total-Count. */
  async list(path, params) {
    const res = await request("GET", path, { params, raw: true });
    const items = await res.json();
    const total = Number(res.headers.get("X-Total-Count") ?? items.length);
    return { items, total };
  },
  /** Fetch a file with auth headers and hand it to the browser as a download. */
  async download(path) {
    const res = await request("GET", path, { raw: true });
    const blob = await res.blob();
    const cd = res.headers.get("Content-Disposition") || "";
    const m = /filename\*?=(?:UTF-8'')?"?([^";]+)"?/i.exec(cd);
    const name = m ? decodeURIComponent(m[1]) : path.split("/").pop();
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = name;
    document.body.append(a);
    a.click();
    a.remove();
    setTimeout(() => URL.revokeObjectURL(url), 2000);
    return name;
  },
  /** Multipart upload with progress (XMLHttpRequest, since fetch has no upload progress). */
  upload(file, onProgress) {
    const send = (retry) => new Promise((resolve, reject) => {
      const xhr = new XMLHttpRequest();
      xhr.open("POST", "/api/datasets");
      if (memoryKey) xhr.setRequestHeader("X-API-Key", memoryKey);
      xhr.upload.onprogress = (e) => { if (e.lengthComputable && onProgress) onProgress(e.loaded / e.total); };
      xhr.onerror = () => reject(new ApiError(0, "Network error while uploading"));
      xhr.onload = async () => {
        let body = null;
        try { body = JSON.parse(xhr.responseText); } catch { /* not JSON */ }
        if (xhr.status === 401 && retry && keyPrompt) {
          const key = await keyPrompt();
          if (key) { setKey(key); resolve(send(false)); return; }
        }
        if (xhr.status >= 200 && xhr.status < 300) resolve(body);
        else reject(new ApiError(xhr.status, (body && body.detail) || `Upload failed (${xhr.status})`, body));
      };
      const form = new FormData();
      form.append("file", file, file.name);
      xhr.send(form);
    });
    return send(true);
  },
};

/** Poll a job until it finishes. Resolves with the final job record. */
export async function waitForJob(jobId, { onUpdate, interval = 600, signal } = {}) {
  for (;;) {
    if (signal && signal.aborted) throw new DOMException("aborted", "AbortError");
    const job = await api.get(`/api/jobs/${jobId}`);
    if (onUpdate) onUpdate(job);
    if (["success", "failed", "interrupted"].includes(job.status)) return job;
    await new Promise((r) => setTimeout(r, interval));
  }
}
