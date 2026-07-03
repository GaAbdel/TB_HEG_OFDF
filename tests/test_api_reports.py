"""Tests des endpoints de restitution : GET /reports/{run_id} et GET /ui."""

from __future__ import annotations

from fastapi.testclient import TestClient

from osint.api.main import app, get_reader

_RUN_DATA = {
    "run": {"run_id": 9, "mode": "B"},
    "listings": [
        {"id": 1, "title": "Ivoire sculpté — défense", "category": "cites",
         "suspicion_score": "0.950", "price_amount": "484.00", "price_currency": "CHF",
         "platform": "ANIBIS.CH", "location": "Vaud", "url": "http://x/1",
         "rationale": "Vente d'ivoire soumise à la réglementation CITES.",
         "content_hash": "abc123def456"},
    ],
}


class _FakeReader:
    def get_run_report(self, run_id):
        return _RUN_DATA if run_id == 9 else None


client = TestClient(app)


def test_rapport_html():
    app.dependency_overrides[get_reader] = lambda: _FakeReader()
    r = client.get("/reports/9")
    assert r.status_code == 200
    assert "text/html" in r.headers["content-type"]
    assert "Rapport d'analyse" in r.text
    assert "réglementation CITES" in r.text       # la justification est rendue
    app.dependency_overrides.pop(get_reader, None)


def test_rapport_json():
    app.dependency_overrides[get_reader] = lambda: _FakeReader()
    r = client.get("/reports/9?format=json")
    assert r.status_code == 200
    body = r.json()
    assert body["synthese"]["revision"] == 1      # 0.95 >= seuil de révision
    assert body["annonces"][0]["categorie"] == "cites"
    app.dependency_overrides.pop(get_reader, None)


def test_rapport_run_introuvable_404():
    app.dependency_overrides[get_reader] = lambda: _FakeReader()
    assert client.get("/reports/999").status_code == 404
    app.dependency_overrides.pop(get_reader, None)


def test_console_ui_servie():
    r = client.get("/ui")
    assert r.status_code == 200
    assert "Console d'analyse" in r.text
    assert "Lancer la recherche" in r.text          # la barre de recherche est là
    assert "langage naturel" in r.text              # l'aide à l'enquêteur
    assert "à venir" in r.text                       # les fonctions futures sont grisées