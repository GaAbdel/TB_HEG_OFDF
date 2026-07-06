"""Tests de l'extracteur Anibis (JSON-LD schema.org).

Le parsing est une fonction pure `parse_anibis_listing(html) -> dict|None` :
on la teste sur des fixtures reproduisant le JSON-LD réel relevé sur Anibis
(bloc Product + bloc WebPage/BreadcrumbList, comme sur les pages réelles).
La collecte est testée en injectant un `fetch` factice dans `collect`.
"""

from __future__ import annotations

import asyncio
import json

from osint.collecte.anibis_extractor import (
    collect,
    parse_anibis_listing,
    _external_id_from_url,
)

BASE = "https://www.anibis.ch"

# JSON-LD Product calqué sur le relevé réel (annonce Glenfiddich).
PRODUCT = {
    "@context": "https://schema.org",
    "@type": "Product",
    "name": "GLENFIDDISCH  25YO SINGLE MALT ORGINALVERPACKT",
    "url": f"{BASE}/fr/vi/soleure/maison/alimentation/glenfiddisch/53577445",
    "description": "DIE BIETEN AUF EINE FLASCHE GLENFIDDISCH 25 JAHRE WHISKY 70cl 43%",
    "image": "https://c.anibis.ch/big/5866400085.jpg",
    "offers": {
        "@type": "Offer",
        "itemCondition": "https://schema.org/UsedCondition",
        "priceCurrency": "CHF",
        "price": 420,
        "seller": {
            "@type": "Person",
            "name": "Vojislav Kostic",
            "address": {
                "@type": "PostalAddress",
                "postalCode": "5012",
                "addressLocality": "Schönenwerd",
                "addressCountry": "CH",
            },
        },
    },
}

# Bloc secondaire présent sur les vraies pages : ne doit PAS être pris pour le Product.
WEBPAGE = {"@context": "https://schema.org", "@type": "WebPage", "name": "x"}


def _detail_html(product: dict | None = PRODUCT, with_webpage: bool = True) -> str:
    blocks = []
    if with_webpage:
        blocks.append(
            f'<script type="application/ld+json">{json.dumps(WEBPAGE)}</script>'
        )
    if product is not None:
        blocks.append(
            f'<script type="application/ld+json">{json.dumps(product)}</script>'
        )
    return f"<html><head>{''.join(blocks)}</head><body>...</body></html>"


def _card(i: int) -> str:
    url = f"/fr/vi/zurich/maison/alimentation/annonce-{i}/{1000 + i}"
    return f'<div data-private-srp-listing-item-id="{1000 + i}"><a href="{url}">x</a></div>'


def _results_html(ids: list[int]) -> str:
    return f"<html><body>{''.join(_card(i) for i in ids)}</body></html>"


# --- Parsing pur -------------------------------------------------------------

def test_parse_extrait_tous_les_champs_du_jsonld():
    rec = parse_anibis_listing(_detail_html())
    assert rec is not None
    assert rec["title"] == "GLENFIDDISCH  25YO SINGLE MALT ORGINALVERPACKT"
    assert rec["price_amount"] == 420.0
    assert rec["price_currency"] == "CHF"
    assert rec["seller"] == "Vojislav Kostic"
    assert rec["location"] == "5012 Schönenwerd"
    assert rec["external_id"] == "53577445"
    assert "WHISKY" in rec["description"]


def test_parse_ignore_le_bloc_webpage_et_vise_le_product():
    # Même avec le bloc WebPage en premier, c'est le Product qui est extrait.
    rec = parse_anibis_listing(_detail_html(with_webpage=True))
    assert rec is not None and rec["title"].startswith("GLENFIDDISCH")


def test_parse_sans_product_renvoie_none():
    # Page sans bloc Product -> None (signal de rupture pour l'appelant).
    assert parse_anibis_listing(_detail_html(product=None)) is None


def test_parse_html_sans_jsonld_renvoie_none():
    assert parse_anibis_listing("<html><body>rien</body></html>") is None


def test_external_id_depuis_url():
    assert _external_id_from_url(f"{BASE}/fr/vi/x/y/z/53577445") == "53577445"
    assert _external_id_from_url(f"{BASE}/fr/vi/x/y/z/53577445?sid=1") == "53577445"
    assert _external_id_from_url(f"{BASE}/fr/seller?id=999") is None


# --- Collecte (fetch factice) ------------------------------------------------

def _make_site(pages: dict[int, list[int]]):
    """pages: {num_page: [ids annonces]}. Construit résultats + détails."""
    site: dict[str, str] = {}
    for page, ids in pages.items():
        url = f"{BASE}/fr/q/cherche/BLOB" if page == 1 else f"{BASE}/fr/q/cherche/BLOB?page={page}"
        site[url] = _results_html(ids)
        for i in ids:
            prod = dict(PRODUCT)
            prod = json.loads(json.dumps(PRODUCT))  # copie profonde
            prod["url"] = f"{BASE}/fr/vi/zurich/maison/alimentation/annonce-{i}/{1000 + i}"
            prod["name"] = f"Whisky lot {i}"
            site[f"{BASE}/fr/vi/zurich/maison/alimentation/annonce-{i}/{1000 + i}"] = _detail_html(prod)
    return site


def _run_collect(site: dict[str, str], **kw) -> list[dict]:
    calls: list[str] = []

    async def fetch(url: str) -> str:
        calls.append(url)
        return site[url]

    recs = asyncio.run(
        collect(BASE, fetch, list_path="/fr/q/cherche/BLOB", **kw)
    )
    return recs


def test_collect_multi_page_et_borne_max_listings():
    site = _make_site({1: [1, 2, 3], 2: [4, 5, 6]})
    recs = _run_collect(site, max_pages=2, max_listings=4)
    assert len(recs) == 4  # plafonné à 4 annonces
    assert all(r["external_id"] for r in recs)


def test_collect_respecte_max_pages():
    site = _make_site({1: [1, 2], 2: [3, 4], 3: [5, 6]})
    recs = _run_collect(site, max_pages=1, max_listings=0)
    assert len(recs) == 2  # seule la page 1


def test_collect_filtre_de_pertinence_sur_terms():
    site = _make_site({1: [1, 2, 3]})
    # Les titres sont « Whisky lot N » -> le terme « whisky » matche tout,
    # « vodka » ne matche rien. Site à une seule page -> max_pages=1.
    assert len(_run_collect(site, terms=["whisky"], max_pages=1)) == 3
    assert len(_run_collect(site, terms=["vodka"], max_pages=1)) == 0