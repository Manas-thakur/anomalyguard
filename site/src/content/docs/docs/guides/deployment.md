---
title: Deployment
description: Run the AnomalyGuard server in Docker or behind a reverse proxy, with an API key and CORS.
---

AnomalyGuard is a single-user tool: one server process, one SQLite database, one shared API key, no user accounts. These steps make it reachable from other machines without leaving it open.

## Checklist

- Set `ANOMALYGUARD_API_KEY` to a long random value.
- Keep the server on `127.0.0.1` behind a reverse proxy that terminates TLS, or bind `0.0.0.0` only inside a container or private network.
- Put the state directory (`.anomalyguard/`) on persistent storage and back it up.
- Run `anomalyguard doctor` in the deployment to check extras, state, pipelines and notifier secrets.
- For scheduled pipelines, run `anomalyguard run --schedule` as a separate supervised process in the same working directory.

## API key

```bash
export ANOMALYGUARD_API_KEY="$(python -c 'import secrets; print(secrets.token_urlsafe(32))')"
anomalyguard serve
```

With a key set, every `/api/*` request needs `X-API-Key: <key>` or `Authorization: Bearer <key>`; otherwise the server answers `401`. The web app asks for the key once and stores it in the browser's local storage. `/health`, `/api/auth` and the app's pages and assets stay open; `/api/docs` and `/api/openapi.json` need the key. Keys are compared in constant time.

`serve` prints a warning when it listens on a non-local address without a key.

## Docker

The image (`ghcr.io/manas-thakur/anomalyguard`, or `docker build -t anomalyguard .` from a clone) runs `anomalyguard serve --host 0.0.0.0 --port 8765` as user `anomalyguard` (uid 1000) in `/data`, and has a health check on `/health`.

```bash
docker run -d --name anomalyguard --restart unless-stopped \
  -p 127.0.0.1:8765:8765 \
  -e ANOMALYGUARD_API_KEY="$ANOMALYGUARD_API_KEY" \
  -v "$PWD/.anomalyguard:/data/.anomalyguard" \
  -v "$PWD/pipelines:/data/pipelines" \
  ghcr.io/manas-thakur/anomalyguard
```

- `/data/.anomalyguard` holds the database, uploads, analyses and the pipelines you create or edit in the web app (`/data/.anomalyguard/pipelines`), so this one volume keeps everything the server writes. The host folder must be writable by uid 1000.
- `/data/pipelines` is scanned for pipeline YAML you manage yourself (along with the bundled `/data/examples`). Data files the pipelines read must be mounted too, at the paths the YAML refers to (relative to the YAML file).
- The image sets `ANOMALYGUARD_PIPELINE_DIRS=/data/.anomalyguard/pipelines,/data/pipelines,/data/examples`; the first folder is where the web app writes new pipelines. Override the variable to change that.
- Publishing on `127.0.0.1:8765` keeps the port off the network so only the reverse proxy can reach it.

A scheduler next to the web app, sharing the same state:

```bash
docker run -d --name anomalyguard-scheduler --restart unless-stopped \
  -v "$PWD/.anomalyguard:/data/.anomalyguard" \
  -v "$PWD/pipelines:/data/pipelines" \
  ghcr.io/manas-thakur/anomalyguard run pipelines/orders.yaml --schedule
```

SQLite allows one writer at a time. A web server and one scheduler process sharing a database work, but do not point many concurrent writers at the same file.

## Reverse proxy

Terminate TLS at the proxy and forward to the local port. Uploads go through the proxy, so raise its body size limit to match `ANOMALYGUARD_MAX_UPLOAD_MB` (default 100).

**Caddy**

```
anomalyguard.example.com {
    reverse_proxy 127.0.0.1:8765
    request_body {
        max_size 100MB
    }
}
```

**nginx**

```nginx
server {
    listen 443 ssl;
    server_name anomalyguard.example.com;
    # ssl_certificate ...; ssl_certificate_key ...;

    client_max_body_size 100m;

    location / {
        proxy_pass http://127.0.0.1:8765;
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_read_timeout 300s;
    }
}
```

Serve the app at the root of a host name rather than under a sub-path.

## CORS

The web app talks to the API on the same origin and needs no CORS. To call the API from a page on another origin (your own dashboard, a notebook in the browser), list that origin:

```bash
export ANOMALYGUARD_CORS_ORIGINS="https://dash.example.com,http://localhost:3000"
```

Allowed methods are `GET`, `POST`, `PUT` and `DELETE`, allowed request headers `X-API-Key`, `Authorization` and `Content-Type`, and `X-Total-Count` and `Content-Disposition` are exposed to scripts. Requests from origins not on the list are refused by the browser. Without the variable, no cross-origin access is allowed.

## Resources

- Uploads are analysed **in memory** with pandas, so very large files need a machine with matching RAM.
- `ANOMALYGUARD_WORKERS` (default 2) sets how many analyses and pipeline runs execute at once.
- Each run stores up to `monitor.store_anomalies` findings (default 1,000). The database grows with run history; there is no automatic retention, so delete old state if it grows too large.

## Security headers

Every response carries `X-Content-Type-Options: nosniff`, `Referrer-Policy: same-origin` and `X-Frame-Options: DENY`. Upload names are sanitised, ids in paths are validated, and downloads are limited to known artifact names inside the state directory and pipeline folders.
