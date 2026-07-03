"""Tests de la CLASSE SelectorBasedExtractor : collecte, détection de rupture,
et réparation LLM-CODE de bout en bout (complète test_selector_extractor.py qui
teste les fonctions de sélecteurs).

Convention du projet : pas de pytest-asyncio ; `asyncio.run(...)`.
"""

from __future__ import annotations

import asyncio

import pytest

from osint.analyse.code_repair import repair_selectors
from osint.collecte.guardrails import Guardrails
from osint.collecte.selector_based_extractor import (
    ExtractorBrokenError,
    SelectorBasedExtractor,
    _parse_price,
)
from osint.collecte.selector_extractor import V1_SELECTORS

BASE = "http://mock"
_LIST = "<div class='grid'><a class='card' href='/shop/listing/1'>Ivoire</a></div>"

_DETAIL_V1 = (
    "<article class='listing card'>"
    "<h1 class='listing-title'>Statuette en ivoire</h1>"
    "<div class='listing-price price'>380 CHF</div>"
    "<span class='seller'>brocante_vaud</span>"
    "<span class='location'>Lausanne</span>"
    "<div class='listing-description'>Ancienne piece sculptee.</div>"
    "</article>"
)
_DETAIL_V2 = (
    "<section class='product card'>"
    "<h2 class='product__name'>Statuette en ivoire</h2>"
    "<p class='product__price'><span class='amount'>380</span> "
    "<span class='currency'>CHF</span></p>"
    "<ul class='product__attrs'><li class='attr attr--seller'>brocante_vaud</li>"
    "<li class='attr attr--location'>Lausanne</li></ul>"
    "<div class='product__desc'>Ancienne piece sculptee.</div>"
    "</section>"
)
V2_SELECTORS = {
    "title": "h2.product__name", "price": ".product__price",
    "seller": ".attr--seller", "location": ".attr--location",
    "description": ".product__desc",
}


def _make_fetch(detail_html: str):
    async def fetch(url: str) -> str:
        return _LIST if url.endswith("/shop") else detail_html
    return fetch


def _extractor(selectors):
    g = Guardrails(allowlist=["mock"], action_budget=50)
    return SelectorBasedExtractor(BASE, g, selectors=selectors, list_path="/shop")


def test_extraction_v1_reussie():
    ext = _extractor(dict(V1_SELECTORS))
    records = asyncio.run(ext._collect(_make_fetch(_DETAIL_V1)))
    assert len(records) == 1
    r = records[0]
    assert r["title"] == "Statuette en ivoire"
    assert r["price_amount"] == 380.0
    assert r["price_currency"] == "CHF"
    assert r["external_id"] == "1"
    assert r["url"].endswith("/shop/listing/1")


def test_rupture_v2_leve_erreur():
    ext = _extractor(dict(V1_SELECTORS))
    with pytest.raises(ExtractorBrokenError) as exc:
        asyncio.run(ext._collect(_make_fetch(_DETAIL_V2)))
    assert "product__name" in exc.value.sample_html
    assert "title" in exc.value.missing


def test_reparation_llm_propose_v2():
    def fake_llm(html, selectors, missing):
        return {k: V2_SELECTORS[k] for k in missing if k in V2_SELECTORS}
    res = repair_selectors(fake_llm, _DETAIL_V2, dict(V1_SELECTORS), max_iters=3)
    assert res["ok"] is True
    assert res["selectors"]["title"] == "h2.product__name"
    assert res["record"]["title"] == "Statuette en ivoire"


def test_parse_price_variantes():
    assert _parse_price("380 CHF") == (380.0, "CHF")
    assert _parse_price("1'250 CHF") == (1250.0, "CHF")
    assert _parse_price("") == (None, None)