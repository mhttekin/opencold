"""OpenCold HTTP API — exposes the `run` pipeline as an async job, plus send.

This is a PRIVATE service: it is not meant to be reachable from the public
internet. Every /v1 route requires a bearer token (OPENCOLD_API_SECRET); the
Next.js BFF is the only intended caller. No request bodies are logged, so the
user's LLM key and SMTP password never hit disk or logs.

Run it with:
    OPENCOLD_API_SECRET=... uvicorn main:app --app-dir server --workers 1
"""

from __future__ import annotations

import asyncio
from dataclasses import asdict

from fastapi import Depends, FastAPI, HTTPException

from opencold import sender

from auth import require_bearer
from jobs import JOBS, run_job
from models import (
    JobAccepted,
    JobStatus,
    RunRequest,
    SendRequest,
    SendResponse,
    SendResult,
    SmtpIn,
)

app = FastAPI(title="OpenCold API", version="0.1.0")

# Keep references to fire-and-forget job tasks so they aren't garbage-collected
# mid-flight (run_job handles its own errors, so they never reject).
_background_tasks: set[asyncio.Task] = set()


@app.get("/healthz")
def healthz() -> dict:
    return {"ok": True}


@app.post(
    "/v1/run",
    status_code=202,
    response_model=JobAccepted,
    dependencies=[Depends(require_bearer)],
)
async def run(req: RunRequest) -> JobAccepted:
    """Start a draft-generation job and return its id immediately."""
    job = JOBS.create()
    # The pipeline is blocking and spawns its own thread pool, so run it off the
    # event loop. The worker updates the job store; the client polls for results.
    task = asyncio.create_task(asyncio.to_thread(run_job, job.id, req))
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)
    return JobAccepted(job_id=job.id)


@app.get(
    "/v1/run/{job_id}",
    response_model=JobStatus,
    dependencies=[Depends(require_bearer)],
)
def run_status(job_id: str) -> JobStatus:
    job = JOBS.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="job not found")
    data = asdict(job)
    data["job_id"] = data.pop("id")
    return JobStatus(**data)


@app.post(
    "/v1/send",
    response_model=SendResponse,
    dependencies=[Depends(require_bearer)],
)
def send(req: SendRequest) -> SendResponse:
    """Send the selected drafts via the caller-supplied SMTP credentials."""
    smtp_config = req.smtp.model_dump()
    results: list[SendResult] = []
    for item in req.items:
        try:
            sender.send_email(smtp_config, item.email, item.name, item.subject, item.body)
            results.append(SendResult(email=item.email, sent=True))
        except Exception as e:  # noqa: BLE001 — reported per-row
            results.append(SendResult(email=item.email, sent=False, error=str(e)[:200]))
    sent = sum(1 for r in results if r.sent)
    return SendResponse(results=results, sent=sent, failed=len(results) - sent)


@app.post("/v1/smtp/test", dependencies=[Depends(require_bearer)])
def smtp_test(smtp: SmtpIn) -> dict:
    """Verify SMTP credentials without sending anything."""
    error = sender.test_connection(smtp.model_dump())
    return {"ok": error is None, "error": error}
