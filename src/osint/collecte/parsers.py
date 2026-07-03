"""Extraction déterministe : HTML brut -> annonces structurées.


"""

from __future__ import annotations

import re

from bs4 import BeautifulSoup

_PRICE_RE = re.compile(r"(\d[\d'’.,\s]*)\s*([A-Za-z]{3})")


def _text(node) -> str:
    return node.get_text(strip=True) if node else ""


def parse_price(raw: str) -> tuple[float | None, str | None]:
    """'484 CHF' -> (484.0, 'CHF'). Renvoie (None, None) si non reconnu."""
    m = _PRICE_RE.search(raw or "")
    if not m:
        return None, None
    digits = re.sub(r"[^\d.]", "", m.group(1).replace(",", "."))
    try:
        amount = float(digits) if digits else None
    except ValueError:
        amount = None
    return amount, m.group(2).upper()


def _after_colon(raw: str) -> str:
    """'Vendeur : alice' -> 'alice'."""
    return raw.split(":", 1)[1].strip() if ":" in raw else raw.strip()


def parse_search_results(html: str) -> list[dict]:
    """Extrait les annonces (résumé) d'une page de résultats.

    Renvoie une liste de dicts : external_id, url, title, price_amount,
    price_currency, platform.
    """
    soup = BeautifulSoup(html, "html.parser")
    results = []
    for card in soup.select(".listing-card"):
        link = card.select_one("a.listing-link")
        href = link.get("href") if link else None
        external_id = None
        if href:
            m = re.search(r"/listing/(\d+)", href)
            external_id = m.group(1) if m else None
        amount, currency = parse_price(_text(card.select_one(".listing-price")))
        results.append({
            "external_id": external_id,
            "url": href,
            "title": _text(card.select_one(".listing-title")),
            "price_amount": amount,
            "price_currency": currency,
            "platform": _text(card.select_one(".listing-platform")),
        })
    return results


def next_page_url(html: str) -> str | None:
    """URL de la page suivante (lien `.page-next`), ou None s'il n'y en a pas."""
    soup = BeautifulSoup(html, "html.parser")
    link = soup.select_one("a.page-next")
    return link.get("href") if link else None


def parse_listing(html: str) -> dict:
    """Extrait les champs structurés d'une page de détail d'annonce."""
    soup = BeautifulSoup(html, "html.parser")
    detail = soup.select_one(".listing-detail") or soup
    amount, currency = parse_price(_text(detail.select_one(".price")))
    return {
        "external_id": _after_colon(_text(detail.select_one(".external-id"))) or None,
        "title": _text(detail.select_one(".title")),
        "price_amount": amount,
        "price_currency": currency,
        "platform": _text(detail.select_one(".platform")),
        "seller": _after_colon(_text(detail.select_one(".seller"))),
        "location": _after_colon(_text(detail.select_one(".location"))),
        "description": _text(detail.select_one(".description")),
    }