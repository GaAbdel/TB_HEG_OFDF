"""Tests de l'orchestration de collecte sans navigateur.

On pré-capture le HTML du faux marché dans un corpus, puis on injecte un
`fetch` qui y puise. On prouve ainsi : (1) qu'un balayage complet ramène les
284 annonces, (2) que le budget agit en coupe-circuit (collecte partielle).
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


def _build_corpus() -> dict[str, str]:
    """Capture toutes les pages utiles du faux marché (une fois)."""
    client = TestClient(fm.app)
    corpus: dict[str, str] = {}
    page = 1
    while True:
        text = client.get(f"/search?page={page}").text
        corpus[f"/search?page={page}"] = text
        if "page-next" not in text:
            break
        page += 1
    listings = json.loads((ROOT / "fake_market" / "listings.json").read_text(encoding="utf-8"))
    for it in listings:
        corpus[f"/listing/{it['id']}"] = client.get(f"/listing/{it['id']}").text
    return corpus


CORPUS = _build_corpus()


def _make_fetch(g: Guardrails):
    async def fetch(url: str) -> str:
        g.consume_action()                 # mime la consommation de budget réelle
        return CORPUS[url.removeprefix(BASE)]
    return fetch


def test_balayage_complet():
    g = Guardrails(allowlist=["fake_market"], action_budget=1000)
    res = asyncio.run(collect(BASE, _make_fetch(g), concurrency=4))
    assert len(res) == 284
    assert all(r["title"] and r["external_id"] for r in res)


def test_budget_coupe_circuit():
    g = Guardrails(allowlist=["fake_market"], action_budget=30)
    res = asyncio.run(collect(BASE, _make_fetch(g), concurrency=4))
    assert 0 < len(res) < 284          # arrêt anticipé -> collecte partielle
    assert g.can_act() is False         # budget épuisé