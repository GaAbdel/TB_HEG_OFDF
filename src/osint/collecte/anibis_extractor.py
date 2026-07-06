"""Extracteur Anibis (Mode A) — exploitation du JSON-LD schema.org.

Anibis publie, sur chaque page de détail, un bloc
`<script type="application/ld+json">` de type schema.org/Product contenant
l'annonce sous forme structurée et standardisée (name, description, price,
priceCurrency, seller, address). Cet extracteur lit ce contrat plutôt que le
DOM visible.

Pourquoi un extracteur CODÉ ici, et non des sélecteurs en base ?
`extract_with_selectors` lit du TEXTE de balise (`select_one(sel).get_text()`).
Le JSON-LD est du JSON encapsulé dans un <script> : l'extraire suppose de
parser le bloc, de le désérialiser et de naviguer dans l'objet — une logique
d'extraction que le mécanisme à sélecteurs ne couvre pas. Anibis relève donc
de la famille des extracteurs dédiés (comme FakeMarketExtractor), au même titre
que tout site dont la donnée utile vit hors du texte du DOM. C'est la frontière
d'architecture assumée : sélecteurs quand le DOM textuel suffit, code quand la
structure de la donnée l'exige.

Robustesse : le JSON-LD est un contrat SEO (schema.org). Il survit aux refontes
d'interface — y compris aux classes CSS-in-JS hashées (MUI/Emotion) qui rendent
les sélecteurs visuels fragiles sur ce site. C'est le point d'extraction le plus
stable disponible sur Anibis.

Le parsing (HTML -> liste de dicts) est une fonction PURE, testable sur fixtures
sans navigateur ; `AnibisExtractor` la relie à une session Playwright réelle.
"""

from __future__ import annotations

import asyncio
import json
import re
from collections.abc import Awaitable, Callable
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from osint.collecte.base import BrowserSession
from osint.collecte.guardrails import BudgetExhausted, Guardrails

Fetch = Callable[[str], Awaitable[str]]

# Sélecteur des liens d'annonces sur la page de résultats (SRP). L'attribut
# data-* est stable et sémantique, contrairement aux classes MUI hashées.
_CARD_LINK = "[data-private-srp-listing-item-id] a[href]"

# Pagination : Anibis reflète l'index de page dans l'URL (`?page=N`), même si le
# contrôle visuel est un <button> JS. On CONSTRUIT donc l'URL de chaque page.
_PAGE_PARAM = "?page="


def _iter_jsonld(soup: BeautifulSoup):
    """Rend chaque objet JSON-LD de la page (tolérant aux blocs invalides)."""
    for tag in soup.find_all("script", attrs={"type": "application/ld+json"}):
        raw = tag.string or tag.get_text() or ""
        raw = raw.strip()
        if not raw:
            continue
        try:
            data = json.loads(raw)
        except (ValueError, TypeError):
            continue
        # Un bloc peut contenir un objet, une liste, ou un @graph.
        if isinstance(data, list):
            yield from (d for d in data if isinstance(d, dict))
        elif isinstance(data, dict):
            if isinstance(data.get("@graph"), list):
                yield from (d for d in data["@graph"] if isinstance(d, dict))
            else:
                yield data


def _find_product(soup: BeautifulSoup) -> dict | None:
    """Premier objet JSON-LD de type Product de la page, ou None."""
    for obj in _iter_jsonld(soup):
        t = obj.get("@type")
        types = t if isinstance(t, list) else [t]
        if "Product" in types:
            return obj
    return None


def _external_id_from_url(url: str) -> str | None:
    """ID réel de l'annonce = dernier segment numérique de l'URL Anibis."""
    clean = url.split("?", 1)[0].split("#", 1)[0].rstrip("/")
    m = re.search(r"/(\d+)$", clean)
    return m.group(1) if m else None


def _to_amount(value) -> float | None:
    """Prix schema.org (nombre ou chaîne) -> float, ou None si non convertible."""
    if value is None or value == "":
        return None
    try:
        return float(str(value).replace("'", "").replace(",", "."))
    except (ValueError, TypeError):
        return None


def parse_anibis_listing(html: str, url: str = "") -> dict | None:
    """Extrait une annonce Anibis depuis le JSON-LD Product de sa page détail.

    Renvoie un dict au format attendu par le pipeline (mêmes clés que
    `parse_listing`), ou None si aucun Product exploitable n'est présent
    (signal de rupture géré par l'appelant).
    """
    soup = BeautifulSoup(html, "html.parser")
    product = _find_product(soup)
    if product is None:
        return None

    offer = product.get("offers") or {}
    if isinstance(offer, list):
        offer = offer[0] if offer else {}
    seller = offer.get("seller") or {}
    address = seller.get("address") or {}

    canonical_url = product.get("url") or offer.get("url") or url
    locality = address.get("addressLocality")
    postal = address.get("postalCode")
    location = " ".join(p for p in (postal, locality) if p) or None

    return {
        "external_id": _external_id_from_url(canonical_url),
        "url": canonical_url,
        "title": product.get("name"),
        "description": product.get("description"),
        "price_amount": _to_amount(offer.get("price")),
        "price_currency": offer.get("priceCurrency"),
        "seller": seller.get("name"),
        "location": location,
    }


async def _gather_listing_urls(
    base_url: str, fetch: Fetch, list_path: str, *, max_pages: int, max_listings: int
) -> list[str]:
    """Parcourt les pages de résultats (URL indexée) et renvoie les URLs d'annonces.

    Bornée par `max_pages` (plafond de pages) et `max_listings` (plafond
    d'annonces) ; s'arrête aussi sur une page sans annonce (fin de pagination)
    ou sur épuisement du budget d'actions.
    """
    base_list = base_url + list_path
    urls: list[str] = []
    seen: set[str] = set()
    for page in range(1, max_pages + 1):
        page_url = base_list if page == 1 else f"{base_list}{_PAGE_PARAM}{page}"
        try:
            html = await fetch(page_url)
        except BudgetExhausted:
            break
        soup = BeautifulSoup(html, "html.parser")
        found = 0
        for a in soup.select(_CARD_LINK):
            href = a.get("href")
            if not href:
                continue
            full = urljoin(page_url, href)
            if full not in seen:
                seen.add(full)
                urls.append(full)
                found += 1
                if max_listings and len(urls) >= max_listings:
                    return urls
        if page > 1 and found == 0:  # fin de pagination
            break
    return urls


async def collect(
    base_url: str,
    fetch: Fetch,
    *,
    list_path: str,
    concurrency: int = 4,
    terms: list[str] | None = None,
    max_pages: int = 2,
    max_listings: int = 8,
) -> list[dict]:
    """Collecte les annonces Anibis d'une page de résultats.

    `list_path` est le chemin de recherche (ex. `/fr/q/cherche/<blob>`), Anibis
    n'exposant pas d'URL de recherche en clair. Les `terms` (LLM-EXPAND)
    servent de filtre de pertinence en aval, la requête elle-même étant portée
    par `list_path`. Récupère chaque page d'annonce en parallèle (borné par
    `concurrency`) et s'arrête proprement sur épuisement du budget.
    """
    base_url = base_url.rstrip("/")
    listing_urls = await _gather_listing_urls(
        base_url, fetch, list_path, max_pages=max_pages, max_listings=max_listings
    )

    sem = asyncio.Semaphore(concurrency)

    async def _one(url: str) -> dict | None:
        async with sem:
            try:
                html = await fetch(url)
            except BudgetExhausted:
                return None
            record = parse_anibis_listing(html, url)
            if record and not record.get("url"):
                record["url"] = url
            return record

    results = await asyncio.gather(*(_one(u) for u in listing_urls))
    records = [r for r in results if r and r.get("external_id")]

    # Filtre de pertinence (LLM-EXPAND) : sous-chaîne sur titre + description.
    if terms:
        toks = [t.lower() for t in terms if t]
        def _match(r: dict) -> bool:
            blob = f"{r.get('title') or ''} {r.get('description') or ''}".lower()
            return any(tok in blob for tok in toks)
        records = [r for r in records if _match(r)]

    return records


class AnibisExtractor:
    """Relie la collecte Anibis (JSON-LD) à une vraie session Playwright.

    Le chemin de recherche (`list_path`) et les plafonds de collecte sont lus
    dans la configuration d'extracteur en base (table extractor_versions),
    sous les mêmes clés `_*` que l'extracteur à sélecteurs — l'onboarding d'une
    recherche Anibis reste ainsi paramétrable sans modifier ce code.
    """

    #: chemin de recherche par défaut (surchargé par la config `_list_path`)
    DEFAULT_LIST_PATH = "/fr/q/cherche/Ak6Z3aGlza3nAlMDAwMA"  # « whisky »

    def __init__(
        self,
        base_url: str,
        guardrails: Guardrails,
        *,
        concurrency: int = 4,
        terms: list[str] | None = None,
        config: dict | None = None,
    ) -> None:
        self.base_url = base_url
        self.guardrails = guardrails
        self.concurrency = concurrency
        self.terms = terms
        config = dict(config or {})
        self.list_path: str = config.get("_list_path", self.DEFAULT_LIST_PATH)
        try:
            self.max_pages = max(1, int(config.get("_max_pages", 2)))
        except (TypeError, ValueError):
            self.max_pages = 2
        try:
            self.max_listings = max(0, int(config.get("_max_listings", 8)))
        except (TypeError, ValueError):
            self.max_listings = 8

    async def run(self) -> list[dict]:
        async with BrowserSession(
            guardrails=self.guardrails, concurrency=self.concurrency
        ) as session:
            return await collect(
                self.base_url, session.fetch,
                list_path=self.list_path,
                concurrency=self.concurrency, terms=self.terms,
                max_pages=self.max_pages, max_listings=self.max_listings,
            )