#!/usr/bin/env python3
"""Marché factice — serveur FastAPI (harnais de dev/test, chapitre 5).

Imite un site d'annonces suisse : une page de résultats paginée et une page de
détail par annonce. Le HTML porte des classes CSS STABLES (`listing-card`,
`listing-title`, `listing-price`...) pour que les extracteurs Playwright aient
des sélecteurs fiables et déterministes.

Ce serveur est isolé du pipeline : il ne sert qu'à développer et évaluer la
collecte hors-ligne, sans jamais toucher aux vrais sites.
"""

from __future__ import annotations

import json
import re
from html import escape
from pathlib import Path

from fastapi import FastAPI, Query
from fastapi.responses import HTMLResponse


# --- Recherche tokenisée (comportement d'un vrai moteur de recherche) --------
_WORD_RE = re.compile(r"[a-z0-9àâäéèêëïîôöùûüç]+")

# Mots vides (FR/DE) ignorés : ils n'apportent rien à la recherche et, sans ce
# filtre, matcheraient presque toutes les annonces.
_STOPWORDS = {
    "de", "des", "du", "la", "le", "les", "un", "une", "et", "ou", "en", "au",
    "aux", "pour", "par", "avec", "sans", "sur", "dans", "que", "qui", "ses",
    "der", "die", "das", "und", "mit", "für", "den", "dem",
}


def _words(text: str) -> list[str]:
    return _WORD_RE.findall(text.lower())


def _significant_tokens(q: str) -> list[str]:
    """Mots de la requête utiles à la recherche (hors mots vides, longueur >= 3)."""
    return [w for w in _words(q) if len(w) >= 3 and w not in _STOPWORDS]


def _matches(tokens: list[str], item: dict) -> bool:
    """Vrai si un mot du titre/description commence par l'un des termes cherchés.

    Correspondance par PRÉFIXE dans un seul sens (le mot du texte commence par le
    terme), ce qui gère singulier/pluriel (« cartouche » -> « cartouches »). On
    n'utilise PAS le sens inverse (terme commence par le mot) : les apostrophes
    produisent des mots d'une lettre (« bureau d'angle » -> « d ») qui, sinon,
    matcheraient des termes comme « défense »/« dague » et ramèneraient la moitié
    du catalogue. La précision de la collecte est ainsi préservée.
    """
    text_words = set(_words(item["title"]) + _words(item["description"]))
    for tok in tokens:
        for w in text_words:
            if w == tok or w.startswith(tok):
                return True
    return False


HERE = Path(__file__).parent
LISTINGS: list[dict] = json.loads((HERE / "listings.json").read_text(encoding="utf-8"))
BY_ID: dict[int, dict] = {item["id"]: item for item in LISTINGS}
PAGE_SIZE = 20

app = FastAPI(title="Marché factice — OSINT OFDF")


def _page_html(title: str, body: str) -> str:
    return (
        "<!doctype html><html lang='fr'><head><meta charset='utf-8'>"
        f"<title>{escape(title)}</title></head><body>{body}</body></html>"
    )


@app.get("/healthz")
def healthz() -> dict[str, str]:
    return {"status": "ok", "listings": str(len(LISTINGS))}


@app.get("/", response_class=HTMLResponse)
def index() -> str:
    body = (
        "<h1>Marché factice</h1>"
        "<p><a href='/search'>Voir toutes les annonces</a></p>"
    )
    return _page_html("Marché factice", body)


@app.get("/search", response_class=HTMLResponse)
def search(
    q: str | None = Query(default=None, description="filtre texte (titre/description)"),
    page: int = Query(default=1, ge=1),
) -> str:
    items = LISTINGS
    if q:
        # Recherche tokenisée, à l'image d'un vrai moteur (Elasticsearch/Algolia) :
        # la requête est découpée en mots, et une annonce ressort si AU MOINS un
        # mot significatif correspond (OR). La correspondance par préfixe gère
        # les variantes singulier/pluriel (« cartouche » -> « cartouches »).
        tokens = _significant_tokens(q)
        if tokens:
            items = [it for it in LISTINGS if _matches(tokens, it)]
        else:
            needle = q.lower()
            items = [
                it for it in LISTINGS
                if needle in it["title"].lower() or needle in it["description"].lower()
            ]

    total = len(items)
    n_pages = max(1, (total + PAGE_SIZE - 1) // PAGE_SIZE)
    page = min(page, n_pages)
    start = (page - 1) * PAGE_SIZE
    chunk = items[start:start + PAGE_SIZE]

    cards = []
    for it in chunk:
        cards.append(
            "<div class='listing-card'>"
            f"<a class='listing-link' href='/listing/{it['id']}'>"
            f"<h2 class='listing-title'>{escape(it['title'])}</h2></a>"
            f"<span class='listing-price'>{it['price']} {escape(it['currency'])}</span>"
            f"<span class='listing-platform'>{escape(it['platform'])}</span>"
            "</div>"
        )

    # Pagination
    nav = []
    qp = f"q={escape(q)}&" if q else ""
    if page > 1:
        nav.append(f"<a class='page-prev' href='/search?{qp}page={page - 1}'>Précédent</a>")
    if page < n_pages:
        nav.append(f"<a class='page-next' href='/search?{qp}page={page + 1}'>Suivant</a>")

    body = (
        f"<h1>Résultats{f' pour « {escape(q)} »' if q else ''}</h1>"
        f"<p class='result-count'>{total} annonce(s) — page {page}/{n_pages}</p>"
        f"<div class='listing-list'>{''.join(cards)}</div>"
        f"<div class='pagination'>{' '.join(nav)}</div>"
    )
    return _page_html("Résultats", body)


@app.get("/listing/{listing_id}", response_class=HTMLResponse)
def listing(listing_id: int) -> HTMLResponse:
    it = BY_ID.get(listing_id)
    if it is None:
        return HTMLResponse(_page_html("Introuvable", "<h1>Annonce introuvable</h1>"), status_code=404)

    body = (
        "<article class='listing-detail'>"
        f"<h1 class='title'>{escape(it['title'])}</h1>"
        f"<div class='price'>{it['price']} {escape(it['currency'])}</div>"
        f"<div class='platform'>{escape(it['platform'])}</div>"
        f"<div class='seller'>Vendeur : {escape(it['seller'])}</div>"
        f"<div class='location'>Lieu : {escape(it['location'])}</div>"
        f"<div class='description'>{escape(it['description'])}</div>"
        f"<div class='external-id'>Référence : {it['id']}</div>"
        "</article>"
    )
    return HTMLResponse(_page_html(it["title"], body))