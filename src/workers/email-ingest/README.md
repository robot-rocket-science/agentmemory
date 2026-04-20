# Email Ingest Worker

Cloudflare Email Worker that receives telemetry submissions at `data@robotrocketscience.com`.

## What it does

1. Parses inbound email (body + attachments) for JSONL telemetry snapshots
2. Validates each snapshot against the agentmemory telemetry schema (v=1)
3. Stores valid snapshots in D1 (`agentmemory-telemetry` database)
4. Forwards the original email to Gmail as notification

## Deploy

```bash
cd workers/email-ingest
npm install
npx wrangler deploy
```

The worker name `worker-name` matches what's configured in Cloudflare Email Routing
for `data@robotrocketscience.com`.

## Local dev

```bash
npm install
npx wrangler dev
```

Test with:
```bash
curl -X POST 'http://localhost:8787/cdn-cgi/handler/email' \
  --url-query 'from=test@example.com' \
  --url-query 'to=data@robotrocketscience.com' \
  --header 'Content-Type: application/json' \
  --data-raw 'From: test@example.com
To: data@robotrocketscience.com
Subject: telemetry submission
Content-Type: text/plain

{"v":1,"ts":"2026-04-17T00:00:00Z","session":{},"feedback":{},"beliefs":{},"graph":{},"window_7":{},"window_30":{}}'
```

## Infrastructure

- **Worker name**: `worker-name`
- **D1 database**: `agentmemory-telemetry` (`d1-database-id-old`)
- **Email route**: `data@robotrocketscience.com` -> this worker
- **Forward**: all emails also forwarded to `user@example.com`
