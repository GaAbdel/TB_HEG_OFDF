"""Tests d'extraction sur fixtures HTML statiques.

Ces tests démontren que le parsing produit les bons champs sans aucun
navigateur, c'est le filet qui détecte une régression d'extraction.
"""

from __future__ import annotations

from pathlib import Path

from osint.collecte.parsers import (
    next_page_url,
    parse_listing,
    parse_price,
    parse_search_results,
)

FIXTURES = Path(__file__).parent / "fixtures" / "fake_market"


def fixture(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


# --- parse_price -------------------------------------------------------------
def test_parse_price_simple():
    assert parse_price("484 CHF") == (484.0, "CHF")


def test_parse_price_inconnu():
    assert parse_price("prix à discuter") == (None, None)


# --- page de résultats -------------------------------------------------------
def test_resultats_compte_20():
    rows = parse_search_results(fixture("search_page1.html"))
    assert len(rows) == 20  # PAGE_SIZE


def test_resultats_champs():
    rows = parse_search_results(fixture("search_page1.html"))
    first = rows[0]
    assert first["external_id"] is not None
    assert first["url"].startswith("/listing/")
    assert first["title"]
    assert first["price_currency"] == "CHF"
    assert first["platform"] in {"ricardo", "anibis", "tutti"}


def test_page_suivante_existe():
    # page 1 sur 15 -> il doit y avoir un lien "suivant"
    assert next_page_url(fixture("search_page1.html")) is not None


# --- page de détail ----------------------------------------------------------
def test_detail_cites_explicite():
    d = parse_listing(fixture("listing_9004.html"))
    assert d["external_id"] == "9004"
    assert "Ivoire" in d["title"]
    assert d["price_amount"] == 484.0
    assert d["price_currency"] == "CHF"
    assert d["platform"] == "tutti"
    assert "certificat CITES" in d["description"]


def test_detail_piege_tagua():
    d = parse_listing(fixture("listing_8000.html"))
    assert "tagua" in d["title"].lower()
    assert "légale" in d["description"].lower()  # signal que c'est un leurre légal


def test_detail_benin():
    d = parse_listing(fixture("listing_1000.html"))
    assert d["external_id"] == "1000"
    assert d["seller"].startswith("vendeur")
    assert d["location"]