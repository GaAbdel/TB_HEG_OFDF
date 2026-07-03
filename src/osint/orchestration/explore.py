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

import time

import hashlib
import json
from typing import TYPE_CHECKING, Callable

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

# Profondeur d'exploration -> budget d'actions de l'agent (pas de navigation).
DEPTH_STEPS = {"rapide": 8, "standard": 15, "approfondie": 25}


def _external_id(listing: dict, url: str) -> str:
    """Identifiant naturel d'une annonce explorée (url si dispo, sinon empreinte)."""
    if listing.get("url"):
        return str(listing["url"])
    base = f"{listing.get('title', '')}|{listing.get('price_amount', '')}|{url}"
    return "browse:" + hashlib.sha256(base.encode("utf-8")).hexdigest()[:16]


def _parse_browse_result(cfg: "Config", raw_text: str, url: str) -> list[dict]:
    """Structure le compte rendu texte de l'agent en annonces (au mieux)."""
    from osint.analyse.scorer import load_prompt
    from osint.model.litellm_client import complete

    if not raw_text or not raw_text.strip():
        return []
    system_prompt = load_prompt("browse_parse_v1")
    raw = complete(
        cfg, agent="LLM-PARSE",
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": raw_text},
        ],
        temperature=0.0, max_tokens=1500,
    )
    start, end = raw.find("["), raw.rfind("]")
    if start == -1 or end == -1:
        return []
    try:
        data = json.loads(raw[start : end + 1])
    except json.JSONDecodeError:
        return []
    return [d for d in data if isinstance(d, dict) and d.get("title")]


def _run_browse_isolated(cfg: "Config", url: str, max_steps: int) -> dict:
    """Exécute run_browse (async) dans une boucle d'évènements ISOLÉE.

    Le pipeline d'exploration est appelé, côté API, depuis _execute_job qui a
    déjà ouvert une boucle via asyncio.run() dans un thread. Relancer
    asyncio.run() ici échouerait (« cannot be called from a running event
    loop »). On délègue donc l'exécution à un thread dédié qui possède sa propre
    boucle — robuste que l'appelant ait une boucle active ou non (API comme CLI).
    """
    import asyncio
    import threading

    from osint.analyse.browse import run_browse

    box: dict = {}

    def _worker() -> None:
        try:
            box["result"] = asyncio.run(run_browse(cfg, url, max_steps=max_steps))
        except BaseException as exc:  # noqa: BLE001 - remonté au thread appelant
            box["error"] = exc

    t = threading.Thread(target=_worker, name="browse-loop")
    t.start()
    t.join()
    if "error" in box:
        raise box["error"]
    return box["result"]


def _default_explorer(cfg: "Config", url: str, max_steps: int) -> list[dict]:
    """Explorateur réel : LLM-BROWSE puis structuration. Validé en conditions réelles."""
    result = _run_browse_isolated(cfg, url, max_steps)
    return _parse_browse_result(cfg, result.get("result") or "", url)


def run_explore_pipeline(
    cfg: "Config",
    *,
    sites: list[dict],
    depth: str = "standard",
    focus: str = "",
    explorer: Callable[["Config", str, int], list[dict]] | None = None,
) -> dict:
    """Explore des sites AUTORISÉS (Mode B-1) et persiste/score les annonces.

    `sites` : liste de {label, base_url, platform}, DÉJÀ validés contre
    l'allowlist par l'appelant. `explorer` est injectable pour les tests.
    """
    explorer = explorer or _default_explorer
    _t0 = time.monotonic()
    max_steps = DEPTH_STEPS.get(depth, DEPTH_STEPS["standard"])

    # Focus optionnel (Mode B-1) : si l'enquêteur précise une cible, on en dérive
    # les catégories visées via LLM-EXPAND — SANS toucher au comportement de
    # BROWSE (qui explore toujours librement). Ces catégories pilotent seulement
    # le tri à deux niveaux du rapport (comme en Mode A). Au mieux : une panne
    # d'EXPAND ne doit jamais empêcher l'exploration.
    target_categories: list[str] = []
    if focus.strip():
        try:
            from osint.analyse.expander import expand_terms
            target_categories = expand_terms(cfg, focus.strip()).get("categories", []) or []
        except Exception:
            target_categories = []
    retriever = QdrantRuleRetriever.from_config(cfg)
    score_model = cfg.resolve_model("LLM-SCORE").model

    with transaction() as conn:
        run_id = create_run(
            conn, mode="B", trigger="explore", actor="investigator",
            params={
                "sites": [s.get("label") for s in sites],
                "depth": depth,
                "mode_b": "exploration",
                "seeds": [focus.strip()] if focus.strip() else [],
                "target_categories": target_categories,
            },
            config_snapshot={"sites": sites, "depth": depth},
        )
        model_version_id = get_or_create_model_version(
            conn, agent="LLM-SCORE", model_name=score_model, prompt_version="score_v1",
        )

        collected = 0
        scored = 0
        alertes = 0
        par_categorie: dict[str, int] = {}
        par_site: dict[str, int] = {}

        for site in sites:
            pid = get_or_create_platform(conn, site["platform"], site["base_url"])
            listings = explorer(cfg, site["base_url"], max_steps) or []
            par_site[site.get("label", site["platform"])] = len(listings)
            collected += len(listings)
            for it in listings:
                ext = _external_id(it, site["base_url"])
                listing_id, _ = upsert_listing(
                    conn, run_id=run_id, actor="investigator", platform_id=pid,
                    external_id=ext, content_hash=content_hash(it),
                    url=it.get("url"), title=it.get("title"),
                    description=it.get("description"),
                    price_amount=it.get("price_amount"),
                    price_currency=it.get("price_currency"),
                    seller_label=it.get("seller"),
                    structured={"location": it.get("location"), "source": "mode_b"},
                )
                query = f"{it.get('title', '')} {it.get('description', '')}".strip()
                rules = retriever.retrieve(query)
                score = score_listing(cfg, it, rules=rules)
                add_score(
                    conn, run_id=run_id, listing_id=listing_id, model_version_id=model_version_id,
                    category=score["category"], suspicion_score=score["suspicion_score"],
                    rationale=score.get("rationale"), rag_refs=score.get("rag_refs"),
                )
                scored += 1
                try:
                    note = float(score["suspicion_score"])
                except (TypeError, ValueError):
                    note = 0.0
                if note >= 0.70:
                    alertes += 1
                    cat = score.get("category") or "aucune"
                    if cat != "aucune":
                        par_categorie[cat] = par_categorie.get(cat, 0) + 1

        etapes = {
            "exploration": {"sites": par_site, "profondeur": depth},
            "collecte": {"annonces": collected},
            "scoring": {"scorees": scored, "alertes": alertes, "par_categorie": par_categorie},
        }
        stats = {
            "collected": collected, "scored": scored, "alertes": alertes,
            "mode_b": True, "etapes": etapes,
            "duree_s": round(time.monotonic() - _t0, 1),
        }
        finish_run(conn, run_id, status="completed", stats=stats, actor="investigator")

    return {"run_id": run_id, "collected": collected, "scored": scored}
