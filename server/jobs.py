"""In-memory async job store + background worker for draft generation.

Single-process only: the store lives in this uvicorn worker's memory, so run
with ``--workers 1``. For multi-replica deployments swap this for Redis + a task
queue (RQ/Celery) — the POST-then-poll contract the routes expose stays the same.
"""

from __future__ import annotations

import threading
import uuid
from dataclasses import dataclass
from typing import Optional

from opencold import pipeline

from models import RunRequest


@dataclass
class Job:
    id: str
    status: str = "queued"
    phase: Optional[str] = None
    progress: Optional[dict] = None
    results: Optional[list] = None
    error: Optional[str] = None


class JobStore:
    """Thread-safe in-memory map of job id → Job."""

    def __init__(self) -> None:
        self._jobs: dict[str, Job] = {}
        self._lock = threading.Lock()

    def create(self) -> Job:
        job = Job(id=uuid.uuid4().hex)
        with self._lock:
            self._jobs[job.id] = job
        return job

    def get(self, job_id: str) -> Optional[Job]:
        with self._lock:
            return self._jobs.get(job_id)

    def update(self, job_id: str, **fields) -> None:
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                return
            for key, value in fields.items():
                setattr(job, key, value)

    def evict_finished(self, keep: int = 200) -> None:
        """Bound memory by dropping the oldest finished jobs beyond ``keep``."""
        with self._lock:
            finished = [
                jid for jid, j in self._jobs.items() if j.status in ("succeeded", "failed")
            ]
            for jid in finished[: max(0, len(finished) - keep)]:
                self._jobs.pop(jid, None)


JOBS = JobStore()


def run_job(job_id: str, req: RunRequest) -> None:
    """Execute one generation job. Blocking — runs in a worker thread."""
    JOBS.update(job_id, status="running", phase="queued")

    def on_progress(event: dict) -> None:
        JOBS.update(
            job_id,
            phase=event.get("phase"),
            progress={
                "current": event.get("current"),
                "total": event.get("total"),
                "message": event.get("message"),
            },
        )

    try:
        result = pipeline.generate_drafts(
            req.leads,
            req.campaign.model_dump(),
            req.identity.model_dump(),
            req.profile.model_dump(),
            req.provider.model_dump(),
            progress=on_progress,
            **req.options.model_dump(),
        )
        JOBS.update(job_id, status="succeeded", phase="done", results=result.rows)
    except Exception as e:  # noqa: BLE001 — surfaced to the client, never raised here
        # Truncated, secret-free message (the pipeline never puts keys in exceptions).
        JOBS.update(job_id, status="failed", error=f"{type(e).__name__}: {str(e)[:200]}")
    finally:
        JOBS.evict_finished()
