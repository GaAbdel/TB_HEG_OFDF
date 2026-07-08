"""Orchestrateur d'exploration (Mode B-1) : l'enquêteur désigne un ou plusieurs
sites AUTORISÉS, l'agent LLM-BROWSE les explore au mieux, les annonces
relevées sont structurées, persistées et scorées comme en Mode A.

Différence assumée avec le Mode A : l'extraction se fait au mieux (l'agent
navigue et relève au mieux), donc moins fiable et complète qu'un extracteur
déterministe. C'est l'exception ponctuelle à la rigueur du Mode A, pour couvrir
des sites sans extracteur dédié.

Comme il touche le navigateur, le LLM, Qdrant et PostgreSQL, ce pipeline se
valide en conditions réelles. L'endpoint qui le déclenche, lui, est testé avec
un explorateur simulé (injection de `explorer`).
"""

from __future__ import annotations

import hashlib
import json
import logging
import time
from typing import TYPE_CHECKING, Callable
from urllib.parse import urlparse

from osint.analyse.retriever import QdrantRuleRetriever
from osint.analyse.scorer import score_listing
from osint.persistance.db import transaction
from osint.persistance.repositories import (
    add_score,
    create_run,
    finish_run,
    get_or_create_model_version,
    get_or_create_platform,
    upsert_listing,
)
from osint.persistance.store import content_hash

if TYPE_CHECKING:
    from osint.config import Config


logger = logging.getLogger(__name__)


# Profondeur d'exploration -> budget d'actions de l'agent.
DEPTH_STEPS = {
    "rapide": 8,
    "standard": 15,
    "approfondie": 25,
}


def _external_id(listing: dict, url: str) -> str:
    """Identifiant naturel d'une annonce explorée.

    L'URL exacte est privilégiée lorsqu'elle est disponible. À défaut, une
    empreinte stable est construite depuis le titre, le prix et le site source.
    """
    if listing.get("url"):
        return str(listing["url"])

    base = (
        f"{listing.get('title', '')}|"
        f"{listing.get('price_amount', '')}|"
        f"{url}"
    )
    return "browse:" + hashlib.sha256(
        base.encode("utf-8")
    ).hexdigest()[:16]


def _decode_first_json_array(text: str) -> list | None:
    """Extrait le premier tableau JSON valide présent dans un texte.

    Le modèle peut entourer le JSON de Markdown, d'une phrase introductive ou
    d'un bloc de code. On ne se contente donc pas du premier `[` et du dernier
    `]`, car cette méthode devient fragile dès qu'un autre crochet apparaît
    dans la réponse.

    Retourne :
    - la liste décodée, y compris une liste vide valide ;
    - `None` si aucun tableau JSON valide n'est trouvé.
    """
    if not isinstance(text, str) or not text.strip():
        return None

    decoder = json.JSONDecoder()

    for index, character in enumerate(text):
        if character != "[":
            continue

        try:
            value, _ = decoder.raw_decode(text[index:])
        except json.JSONDecodeError:
            continue

        if isinstance(value, list):
            return value

    return None


def _clean_listing_url(value: object) -> str | None:
    """Conserve uniquement une URL HTTP(S) exploitable et non annotée.

    Les sorties comme :

        https://example.test/annonce/123 (URL approximative)

    ne doivent pas être persistées comme preuve exacte.
    """
    if not isinstance(value, str):
        return None

    candidate = value.strip()
    if not candidate:
        return None

    # Une URL issue du navigateur ne doit pas contenir d'espace ni
    # d'annotation textuelle ajoutée par le modèle.
    if any(character.isspace() for character in candidate):
        return None

    try:
        parsed = urlparse(candidate)
    except ValueError:
        return None

    if parsed.scheme not in {"http", "https"}:
        return None

    if not parsed.netloc:
        return None

    return candidate


def _normalise_parsed_listings(data: list) -> list[dict]:
    """Valide et normalise les annonces produites par LLM-PARSE."""
    listings: list[dict] = []

    for item in data:
        if not isinstance(item, dict):
            continue

        title = item.get("title")
        if not isinstance(title, str) or not title.strip():
            continue

        listing = dict(item)
        listing["title"] = title.strip()

        if isinstance(listing.get("description"), str):
            listing["description"] = listing["description"].strip()

        if isinstance(listing.get("price_currency"), str):
            listing["price_currency"] = (
                listing["price_currency"].strip().upper()
            )

        if isinstance(listing.get("seller"), str):
            listing["seller"] = listing["seller"].strip()

        if isinstance(listing.get("location"), str):
            listing["location"] = listing["location"].strip()

        listing["url"] = _clean_listing_url(listing.get("url"))

        listings.append(listing)

    return listings


def _parse_browse_result(
    cfg: "Config",
    raw_text: str,
    url: str,
) -> list[dict]:
    """Structure le compte rendu de LLM-BROWSE en annonces.

    Stratégie :

    1. Si LLM-BROWSE a déjà renvoyé un tableau JSON valide, il est utilisé
       directement sans second appel au modèle.
    2. Sinon, LLM-PARSE transforme le compte rendu en tableau JSON.
    3. La réponse est décodée avec un extracteur tolérant au Markdown.
    4. Une réponse invalide provoque une erreur explicite au lieu de retourner
       silencieusement `[]` et de générer un faux rapport à zéro annonce.

    Une liste vide reste valide lorsque LLM-PARSE renvoie réellement `[]`.
    """
    from osint.analyse.scorer import load_prompt
    from osint.model.litellm_client import complete

    if not raw_text or not raw_text.strip():
        logger.info(
            "LLM-BROWSE n'a produit aucun résultat textuel pour %s.",
            url,
        )
        return []

    # Évolution future compatible : si le prompt de LLM-BROWSE produit déjà
    # du JSON structuré, on évite un appel LLM-PARSE supplémentaire.
    direct_data = _decode_first_json_array(raw_text)
    if direct_data is not None:
        direct_listings = _normalise_parsed_listings(direct_data)

        logger.info(
            "Résultat LLM-BROWSE directement structuré : "
            "%d annonce(s) valide(s) sur %d élément(s).",
            len(direct_listings),
            len(direct_data),
        )
        return direct_listings

    system_prompt = load_prompt("browse_parse_v1")

    try:
        raw = complete(
            cfg,
            agent="LLM-PARSE",
            messages=[
                {
                    "role": "system",
                    "content": system_prompt,
                },
                {
                    "role": "user",
                    "content": raw_text,
                },
            ],
            temperature=0.0,
            # Un compte rendu Browser-Use détaillé peut contenir plusieurs
            # annonces. 1500 tokens pouvaient tronquer le tableau avant son
            # crochet final.
            max_tokens=6000,
        )
    except Exception:
        logger.exception(
            "Échec de l'appel LLM-PARSE pour %s "
            "(entrée Browser-Use : %d caractères).",
            url,
            len(raw_text),
        )
        raise

    if not isinstance(raw, str):
        raise TypeError(
            "LLM-PARSE a renvoyé un résultat non textuel : "
            f"{type(raw).__name__}"
        )

    data = _decode_first_json_array(raw)

    if data is None:
        logger.error(
            "LLM-PARSE n'a renvoyé aucun tableau JSON valide pour %s. "
            "Taille de l'entrée Browser-Use : %d caractères. "
            "Taille de la réponse LLM-PARSE : %d caractères.",
            url,
            len(raw_text),
            len(raw),
        )

        # Ne pas convertir cet échec en faux résultat métier vide. L'appelant
        # doit voir que le run a échoué au stade de la structuration.
        raise ValueError(
            "LLM-PARSE n'a pas renvoyé de tableau JSON valide. "
            f"Réponse reçue : {len(raw)} caractères."
        )

    listings = _normalise_parsed_listings(data)

    if data and not listings:
        logger.error(
            "LLM-PARSE a produit %d élément(s), mais aucune annonce ne possède "
            "un titre valide pour %s.",
            len(data),
            url,
        )
        raise ValueError(
            "LLM-PARSE a produit des éléments, mais aucune annonce valide."
        )

    logger.info(
        "LLM-PARSE a structuré %d annonce(s) valide(s) "
        "sur %d élément(s) pour %s.",
        len(listings),
        len(data),
        url,
    )

    return listings


def _run_browse_isolated(
    cfg: "Config",
    url: str,
    max_steps: int,
    focus: str = "",
    generated_terms: list[str] | None = None,
) -> dict:
    """Exécute run_browse dans une boucle d'évènements isolée.

    Le pipeline d'exploration est appelé, côté API, depuis `_execute_job`, qui
    a déjà ouvert une boucle via `asyncio.run()` dans un thread. Relancer
    `asyncio.run()` ici échouerait avec :

        asyncio.run() cannot be called from a running event loop

    L'exécution est donc déléguée à un thread dédié possédant sa propre boucle.
    Cette approche fonctionne aussi bien depuis l'API que depuis la CLI.
    """
    import asyncio
    import threading

    from osint.analyse.browse import run_browse

    box: dict = {}

    def _worker() -> None:
        try:
            box["result"] = asyncio.run(
                run_browse(
                    cfg,
                    url,
                    max_steps=max_steps,
                    focus=focus,
                    generated_terms=generated_terms or [],
                )
            )
        except BaseException as exc:  # noqa: BLE001
            # L'exception doit être remontée au thread appelant.
            box["error"] = exc

    thread = threading.Thread(
        target=_worker,
        name="browse-loop",
    )
    thread.start()
    thread.join()

    if "error" in box:
        raise box["error"]

    result = box.get("result")
    if not isinstance(result, dict):
        raise TypeError(
            "run_browse doit renvoyer un dictionnaire, "
            f"pas {type(result).__name__}."
        )

    return result


def _default_explorer(
    cfg: "Config",
    url: str,
    max_steps: int,
    focus: str = "",
    generated_terms: list[str] | None = None,
) -> list[dict]:
    """Explorateur réel : LLM-BROWSE puis structuration par LLM-PARSE."""
    result = _run_browse_isolated(
        cfg,
        url,
        max_steps,
        focus,
        generated_terms,
    )

    raw_result = result.get("result") or ""

    logger.info(
        "LLM-BROWSE terminé pour %s : %d caractère(s) à structurer.",
        url,
        len(raw_result),
    )

    return _parse_browse_result(
        cfg,
        raw_result,
        url,
    )


def run_explore_pipeline(
    cfg: "Config",
    *,
    sites: list[dict],
    depth: str = "standard",
    focus: str = "",
    explorer: Callable[..., list[dict]] | None = None,
) -> dict:
    """Explore des sites autorisés et persiste/score les annonces.

    `sites` est une liste d'objets :

        {
            "label": "...",
            "base_url": "...",
            "platform": "..."
        }

    Les sites doivent déjà avoir été validés contre l'allowlist par l'appelant.

    `explorer` est injectable pour permettre les tests sans navigateur réel.
    """
    explorer = explorer or _default_explorer

    started_at = time.monotonic()
    max_steps = DEPTH_STEPS.get(
        depth,
        DEPTH_STEPS["standard"],
    )

    # Focus optionnel : lorsque l'enquêteur précise une cible, LLM-EXPAND
    # produit des catégories et des formulations associées. Ces éléments
    # orientent LLM-BROWSE sans constituer un filtre littéral ou exclusif.
    #
    # Une panne de LLM-EXPAND ne doit pas bloquer l'exploration.
    target_categories: list[str] = []
    generated_terms: list[str] = []

    if focus.strip():
        try:
            from osint.analyse.expander import expand_terms

            expanded = expand_terms(
                cfg,
                focus.strip(),
            )

            target_categories = (
                expanded.get("categories", []) or []
            )

            generated_terms = list(
                dict.fromkeys(
                    str(term).strip()
                    for term in (
                        expanded.get("terms", []) or []
                    )
                    if str(term).strip()
                )
            )[:10]

        except Exception:
            logger.exception(
                "LLM-EXPAND a échoué pour le focus %r. "
                "L'exploration continue sans termes générés.",
                focus.strip(),
            )

            target_categories = []
            generated_terms = []

    retriever = QdrantRuleRetriever.from_config(cfg)
    score_model = cfg.resolve_model("LLM-SCORE").model

    with transaction() as conn:
        run_id = create_run(
            conn,
            mode="B",
            trigger="explore",
            actor="investigator",
            params={
                "sites": [
                    site.get("label")
                    for site in sites
                ],
                "depth": depth,
                "mode": "B1",
                "mode_b": "exploration",
                "seeds": (
                    [focus.strip()]
                    if focus.strip()
                    else []
                ),
                "target_categories": target_categories,
                "generated_terms": generated_terms,
            },
            config_snapshot={
                "sites": sites,
                "depth": depth,
            },
        )

        model_version_id = get_or_create_model_version(
            conn,
            agent="LLM-SCORE",
            model_name=score_model,
            prompt_version="score_v1",
        )

        collected = 0
        scored = 0
        alertes = 0

        par_categorie: dict[str, int] = {}
        par_site: dict[str, int] = {}

        # Compatibilité avec les explorateurs simulés utilisés dans les tests.
        # Certains n'acceptent que `(cfg, url, max_steps)`.
        import inspect

        try:
            explorer_parameters = inspect.signature(
                explorer
            ).parameters
        except (TypeError, ValueError):
            explorer_parameters = {}

        explore_kwargs: dict = {}

        if "focus" in explorer_parameters:
            explore_kwargs["focus"] = focus.strip()

        if "generated_terms" in explorer_parameters:
            explore_kwargs["generated_terms"] = generated_terms

        for site in sites:
            platform_id = get_or_create_platform(
                conn,
                site["platform"],
                site["base_url"],
            )

            listings = explorer(
                cfg,
                site["base_url"],
                max_steps,
                **explore_kwargs,
            ) or []

            site_label = site.get(
                "label",
                site["platform"],
            )

            par_site[site_label] = len(listings)
            collected += len(listings)

            logger.info(
                "Mode B : %d annonce(s) structurée(s) pour le site %s.",
                len(listings),
                site_label,
            )

            for listing in listings:
                external_id = _external_id(
                    listing,
                    site["base_url"],
                )

                listing_id, _ = upsert_listing(
                    conn,
                    run_id=run_id,
                    actor="investigator",
                    platform_id=platform_id,
                    external_id=external_id,
                    content_hash=content_hash(listing),
                    url=listing.get("url"),
                    title=listing.get("title"),
                    description=listing.get("description"),
                    price_amount=listing.get("price_amount"),
                    price_currency=listing.get("price_currency"),
                    seller_label=listing.get("seller"),
                    structured={
                        "location": listing.get("location"),
                        "source": "mode_b",
                    },
                )

                query = (
                    f"{listing.get('title', '')} "
                    f"{listing.get('description', '')}"
                ).strip()

                rules = retriever.retrieve(query)

                score = score_listing(
                    cfg,
                    listing,
                    rules=rules,
                )

                add_score(
                    conn,
                    run_id=run_id,
                    listing_id=listing_id,
                    model_version_id=model_version_id,
                    category=score["category"],
                    suspicion_score=score["suspicion_score"],
                    rationale=score.get("rationale"),
                    rag_refs=score.get("rag_refs"),
                )

                scored += 1

                try:
                    note = float(
                        score["suspicion_score"]
                    )
                except (TypeError, ValueError):
                    note = 0.0

                if note >= 0.70:
                    alertes += 1

                    category = (
                        score.get("category")
                        or "aucune"
                    )

                    if category != "aucune":
                        par_categorie[category] = (
                            par_categorie.get(category, 0)
                            + 1
                        )

        etapes = {
            "expand": {
                "categories": target_categories,
                "termes": len(generated_terms),
            },
            "exploration": {
                "sites": par_site,
                "profondeur": depth,
            },
            "collecte": {
                "annonces": collected,
            },
            "scoring": {
                "scorees": scored,
                "alertes": alertes,
                "par_categorie": par_categorie,
            },
        }

        stats = {
            "collected": collected,
            "scored": scored,
            "alertes": alertes,
            "mode_b": True,
            "etapes": etapes,
            "duree_s": round(
                time.monotonic() - started_at,
                1,
            ),
        }

        finish_run(
            conn,
            run_id,
            status="completed",
            stats=stats,
            actor="investigator",
        )

    return {
        "run_id": run_id,
        "collected": collected,
        "scored": scored,
    }