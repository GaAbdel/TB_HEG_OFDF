"""Test du mode « termes » de collect() — LLM-EXPAND -> collecte ciblée.

Recherche `?q=terme` par terme, résultats dédupliqués. On vérifie : filtrage
effectif, déduplication, et terme sans correspondance.
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

from fastapi.testclient import TestClient

from osint.collecte.fake_market_extractor import collect
from osint.collecte.guardrails import Guardrails

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT / "fake_market"))
import app as fm  # noqa: E402

BASE = "http://fake_market:8000"


def _fetch(g: Guardrails, client: TestClient):
    async def f(url: str) -> str:
        g.consume_action()
        return client.get(url.removeprefix(BASE)).text
    return f


def _collect(terms):
    client = TestClient(fm.app)
    g = Guardrails(allowlist=["fake_market"], action_budget=5000)
    return asyncio.run(collect(BASE, _fetch(g, client), concurrency=4, terms=terms))


def _mot_present() -> str:
    listings = json.loads((ROOT / "fake_market" / "listings.json").read_text(encoding="utf-8"))
    return listings[0]["title"].split()[0].lower().strip(",.—-")


def test_terme_filtre_resultats():
    res = _collect([_mot_present()])
    assert 1 <= len(res) <= 284


def test_termes_dupliques_sont_dedupliques():
    mot = _mot_present()
    assert len(_collect([mot, mot])) == len(_collect([mot]))


def test_terme_sans_correspondance_donne_zero():
    assert _collect(["zzqxnotexistxyz"]) == []