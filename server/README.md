# OpenCold API

A small, **private** FastAPI service that wraps the `opencold` `run` pipeline so the
website can generate cold-email drafts. It is deliberately **not** part of the
`opencold` PyPI package (it lives outside the `opencold/` folder).

## Design

- **Stateless** — LLM provider credentials arrive in each request body. The service
  never reads or writes `~/.opencold/config.json` and never persists secrets.
- **Async jobs** — `POST /v1/run` returns a `job_id` immediately; poll
  `GET /v1/run/{job_id}` for status, progress, and results.
- **Bearer auth** — every `/v1` route requires `Authorization: Bearer $OPENCOLD_API_SECRET`.
  Meant to sit behind the Next.js BFF on a private network, never exposed publicly.

## Endpoints

| Method | Path                | Purpose                                            |
| ------ | ------------------- | -------------------------------------------------- |
| GET    | `/healthz`          | Liveness (unauthenticated)                         |
| POST   | `/v1/run`           | Start a draft-generation job → `202 {job_id}`      |
| GET    | `/v1/run/{job_id}`  | Job status / progress / results                    |
| POST   | `/v1/send`          | Send selected drafts via caller-supplied SMTP      |
| POST   | `/v1/smtp/test`     | Verify SMTP credentials without sending            |

## Run locally

```bash
# from the repo root
pip install -e .                       # the opencold package (core pipeline)
pip install -r server/requirements.txt # fastapi / uvicorn / pydantic

cp server/.env.example server/.env     # then set a real OPENCOLD_API_SECRET
export OPENCOLD_API_SECRET=dev-secret

uvicorn main:app --app-dir server --workers 1 --no-access-log
```

```bash
curl localhost:8000/healthz
curl -X POST localhost:8000/v1/run \
  -H "Authorization: Bearer dev-secret" -H "Content-Type: application/json" \
  -d '{"leads":[],"provider":{"type":"anthropic","api_key":"sk-...","model":"claude-sonnet-4-6"}}'
```

## Deploy

Build the container from the repo root and run it on a private network — only the
Next.js server should be able to reach it:

```bash
docker build -f server/Dockerfile -t opencold-api .
docker run -e OPENCOLD_API_SECRET=... -p 127.0.0.1:8000:8000 opencold-api
```

Single instance only (the job store is in-memory). For multiple replicas, replace
`JobStore` in `jobs.py` with Redis + a task queue; the route contract is unchanged.
