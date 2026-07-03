"""File de tâches en mémoire pour les recherches asynchrones (POST /search).

Une collecte complète (EXPAND -> collecte -> scoring) prend plusieurs minutes :
on ne la fait pas dans le cycle requête/réponse. POST /search crée un job et
répond immédiatement (202) ; le client suit l'avancement via GET /search/{id}.

Stockage en mémoire. Une mise à l'échelle réelle s'appuierait sur une file persistante (Celery/RQ/arq) perspective.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from threading import Lock
from typing import Any

PENDING, RUNNING, DONE, ERROR = "pending", "running", "done", "error"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class Job:
    id: str
    status: str
    params: dict
    created_at: str
    updated_at: str
    result: dict | None = None
    error: str | None = None

    def public(self) -> dict[str, Any]:
        return {
            "job_id": self.id,
            "status": self.status,
            "params": self.params,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "result": self.result,
            "error": self.error,
        }


class JobStore:
    """Stockage thread-safe des jobs (création, lecture, transitions d'état)."""

    def __init__(self) -> None:
        self._jobs: dict[str, Job] = {}
        self._lock = Lock()

    def create(self, params: dict) -> Job:
        job = Job(id=uuid.uuid4().hex, status=PENDING, params=params,
                  created_at=_now(), updated_at=_now())
        with self._lock:
            self._jobs[job.id] = job
        return job

    def get(self, job_id: str) -> Job | None:
        with self._lock:
            return self._jobs.get(job_id)

    def _set(self, job_id: str, **changes: Any) -> None:
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                return
            for k, v in changes.items():
                setattr(job, k, v)
            job.updated_at = _now()

    def mark_running(self, job_id: str) -> None:
        self._set(job_id, status=RUNNING)

    def mark_done(self, job_id: str, result: dict) -> None:
        self._set(job_id, status=DONE, result=result)

    def mark_error(self, job_id: str, error: str) -> None:
        self._set(job_id, status=ERROR, error=error)