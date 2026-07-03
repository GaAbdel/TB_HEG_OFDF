"""Orchestrateur de recherche à la demande (Mode A, surveillance déterministe) : EXPAND -> collecte ->
scoring -> persistance, dans une transaction.

Enchaîne des briques déjà éprouvées individuellement. Comme il touche le LLM,
le navigateur, Qdrant et PostgreSQL, il se valide en conditions réelles (via
POST /search), pas sur des données factices.
"""

from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor

from typing import TYPE_CHECKING

from osint.analyse.expander import expand_terms
from osint.analyse.retriever import QdrantRuleRetriever
from osint.analyse.scorer import score_listing
from osint.collecte.fake_market_extractor import FakeMarketExtractor
from osint.collecte.selector_based_extractor import (
    ExtractorBrokenError,
    SelectorBasedExtractor,
)

# Plateformes disposant d'un extracteur FIGÉ (parsing dans le code). En démo,
# fake_market. Les extracteurs à SÉLECTEURS (réparables) ne sont plus listés ici :
# une plateforme est « à sélecteurs » dès qu'elle a une version active en base
# (table extractor_versions) — cf. list_selector_platforms. Onboarder un tel site
# = insérer sa version active, sans toucher au code.
EXTRACTORS: dict = {"fake_market": FakeMarketExtractor}
from osint.collecte.guardrails import Guardrails
from osint.persistance.db import transaction
from osint.analyse.code_repair import make_llm_repair_fn, repair_selectors
from osint.persistance.repositories import (
    add_score,
    create_run,
    finish_run,
    get_active_selectors,
    get_or_create_model_version,
    insert_extractor_candidate,
    list_selector_platforms,
    platform_id,
    upsert_listing,
)
from osint.persistance.store import content_hash

if TYPE_CHECKING:
    from osint.config import Config


def _handle_broken_extractor(
    cfg, platform: str, base_url: str, seeds: list[str],
    terms: list[str], target_categories: list[str],
    exc: ExtractorBrokenError, t0: float,
) -> dict:
    """Extracteur cassé : LLM-CODE propose un CANDIDAT (non appliqué), l'admin valide.

    Le run se termine SANS annonces mais avec un signal explicite (extractor_stale
    + candidate_id). Aucune réparation n'est appliquée automatiquement — conforme
    au principe « signaux, pas décisions » étendu au code.
    """
    llm_fn = make_llm_repair_fn(cfg)
    result = repair_selectors(llm_fn, exc.sample_html, exc.selectors, max_iters=3)
    proposed = result.get("selectors") or {}
    candidate_id = None

    with transaction() as conn:
        run_id = create_run(
            conn, mode="A", trigger="api", actor="api",
            params={"seeds": seeds, "terms": len(terms), "target_categories": target_categories},
            config_snapshot={"platform": platform, "base_url": base_url},
        )
        # On ne persiste un candidat que s'il DIFFÈRE des sélecteurs cassés.
        if proposed and proposed != exc.selectors:
            candidate_id = insert_extractor_candidate(
                conn, platform=platform, selectors=proposed, source="llm-code",
                repair_history=result.get("history"), validation=result.get("record"),
            )
        stats = {
            "terms": len(terms), "collected": 0, "scored": 0,
            "extractor_stale": True,
            "repair_ok": bool(result.get("ok")),
            "candidate_id": candidate_id,
            "duree_s": round(time.monotonic() - t0, 1),
        }
        finish_run(conn, run_id, status="completed", stats=stats, actor="api")

    return {
        "run_id": run_id, "terms": len(terms), "collected": 0, "scored": 0,
        "extractor_stale": True, "repair_ok": bool(result.get("ok")),
        "candidate_id": candidate_id,
    }


async def run_search_pipeline(
    cfg: "Config",
    *,
    seeds: list[str],
    platform: str = "fake_market",
    base_url: str = "http://fake_market:8000",
    max_terms: int | None = None,
    action_budget: int = 500,
) -> dict:
    """Exécute une recherche complète et persiste annonces + scores.

    Renvoie un bilan : {run_id, terms, collected, scored}.
    """
    cfg.assert_lpd_compliance(consentement_cloud=True)
    _t0 = time.monotonic()

    # 1) EXPAND : amorces -> termes enrichis (dédupliqués) + catégories visées.
    terms: list[str] = []
    target_categories: list[str] = []
    for seed in seeds:
        result = expand_terms(cfg, seed)
        terms.extend(result.get("terms", []))
        for cat in result.get("categories", []):
            if cat not in target_categories:
                target_categories.append(cat)
    terms = list(dict.fromkeys(terms))
    if max_terms:
        terms = terms[:max_terms]

    # 2) COLLECTE ciblée sous garde-fous.
    # Deux familles d'extracteurs : classiques (parsing figé, ex. fake_market) et
    # pilotés par sélecteurs chargés en base (ex. mock_shop), ces derniers étant
    # réparables par LLM-CODE. Ricardo/Tutti/Anibis exigent un extracteur dédié
    # (à construire par l'OFDF).
    guardrails = Guardrails.from_config(cfg, allowlist=[platform], action_budget=action_budget)
    concurrency = cfg.get("collecte", "concurrence_max", default=4)

    if platform in EXTRACTORS:
        extractor = EXTRACTORS[platform](base_url, guardrails, concurrency=concurrency, terms=terms)
    else:
        # Sinon : extracteur à sélecteurs SI la plateforme a une version active
        # en base (source de vérité déclarative, pas de registre codé en dur).
        with transaction() as conn:
            active_selectors = get_active_selectors(conn, platform)
            known = sorted(set(EXTRACTORS) | set(list_selector_platforms(conn)))
        if not active_selectors:
            raise ValueError(
                f"extracteur déterministe non disponible pour '{platform}' "
                f"(plateformes supportées : {', '.join(known)})"
            )
        extractor = SelectorBasedExtractor(
            base_url, guardrails, selectors=active_selectors,
            concurrency=concurrency, terms=terms,
        )

    try:
        listings = await extractor.run()
    except ExtractorBrokenError as exc:
        # Le site a changé : LLM-CODE propose un candidat, l'humain validera.
        return _handle_broken_extractor(
            cfg, platform, base_url, seeds, terms, target_categories, exc, _t0
        )

    # 3) SCORING (RAG) + PERSISTANCE, le tout dans une transaction.
    retriever = QdrantRuleRetriever.from_config(cfg)
    score_model = cfg.resolve_model("LLM-SCORE").model

    with transaction() as conn:
        run_id = create_run(
            conn, mode="A", trigger="api", actor="api",
            params={"seeds": seeds, "terms": len(terms), "target_categories": target_categories},
            config_snapshot={"platform": platform, "base_url": base_url},
        )
        pid = platform_id(conn, platform)
        if pid is None:
            finish_run(conn, run_id, status="failed", error=f"plateforme inconnue : {platform}", actor="api")
            raise ValueError(f"plateforme inconnue en base : {platform!r}")
        model_version_id = get_or_create_model_version(
            conn, agent="LLM-SCORE", model_name=score_model, prompt_version="score_v1",
        )

        # Scoring : le vrai goulot d'étranglement, ce sont les appels LLM (cloud).
        # On récupère les règles RAG séquentiellement (embedding local, non garanti
        # thread-safe), puis on lance le scoring LLM EN PARALLÈLE, et enfin on écrit
        # en base séquentiellement (rapide, connexion unique). En cloud, ça réduit
        # fortement la durée d'une recherche portant sur de nombreuses annonces.
        candidats = [it for it in listings if it.get("external_id")]
        regles = [
            retriever.retrieve(
                f"{it.get('title', '')} {it.get('description', '')}".strip()
            )
            for it in candidats
        ]

        def _scorer(pair: tuple[dict, list]) -> tuple[dict, dict]:
            it, rules = pair
            return it, score_listing(cfg, it, rules=rules)

        max_workers = min(8, max(1, len(candidats)))
        with ThreadPoolExecutor(max_workers=max_workers) as pool:
            resultats = list(pool.map(_scorer, zip(candidats, regles)))

        scored = 0
        alertes = 0
        par_categorie: dict[str, int] = {}
        for it, score in resultats:
            listing_id, _ = upsert_listing(
                conn, run_id=run_id, actor="api", platform_id=pid,
                external_id=str(it["external_id"]), content_hash=content_hash(it),
                url=it.get("url"), title=it.get("title"),
                description=it.get("description"),
                price_amount=it.get("price_amount"),
                price_currency=it.get("price_currency"),
                seller_label=it.get("seller"),
                structured={"location": it.get("location")},
            )
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

        # Journal d'étapes : déroulé synthétique et lisible de la recherche.
        etapes = {
            "expand": {"categories": target_categories, "termes": len(terms)},
            "collecte": {"annonces": len(listings)},
            "scoring": {"scorees": scored, "alertes": alertes, "par_categorie": par_categorie},
        }
        stats = {
            "terms": len(terms), "collected": len(listings), "scored": scored,
            "alertes": alertes, "etapes": etapes,
            "duree_s": round(time.monotonic() - _t0, 1),
        }
        finish_run(conn, run_id, status="completed", stats=stats, actor="api")

    return {"run_id": run_id, "terms": len(terms), "collected": len(listings), "scored": scored}