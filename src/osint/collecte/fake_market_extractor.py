"""Extracteur du faux marché — orchestration de la collecte.

`collect()` parcourt la page de résultats (pagination), suit les liens vers les
pages d'annonce et renvoie les annonces structurées. La fonction `fetch`
(url -> HTML) est INJECTÉE : avec une vraie `BrowserSession` en production, avec
un stub en test -> l'orchestration est testable sans navigateur.

`FakeMarketExtractor` relie cette orchestration à une session Playwright réelle.
"""


from __future__ import annotations
 
import asyncio
from collections.abc import Awaitable, Callable
from urllib.parse import quote
 
from osint.collecte.base import BrowserSession
from osint.collecte.guardrails import BudgetExhausted, Guardrails
from osint.collecte.parsers import next_page_url, parse_listing, parse_search_results
 
Fetch = Callable[[str], Awaitable[str]]
 
 
async def _gather_listing_urls(base_url: str, fetch: Fetch, start_path: str) -> list[str]:
    """Parcourt une page de résultats (pagination) et renvoie les URLs d'annonces."""
    urls: list[str] = []
    next_path: str | None = start_path
    while next_path:
        try:
            html = await fetch(base_url + next_path)
        except BudgetExhausted:
            break
        for row in parse_search_results(html):
            if row.get("url"):
                urls.append(base_url + row["url"])
        next_path = next_page_url(html)
    return urls
 
 
async def collect(
    base_url: str,
    fetch: Fetch,
    *,
    concurrency: int = 4,
    terms: list[str] | None = None,
) -> list[dict]:
    """Collecte les annonces du faux marché.
 
    Deux modes :
      - sans `terms` : parcourt /search dans sa totalité (balayage complet) ;
      - avec `terms` (fournis par LLM-EXPAND) : lance une recherche `?q=terme`
        par terme et déduplique les annonces trouvées (collecte ciblée).
 
    Puis récupère chaque page d'annonce en parallèle (borné par `concurrency`).
    S'arrête proprement si le budget d'actions est épuisé (BudgetExhausted),
    renvoyant la collecte partielle déjà obtenue.
    """
    base_url = base_url.rstrip("/")
 
    if terms:
        listing_urls: list[str] = []
        seen: set[str] = set()
        for term in terms:
            start = f"/search?q={quote(term)}&page=1"
            for url in await _gather_listing_urls(base_url, fetch, start):
                if url not in seen:
                    seen.add(url)
                    listing_urls.append(url)
    else:
        listing_urls = await _gather_listing_urls(base_url, fetch, "/search?page=1")
 
    sem = asyncio.Semaphore(concurrency)
 
    async def _one(url: str) -> dict | None:
        async with sem:
            try:
                record = parse_listing(await fetch(url))
            except BudgetExhausted:
                return None
            record["url"] = url
            return record
 
    results = await asyncio.gather(*(_one(u) for u in listing_urls))
    return [r for r in results if r]
 
 
class FakeMarketExtractor:
    """Relie l'orchestration de collecte à une vraie session Playwright."""
 
    def __init__(
        self,
        base_url: str,
        guardrails: Guardrails,
        *,
        concurrency: int = 4,
        terms: list[str] | None = None,
    ) -> None:
        self.base_url = base_url
        self.guardrails = guardrails
        self.concurrency = concurrency
        self.terms = terms
 
    async def run(self) -> list[dict]:
        async with BrowserSession(
            guardrails=self.guardrails, concurrency=self.concurrency
        ) as session:
            return await collect(
                self.base_url, session.fetch,
                concurrency=self.concurrency, terms=self.terms,
            )
 