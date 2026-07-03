"""Tests de LLM-CODE  boucle de réparation avec LLM simulé.

On injecte un `llm_fn` factice : la boucle est testée sans appel modèle réel.
Cas couverts : convergence (le LLM propose les bons sélecteurs v2), abandon
gracieux (le LLM ne propose rien d'utile), no-op (déjà bon dès le départ).
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

from fastapi.testclient import TestClient

from osint.analyse.code_repair import repair_selectors
from osint.collecte.selector_extractor import V1_SELECTORS

ROOT = Path(__file__).parent.parent
_spec = importlib.util.spec_from_file_location("mock_shop_app", ROOT / "mock_shop" / "app.py")
shop = importlib.util.module_from_spec(_spec)
sys.modules["mock_shop_app"] = shop
_spec.loader.exec_module(shop)

CLIENT = TestClient(shop.app)
HTML_V1 = CLIENT.get("/v1/listing/1").text
HTML_V2 = CLIENT.get("/v2/listing/1").text

V2_FIX = {
    "title": "h2.product__name",
    "price": ".product__price",
    "description": ".product__desc",
}


def _stub_fix(html, current, missing):
    """LLM simulé : renvoie les bons sélecteurs v2 pour les champs manquants."""
    return {f: V2_FIX[f] for f in missing if f in V2_FIX}


def _stub_vide(html, current, missing):
    """LLM simulé incapable : ne propose jamais rien."""
    return {}


def test_convergence_repare_v2():
    res = repair_selectors(_stub_fix, HTML_V2, V1_SELECTORS, max_iters=3)
    assert res["ok"] is True
    assert res["missing"] == []
    assert "Montre automatique" in res["record"]["title"]
    assert res["iterations"] >= 1


def test_abandon_gracieux_si_aucune_proposition():
    res = repair_selectors(_stub_vide, HTML_V2, V1_SELECTORS, max_iters=3)
    assert res["ok"] is False
    assert res["missing"]                      # champs toujours manquants
    assert res["record"] is not None           # pas de crash, état renvoyé


def test_noop_si_deja_bon():
    res = repair_selectors(_stub_fix, HTML_V1, V1_SELECTORS, max_iters=3)
    assert res["ok"] is True
    assert res["iterations"] == 0              # aucune réparation nécessaire


def test_historique_trace_chaque_iteration():
    res = repair_selectors(_stub_fix, HTML_V2, V1_SELECTORS, max_iters=3)
    assert len(res["history"]) >= 2
    assert res["history"][0]["missing"]        # 1re passe : des manquants
    assert res["history"][-1]["missing"] == []  # dernière : réparé