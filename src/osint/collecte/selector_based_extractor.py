"""Extracteur Mode A piloté par une configuration de sélecteurs.

Contrairement à FakeMarketExtractor (parsing figé dans le code), cet extracteur
reçoit ses sélecteurs `{champ: sélecteur CSS}` en paramètre — typiquement chargés
depuis la table `extractor_versions` (version ACTIVE). Il devient donc
RÉPARABLE : si le site change et casse l'extraction, LLM-CODE propose de
nouveaux sélecteurs (candidat en attente de validation admin), sans que le code
change.

Métadonnées de navigation (clés préfixées `_` dans la config JSONB) :
la structure du site — chemin de la page de résultats, sélecteur des cartes,
lien « page suivante », plafond de pages — relève de la CONFIGURATION, pas du
code. Les clés `_list_path`, `_card_selector`, `_next_page` et `_max_pages`
sont extraites du dictionnaire de sélecteurs à l'initialisation ; les clés
restantes sont les champs d'extraction. Une config sans clé `_*` reproduit
exactement le comportement historique (mono-page, valeurs par défaut) :
onboarder un site = insérer sa ligne en base, sans toucher au code.

Détection de rupture : si, sur les pages de détail visitées, les champs requis
sont massivement absents, l'extracteur lève `ExtractorBrokenError` en emportant
un échantillon de HTML défaillant — matière première de la réparation.
"""

from __future__ import annotations

import hashlib
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

# Clés de la config JSONB décrivant la STRUCTURE du site (navigation), par
# opposition aux champs d'extraction. Documentées ici comme contrat.
_META_KEYS = ("_list_path", "_card_selector", "_next_page", "_max_pages")


class ExtractorBrokenError(Exception):
    """Levée quand l'extraction échoue massivement (sélecteurs obsolètes).

    Porte l'échantillon de HTML défaillant et les sélecteurs courants, pour
    alimenter la réparation LLM-CODE.
    """

    def __init__(
        self, sample_html: str, selectors: dict, missing: list[str],
        meta: dict | None = None,
    ) -> None:
        super().__init__(f"extracteur cassé — champs manquants : {missing}")
        self.sample_html = sample_html
        self.selectors = selectors      # champs d'extraction (portée LLM-CODE)
        self.missing = missing
        # Métadonnées de navigation (_list_path, _next_page...) : HORS de la
        # portée de la réparation, mais à REFUSIONNER dans tout candidat pour
        # qu'une approbation ne fasse pas régresser la configuration.
        self.meta = dict(meta or {})


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


def _external_id(url: str) -> str:
    """Identifiant stable d'une annonce à partir de son URL.

    1. Format historique `/listing/<id>` (fake_market, mock_shop) : l'id.
    2. Segment final numérique (convention des marketplaces réelles, dont
       Anibis : `/fr/vi/<région>/<catégorie>/<slug>/<id>`) : l'identifiant
       RÉEL de l'annonce sur la plateforme — traçable par l'enquêteur.
    3. Sinon : empreinte SHA-256 tronquée de l'URL NORMALISÉE (sans query
       string ni slash final, insensibles aux paramètres de session/tracking).

    Dans les trois cas l'identifiant est stable entre deux runs -> la clé
    naturelle UNIQUE (platform_id, external_id) et la déduplication par
    upsert fonctionnent sans hypothèse sur le format d'URL du site.
    """
    clean = url.split("?", 1)[0].split("#", 1)[0].rstrip("/")
    m = re.search(r"/listing/(\d+)$", clean)
    if m:
        return m.group(1)
    m = re.search(r"/(\d+)$", clean)
    if m:
        return m.group(1)
    return hashlib.sha256(clean.encode("utf-8")).hexdigest()[:16]


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
        self.concurrency = concurrency
        self.terms = terms
        self.break_threshold = break_threshold

        # --- Métadonnées de navigation (config déclarative, clés `_*`) -------
        # Copie défensive : la config chargée depuis la base ne doit pas être
        # mutée. Les kwargs `list_path`/`card_selector` restent les défauts,
        # surchargés par la config si elle les déclare.
        selectors = dict(selectors)
        self.list_path: str = selectors.pop("_list_path", list_path)
        self.card_selector: str = selectors.pop("_card_selector", card_selector)
        self.next_page_selector: str | None = selectors.pop("_next_page", None)
        # Deux mécanismes de pagination, mutuellement exclusifs :
        #   - `_next_page` : sélecteur d'un lien « suivant » (site où la page
        #     suivante est un <a href>). On SUIT le lien.
        #   - `_page_param` : suffixe de requête indexé (ex. "?page=" ou
        #     "&page="). On CONSTRUIT l'URL de chaque page (site où la
        #     pagination est un <button> JS sans href, mais où l'index de page
        #     se reflète dans l'URL — cas d'Anibis). Numérotation à partir de 1,
        #     la page 1 restant l'URL de base (aucun suffixe ajouté).
        self.page_param: str | None = selectors.pop("_page_param", None)
        try:
            self.max_pages: int = max(1, int(selectors.pop("_max_pages", 1)))
        except (TypeError, ValueError):
            self.max_pages = 1
        # Plafond d'annonces par run (0/absent = illimité) : contrôle direct de
        # la durée d'une collecte — chaque annonce coûte un fetch de détail PUIS
        # un scoring LLM, de loin le poste dominant en topologie locale.
        try:
            self.max_listings: int = max(0, int(selectors.pop("_max_listings", 0)))
        except (TypeError, ValueError):
            self.max_listings = 0
        # Les clés restantes sont les champs d'extraction (contrat LLM-CODE :
        # la réparation ne porte QUE sur ces champs, jamais sur la navigation).
        self.selectors = selectors
        # Métadonnées conservées telles que déclarées en base : refusionnées
        # dans tout candidat de réparation (cf. ExtractorBrokenError.meta).
        self.meta: dict = {
            "_list_path": self.list_path,
            "_card_selector": self.card_selector,
            **({"_next_page": self.next_page_selector} if self.next_page_selector else {}),
            **({"_page_param": self.page_param} if self.page_param else {}),
            **({"_max_pages": self.max_pages} if self.max_pages > 1 else {}),
            **({"_max_listings": self.max_listings} if self.max_listings else {}),
        }

    async def run(self) -> list[dict]:
        async with BrowserSession(
            guardrails=self.guardrails, concurrency=self.concurrency
        ) as session:
            return await self._collect(session.fetch)

    def _next_list_url(
        self, base_list_url: str, soup, current_url: str, pages_done: int
    ) -> str | None:
        """URL de la page de résultats suivante, ou None s'il n'y en a pas.

        Deux stratégies, selon la config :
          - `_page_param` : construction d'URL indexée (page 1 = URL de base ;
            page N>=2 = base + suffixe + N). Le suffixe porte son séparateur
            (« ?page= » ou « &page= ») ; on ne présume pas de l'état de la
            query string de `_list_path`.
          - `_next_page` : suivi du lien « suivant » présent dans le DOM.
        Sans aucune des deux : pas de page suivante (comportement mono-page).
        """
        if self.page_param:
            return f"{base_list_url}{self.page_param}{pages_done + 1}"
        if self.next_page_selector:
            nxt = soup.select_one(self.next_page_selector)
            if nxt and nxt.get("href"):
                return urljoin(current_url, nxt.get("href"))
        return None

    async def _collect(self, fetch) -> list[dict]:
        """Cœur testable : `fetch(url) -> html`. Lève ExtractorBrokenError si cassé."""
        # --- Parcours de la ou des pages de résultats -------------------------
        # Boucle bornée deux fois : par `_max_pages` (plafond déclaratif) et,
        # en profondeur, par le budget d'actions du garde-fou que chaque fetch
        # consomme déjà. Sans `_next_page` en config : une seule page,
        # comportement historique inchangé.
        hrefs: list[str] = []
        list_html: str | None = None
        base_list_url = self.base_url + self.list_path
        url: str | None = base_list_url
        pages = 0
        visited: set[str] = set()
        while url and pages < self.max_pages:
            if url in visited:  # cycle de pagination (lien « suivant » bouclant)
                break
            visited.add(url)
            list_html = await fetch(url)
            soup = BeautifulSoup(list_html, "html.parser")
            page_hrefs = [
                urljoin(url, a.get("href"))
                for a in soup.select(self.card_selector)
                if a.get("href")
            ]
            hrefs += page_hrefs
            pages += 1

            # Arrêt anticipé : une page de résultats sans aucune carte signale
            # la fin de la pagination (dépassement du dernier index), même si
            # `_max_pages` n'est pas atteint. Ne s'applique qu'après la 1re page
            # (une 1re page vide relève de la détection de rupture, pas de la
            # fin de pagination).
            if pages > 1 and not page_hrefs:
                break

            url = self._next_list_url(base_list_url, soup, url, pages)

        # Dédoublonnage en préservant l'ordre : une même annonce peut
        # apparaître sur plusieurs pages (remontées, mises en avant).
        hrefs = list(dict.fromkeys(hrefs))
        if self.max_listings:
            hrefs = hrefs[: self.max_listings]

        records: list[dict] = []
        broken = 0
        first_bad_html: str | None = None

        for href in hrefs:
            html = await fetch(href)
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
                    "external_id": _external_id(href),
                    "url": href,
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
            fields = extract_with_selectors(first_bad_html or list_html or "", self.selectors)
            raise ExtractorBrokenError(
                first_bad_html or list_html or "", self.selectors,
                missing_fields(fields, REQUIRED), meta=self.meta,
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