"""Extracteur Mode A piloté par une configuration de sélecteurs.

Contrairement à FakeMarketExtractor (parsing figé dans le code), cet extracteur
reçoit ses sélecteurs `{champ: sélecteur CSS}` en paramètre — typiquement chargés
depuis la table `extractor_versions` (version ACTIVE). Il devient donc
RÉPARABLE : si le site change et casse l'extraction, LLM-CODE propose de
nouveaux sélecteurs (candidat en attente de validation admin), sans que le code
change.

Détection de rupture : si, sur les pages de détail visitées, les champs requis
sont massivement absents, l'extracteur lève `ExtractorBrokenError` en emportant
un échantillon de HTML défaillant — matière première de la réparation.
"""

from __future__ import annotations

import re
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from osint.collecte.base import BrowserSession
from osint.collecte.guardrails import Guardrails
from osint.collecte.selector_extractor import (
    REQUIRED,
    extract_with_selectors,
    missing_fields,
)

_PRICE_RE = re.compile(r"([\d'’.,]+)\s*([A-Za-z]{3})?")


class ExtractorBrokenError(Exception):
    """Levée quand l'extraction échoue massivement (sélecteurs obsolètes).

    Porte l'échantillon de HTML défaillant et les sélecteurs courants, pour
    alimenter la réparation LLM-CODE.
    """

    def __init__(self, sample_html: str, selectors: dict, missing: list[str]) -> None:
        super().__init__(f"extracteur cassé — champs manquants : {missing}")
        self.sample_html = sample_html
        self.selectors = selectors
        self.missing = missing


def _parse_price(text: str | None) -> tuple[float | None, str | None]:
    """« 380 CHF » -> (380.0, 'CHF'). Tolérant aux séparateurs de milliers."""
    if not text:
        return None, None
    m = _PRICE_RE.search(text)
    if not m:
        return None, None
    raw = m.group(1).replace("'", "").replace("’", "").replace(",", ".")
    try:
        amount = float(raw)
    except ValueError:
        amount = None
    return amount, (m.group(2).upper() if m.group(2) else None)


def _external_id(url: str) -> str | None:
    m = re.search(r"/listing/(\d+)", url)
    return m.group(1) if m else None


class SelectorBasedExtractor:
    """Extracteur Mode A dont les sélecteurs sont un paramètre (donc réparable)."""

    def __init__(
        self,
        base_url: str,
        guardrails: Guardrails,
        *,
        selectors: dict,
        concurrency: int = 4,
        terms: list[str] | None = None,
        list_path: str = "/shop",
        card_selector: str = "a.card",
        break_threshold: float = 0.5,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.guardrails = guardrails
        self.selectors = selectors
        self.concurrency = concurrency
        self.terms = terms
        self.list_path = list_path
        self.card_selector = card_selector
        self.break_threshold = break_threshold

    async def run(self) -> list[dict]:
        async with BrowserSession(
            guardrails=self.guardrails, concurrency=self.concurrency
        ) as session:
            return await self._collect(session.fetch)

    async def _collect(self, fetch) -> list[dict]:
        """Cœur testable : `fetch(url) -> html`. Lève ExtractorBrokenError si cassé."""
        list_html = await fetch(self.base_url + self.list_path)
        soup = BeautifulSoup(list_html, "html.parser")
        hrefs = [
            urljoin(self.base_url + "/", a.get("href"))
            for a in soup.select(self.card_selector)
            if a.get("href")
        ]

        records: list[dict] = []
        broken = 0
        first_bad_html: str | None = None

        for url in hrefs:
            html = await fetch(url)
            fields = extract_with_selectors(html, self.selectors)
            miss = missing_fields(fields, REQUIRED)
            if miss:
                broken += 1
                if first_bad_html is None:
                    first_bad_html = html
                continue
            amount, currency = _parse_price(fields.get("price"))
            records.append(
                {
                    "external_id": _external_id(url),
                    "url": url,
                    "title": fields.get("title"),
                    "price_amount": amount,
                    "price_currency": currency,
                    "seller": fields.get("seller"),
                    "location": fields.get("location"),
                    "description": fields.get("description"),
                }
            )

        # Rupture : trop de pages de détail sans champs requis -> extracteur obsolète.
        total = len(hrefs)
        if total and (broken / total) >= self.break_threshold:
            fields = extract_with_selectors(first_bad_html or list_html, self.selectors)
            raise ExtractorBrokenError(
                first_bad_html or list_html, self.selectors,
                missing_fields(fields, REQUIRED),
            )

        # Filtre par termes (site de démo à faible volume) : sous-chaîne.
        # Pas de filet de secours : si rien ne matche, on renvoie 0 (honnête).
        if self.terms:
            toks = [t.lower() for t in self.terms if t]
            def _match(r: dict) -> bool:
                blob = f"{r.get('title') or ''} {r.get('description') or ''}".lower()
                return any(tok in blob for tok in toks)
            records = [r for r in records if _match(r)]

        return records