"""Tests de l'extracteur par sélecteurs + du site mock_shop.

Prouve la prémisse de LLM-CODE : les sélecteurs v1 extraient correctement sur la
v1, mais échouent sur la v2 (structure changée). Les bons sélecteurs v2 réparent.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

from fastapi.testclient import TestClient

from osint.collecte.selector_extractor import (
    V1_SELECTORS,
    extract_with_selectors,
    missing_fields,
)

ROOT = Path(__file__).parent.parent
_spec = importlib.util.spec_from_file_location("mock_shop_app", ROOT / "mock_shop" / "app.py")
shop = importlib.util.module_from_spec(_spec)
sys.modules["mock_shop_app"] = shop
_spec.loader.exec_module(shop)

CLIENT = TestClient(shop.app)
HTML_V1 = CLIENT.get("/v1/listing/1").text
HTML_V2 = CLIENT.get("/v2/listing/1").text

V2_SELECTORS = {
    "title": "h2.product__name",
    "price": ".product__price",
    "seller": ".attr--seller",
    "location": ".attr--location",
    "description": ".product__desc",
}


def test_v1_selectors_extraient_sur_v1():
    rec = extract_with_selectors(HTML_V1, V1_SELECTORS)
    assert "Montre automatique" in rec["title"]
    assert "540" in rec["price"]
    assert missing_fields(rec) == []


def test_v1_selectors_cassent_sur_v2():
    rec = extract_with_selectors(HTML_V2, V1_SELECTORS)
    assert missing_fields(rec)            # champs requis manquants -> extracteur cassé


def test_v2_selectors_reparent_sur_v2():
    rec = extract_with_selectors(HTML_V2, V2_SELECTORS)
    assert "Montre automatique" in rec["title"]
    assert "540" in rec["price"]
    assert missing_fields(rec) == []


def test_pages_rendues_credibles():
    assert "<style>" in HTML_V1 and "Afficher le numéro" in HTML_V1
    assert "product__name" in HTML_V2 and "listing-title" not in HTML_V2