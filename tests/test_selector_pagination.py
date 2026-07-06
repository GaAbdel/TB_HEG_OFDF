"""Tests de la pagination déclarative de SelectorBasedExtractor.

La structure du site (page de résultats, cartes, lien « suivant », plafond de
pages) est portée par des clés `_*` de la config de sélecteurs. Ces tests sont
autoportants : ils injectent un `fetch` factice dans `_collect` (aucun
navigateur, aucun garde-fou requis) et vérifient :

  1. le parcours multi-page suit `_next_page` et agrège les annonces ;
  2. `_max_pages` borne le parcours même si un lien « suivant » subsiste ;
  3. sans `_next_page`, comportement historique : une seule page ;
  4. `_external_id` est stable et insensible aux paramètres d'URL ;
  5. les clés `_*` ne fuient pas dans les champs d'extraction.
"""

from __future__ import annotations

import asyncio

from osint.collecte.selector_based_extractor import (
    SelectorBasedExtractor,
    _external_id,
)

BASE = "http://demo:8000"

FIELD_SELECTORS = {
    "title": "h1.t",
    "price": ".p",
    "description": ".d",
}


def _detail(n: int) -> str:
    return (
        f"<html><body><h1 class='t'>Annonce {n}</h1>"
        f"<span class='p'>{10 * n} CHF</span>"
        f"<p class='d'>Description {n}</p></body></html>"
    )


def _list_page(ids: list[int], next_href: str | None) -> str:
    cards = "".join(f"<a class='card' href='/item/{i}'>x</a>" for i in ids)
    nav = f"<a class='next' href='{next_href}'>Suivant</a>" if next_href else ""
    return f"<html><body>{cards}{nav}</body></html>"


def _make_site() -> dict[str, str]:
    """Trois pages de résultats chaînées, deux annonces chacune."""
    site = {
        f"{BASE}/search": _list_page([1, 2], "/search?page=2"),
        f"{BASE}/search?page=2": _list_page([3, 4], "/search?page=3"),
        f"{BASE}/search?page=3": _list_page([5, 6], None),
    }
    for i in range(1, 7):
        site[f"{BASE}/item/{i}"] = _detail(i)
    return site


def _extractor(selectors: dict) -> SelectorBasedExtractor:
    # guardrails=None : _collect ne les consulte pas (ils vivent dans
    # BrowserSession.fetch, remplacé ici par le fetch factice).
    return SelectorBasedExtractor(BASE, None, selectors=selectors)


def _run(extractor: SelectorBasedExtractor, site: dict[str, str]) -> list[dict]:
    calls: list[str] = []

    async def fetch(url: str) -> str:
        calls.append(url)
        return site[url]

    records = asyncio.run(extractor._collect(fetch))
    extractor._test_calls = calls  # inspection par les tests
    return records


def test_pagination_suit_next_page_et_agrege():
    sel = {
        **FIELD_SELECTORS,
        "_list_path": "/search",
        "_card_selector": "a.card",
        "_next_page": "a.next",
        "_max_pages": 3,
    }
    records = _run(_extractor(sel), _make_site())
    assert len(records) == 6
    assert [r["title"] for r in records] == [f"Annonce {i}" for i in range(1, 7)]


def test_max_pages_borne_le_parcours():
    sel = {
        **FIELD_SELECTORS,
        "_list_path": "/search",
        "_card_selector": "a.card",
        "_next_page": "a.next",
        "_max_pages": 2,  # la page 3 existe mais ne doit PAS être visitée
    }
    ext = _extractor(sel)
    records = _run(ext, _make_site())
    assert len(records) == 4
    assert f"{BASE}/search?page=3" not in ext._test_calls


def test_max_pages_accepte_une_chaine_jsonb():
    # Le JSONB peut livrer "2" (texte) : l'extracteur doit le tolérer.
    sel = {
        **FIELD_SELECTORS,
        "_list_path": "/search",
        "_card_selector": "a.card",
        "_next_page": "a.next",
        "_max_pages": "2",
    }
    records = _run(_extractor(sel), _make_site())
    assert len(records) == 4


def test_sans_next_page_comportement_mono_page():
    # Config historique (aucune clé `_*` de pagination) : une seule page,
    # même si le HTML contient un lien « suivant ».
    sel = {
        **FIELD_SELECTORS,
        "_list_path": "/search",
        "_card_selector": "a.card",
    }
    ext = _extractor(sel)
    records = _run(ext, _make_site())
    assert len(records) == 2
    assert f"{BASE}/search?page=2" not in ext._test_calls


def test_meta_keys_ne_fuient_pas_dans_les_champs():
    sel = {
        **FIELD_SELECTORS,
        "_list_path": "/search",
        "_card_selector": "a.card",
        "_next_page": "a.next",
        "_max_pages": 3,
    }
    ext = _extractor(sel)
    assert all(not k.startswith("_") for k in ext.selectors)
    assert ext.list_path == "/search"
    assert ext.card_selector == "a.card"
    assert ext.next_page_selector == "a.next"
    assert ext.max_pages == 3


def test_external_id_format_historique_preserve():
    assert _external_id("http://fake_market:8000/listing/1229") == "1229"


def test_external_id_capture_id_reel_plateforme():
    # Format Anibis relevé en reconnaissance : le segment final est l'ID réel
    # de l'annonce -> on le capture tel quel (traçabilité enquêteur).
    a = _external_id(
        "https://www.anibis.ch/fr/vi/vaud/maison/alimentation/nikka-whisky-70cl/54518054"
    )
    b = _external_id(
        "https://www.anibis.ch/fr/vi/vaud/maison/alimentation/nikka-whisky-70cl/54518054/"
    )
    c = _external_id(
        "https://www.anibis.ch/fr/vi/vaud/maison/alimentation/nikka-whisky-70cl/54518054?sid=42"
    )
    assert a == b == c == "54518054"   # stabilité inter-runs (dédup upsert)


def test_external_id_hash_en_dernier_recours():
    # URL sans identifiant numérique -> empreinte normalisée, stable.
    a = _external_id("https://exemple.ch/annonce/velo-electrique")
    b = _external_id("https://exemple.ch/annonce/velo-electrique?utm=x")
    assert a == b
    assert len(a) == 16
    assert a != _external_id("https://exemple.ch/annonce/autre-velo")


def test_max_listings_borne_le_nombre_d_annonces():
    sel = {
        **FIELD_SELECTORS,
        "_list_path": "/search",
        "_card_selector": "a.card",
        "_next_page": "a.next",
        "_max_pages": 3,
        "_max_listings": 3,  # 6 annonces disponibles -> 3 visitées/scorées
    }
    ext = _extractor(sel)
    records = _run(ext, _make_site())
    assert len(records) == 3
    # Les pages de détail au-delà du plafond ne sont même pas visitées.
    assert f"{BASE}/item/4" not in ext._test_calls


def test_cycle_de_pagination_interrompu():
    # Un lien « suivant » qui reboucle sur une page déjà vue ne doit pas
    # produire de boucle infinie ni de doublons.
    site = {
        f"{BASE}/search": _list_page([1, 2], "/search?page=2"),
        f"{BASE}/search?page=2": _list_page([3], "/search"),  # <- cycle
    }
    for i in (1, 2, 3):
        site[f"{BASE}/item/{i}"] = _detail(i)
    sel = {
        **FIELD_SELECTORS,
        "_list_path": "/search",
        "_card_selector": "a.card",
        "_next_page": "a.next",
        "_max_pages": 10,
    }
    records = _run(_extractor(sel), site)
    assert len(records) == 3


def test_rupture_emporte_les_metadonnees_pour_la_reparation():
    import pytest
    from osint.collecte.selector_based_extractor import ExtractorBrokenError

    # Sélecteurs de champs volontairement faux -> rupture massive.
    sel = {
        "title": "h1.inexistant",
        "price": ".inexistant",
        "description": ".inexistant",
        "_list_path": "/search",
        "_card_selector": "a.card",
        "_next_page": "a.next",
        "_max_pages": 2,
    }
    with pytest.raises(ExtractorBrokenError) as exc_info:
        _run(_extractor(sel), _make_site())
    exc = exc_info.value
    # La réparation LLM-CODE ne porte que sur les champs...
    assert all(not k.startswith("_") for k in exc.selectors)
    # ...mais les métadonnées de navigation voyagent avec l'exception, pour
    # être refusionnées dans le candidat (pas de régression à l'approbation).
    assert exc.meta.get("_list_path") == "/search"
    assert exc.meta.get("_next_page") == "a.next"


# --- Pagination par construction d'URL (_page_param, cas Anibis) -------------

def _make_indexed_site(pages: int, per_page: int = 2, param: str = "?page="):
    """Site paginé par index d'URL : page 1 = /search, page N = /search?page=N."""
    site: dict[str, str] = {}
    idc = 1
    ids_by_page: list[list[int]] = []
    for p in range(1, pages + 1):
        ids = list(range(idc, idc + per_page))
        ids_by_page.append(ids)
        idc += per_page
        url = f"{BASE}/search" if p == 1 else f"{BASE}/search{param}{p}"
        site[url] = _list_page(ids, None)  # pas de lien « suivant » : c'est l'URL qui indexe
    # une page au-delà de la dernière : vide (0 carte)
    site[f"{BASE}/search{param}{pages + 1}"] = _list_page([], None)
    for ids in ids_by_page:
        for i in ids:
            site[f"{BASE}/item/{i}"] = _detail(i)
    return site


def test_pagination_par_url_construit_les_pages():
    sel = {
        **FIELD_SELECTORS,
        "_list_path": "/search",
        "_card_selector": "a.card",
        "_page_param": "?page=",
        "_max_pages": 3,
    }
    ext = _extractor(sel)
    records = _run(ext, _make_indexed_site(3))
    assert len(records) == 6
    assert f"{BASE}/search?page=2" in ext._test_calls
    assert f"{BASE}/search?page=3" in ext._test_calls


def test_pagination_par_url_s_arrete_sur_page_vide():
    # 2 pages réelles, _max_pages=5 : la boucle doit s'arrêter en trouvant la
    # page 3 vide, sans aller jusqu'à 5.
    sel = {
        **FIELD_SELECTORS,
        "_list_path": "/search",
        "_card_selector": "a.card",
        "_page_param": "?page=",
        "_max_pages": 5,
    }
    ext = _extractor(sel)
    records = _run(ext, _make_indexed_site(2))
    assert len(records) == 4
    assert f"{BASE}/search?page=4" not in ext._test_calls
    assert f"{BASE}/search?page=5" not in ext._test_calls


def test_page_param_prioritaire_et_dans_meta():
    sel = {
        **FIELD_SELECTORS,
        "_list_path": "/search",
        "_card_selector": "a.card",
        "_page_param": "?page=",
        "_max_pages": 2,
    }
    ext = _extractor(sel)
    assert ext.page_param == "?page="
    assert ext.meta.get("_page_param") == "?page="