"""Tests de POST /search et GET /search/{id} runner simulé.

Le pipeline réel est remplacé par un faux runner (dependency_overrides) : on
teste le cycle 202 -> job_id -> statut, le succès, l'erreur et le 404, sans
LLM, navigateur ni base.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from osint.api.jobs import DONE, ERROR, PENDING, JobStore
from osint.api.main import app, get_search_runner


# --- JobStore (pur) ---------------------------------------------------------
def test_jobstore_cycle():
    store = JobStore()
    job = store.create({"seeds": ["cigarettes"]})
    assert job.status == PENDING
    store.mark_running(job.id)
    store.mark_done(job.id, {"collected": 9})
    got = store.get(job.id)
    assert got.status == DONE and got.result == {"collected": 9}


def test_jobstore_inconnu():
    assert JobStore().get("inexistant") is None


# --- Routes (runner simulé) -------------------------------------------------
async def _runner_ok(params):
    return {"run_id": 1, "terms": 34, "collected": 9, "scored": 9}


async def _runner_ko(params):
    raise RuntimeError("collecte impossible")


client = TestClient(app)


def test_post_search_renvoie_202_et_job_id():
    app.dependency_overrides[get_search_runner] = lambda: _runner_ok
    r = client.post("/search", json={"seeds": ["cigarettes", "ivoire"]})
    assert r.status_code == 202
    body = r.json()
    assert "job_id" in body and body["status"] == "pending"
    app.dependency_overrides.pop(get_search_runner, None)


def test_cycle_complet_succes():
    app.dependency_overrides[get_search_runner] = lambda: _runner_ok
    job_id = client.post("/search", json={"seeds": ["cigarettes"]}).json()["job_id"]
    # En TestClient, la tâche de fond s'exécute avant le retour : le job est fini.
    status = client.get(f"/search/{job_id}").json()
    assert status["status"] == DONE
    assert status["result"]["collected"] == 9
    app.dependency_overrides.pop(get_search_runner, None)


def test_cycle_complet_erreur():
    app.dependency_overrides[get_search_runner] = lambda: _runner_ko
    job_id = client.post("/search", json={"seeds": ["x"]}).json()["job_id"]
    status = client.get(f"/search/{job_id}").json()
    assert status["status"] == ERROR
    assert "impossible" in status["error"]
    app.dependency_overrides.pop(get_search_runner, None)


def test_statut_job_inconnu_404():
    assert client.get("/search/inexistant").status_code == 404