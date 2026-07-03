"""Tests des endpoints Mode B (exploration) — runner simulé.

On teste la validation de l'allowlist (B-1) et le verrou de la recherche
autonome (B-2), sans LLM, navigateur ni base. Le vrai pipeline d'exploration
est remplacé par un faux runner via dependency_overrides.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from osint.api.jobs import DONE
from osint.api.main import app, get_explore_runner

client = TestClient(app)


async def _explore_ok(params):
    return {"run_id": 7, "collected": 5, "scored": 5}


def test_mode_b_sites_expose_allowlist_et_verrou():
    r = client.get("/mode-b/sites")
    assert r.status_code == 200
    body = r.json()
    labels = [s["label"] for s in body["sites"]]
    assert "Trovas" in labels                       # sites de l'allowlist présents
    assert body["autonomous_enabled"] is False     # verrou B-2 par défaut


def test_explore_site_autorise_renvoie_202():
    app.dependency_overrides[get_explore_runner] = lambda: _explore_ok
    r = client.post("/explore", json={"sites": ["Trovas"], "depth": "standard"})
    assert r.status_code == 202
    job_id = r.json()["job_id"]
    status = client.get(f"/search/{job_id}").json()   # même JobStore que /search
    assert status["status"] == DONE
    assert status["result"]["collected"] == 5
    app.dependency_overrides.pop(get_explore_runner, None)


def test_explore_site_non_autorise_rejete_422():
    app.dependency_overrides[get_explore_runner] = lambda: _explore_ok
    r = client.post("/explore", json={"sites": ["Le Bon Coin"]})
    assert r.status_code == 422
    assert "non autorisé" in r.json()["detail"]
    app.dependency_overrides.pop(get_explore_runner, None)


def test_explore_sans_site_rejete_422():
    app.dependency_overrides[get_explore_runner] = lambda: _explore_ok
    r = client.post("/explore", json={"sites": []})
    assert r.status_code == 422
    app.dependency_overrides.pop(get_explore_runner, None)


def test_mode_b2_recherche_autonome_verrouillee_403():
    app.dependency_overrides[get_explore_runner] = lambda: _explore_ok
    # Recherche autonome demandée alors que le verrou est actif -> refus propre.
    r = client.post("/explore", json={"sites": ["Trovas"], "autonomous": True})
    assert r.status_code == 403
    assert "non activé" in r.json()["detail"]
    app.dependency_overrides.pop(get_explore_runner, None)