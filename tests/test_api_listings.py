"""Tests des endpoints GET /listings et /listings/{id}.

Le lecteur est remplacé par un faux (dependency_overrides) : on teste le
routage, la sérialisation, le filtre min_score et le 404, sans base de données.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from osint.api.main import app, get_reader

_ROWS = [
    {"id": 1, "title": "Cartouches de cigarettes", "price_amount": 380.0,
     "price_currency": "CHF", "url": None, "platform": "fake_market",
     "category": "tabac", "suspicion_score": 0.95},
    {"id": 2, "title": "Canapé gris", "price_amount": 300.0,
     "price_currency": "CHF", "url": None, "platform": "fake_market",
     "category": "aucune", "suspicion_score": 0.0},
]


class _FakeReader:
    def list_listings(self, *, limit, offset, min_score, run_id=None, category=None):
        data = _ROWS
        if run_id is not None:
            data = [r for r in data if r.get("run_id") == run_id]
        if category is not None:
            data = [r for r in data if r.get("category") == category]
        if min_score is not None:
            data = [r for r in data if (r["suspicion_score"] or 0) >= min_score]
        return data[offset: offset + limit]

    def list_runs(self):
        return [{"run_id": 9, "mode": "B", "status": "completed", "stats": {"scored": 2}}]

    def add_review(self, *, listing_id, decision, investigator_ref, comment=None, category_corrected=None):
        # enregistre l'appel pour vérification, renvoie un id simulé
        _FakeReader.last_review = {"listing_id": listing_id, "decision": decision,
                                   "investigator_ref": investigator_ref}
        return 123

    def get_listing(self, listing_id):
        if listing_id == 1:
            return {"listing": {"id": 1, "title": "Cartouches de cigarettes",
                                "platform": "fake_market", "price_amount": 380.0},
                    "score": {"category": "tabac", "suspicion_score": 0.95,
                              "rationale": "non taxées"}}
        return None


app.dependency_overrides[get_reader] = lambda: _FakeReader()
client = TestClient(app)


def test_list_renvoie_les_annonces():
    r = client.get("/listings")
    assert r.status_code == 200
    body = r.json()
    assert body["count"] == 2
    assert body["items"][0]["title"] == "Cartouches de cigarettes"


def test_list_filtre_min_score():
    r = client.get("/listings", params={"min_score": 0.5})
    assert r.status_code == 200
    body = r.json()
    assert body["count"] == 1 and body["items"][0]["category"] == "tabac"


def test_detail_trouve():
    r = client.get("/listings/1")
    assert r.status_code == 200
    body = r.json()
    assert body["listing"]["id"] == 1
    assert body["score"]["category"] == "tabac"


def test_detail_introuvable_404():
    r = client.get("/listings/999")
    assert r.status_code == 404


def test_min_score_hors_bornes_rejete():
    assert client.get("/listings", params={"min_score": 2}).status_code == 422


def test_endpoint_runs():
    r = client.get("/runs")
    assert r.status_code == 200
    body = r.json()
    assert body["count"] == 1 and body["items"][0]["run_id"] == 9


def test_filtre_par_run_id_passe_au_lecteur():
    # run_id=9 n'existe pas dans _ROWS (pas de clé run_id) -> liste vide attendue
    r = client.get("/listings?run_id=9")
    assert r.status_code == 200
    assert r.json()["count"] == 0


def test_review_enregistre_une_decision():
    r = client.post("/listings/1/review", json={"decision": "confirme", "investigator_ref": "agent42"})
    assert r.status_code == 201
    body = r.json()
    assert body["decision"] == "confirme" and body["feedback_id"] == 123
    assert _FakeReader.last_review["listing_id"] == 1


def test_review_decision_invalide_rejetee():
    r = client.post("/listings/1/review", json={"decision": "n_importe_quoi"})
    assert r.status_code == 422