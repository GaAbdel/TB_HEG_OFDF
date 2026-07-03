#!/usr/bin/env python3
"""Collecte le faux marché avec un vrai navigateur, PUIS persiste en base.

Premier flux complet collecte -> base :
  1. Playwright navigue le faux marché sous garde-fous (Mode A).
  2. On ouvre une transaction « tout ou rien ».
  3. create_run : on ouvre un dossier de session.
  4. persist_listings : chaque annonce est insérée ou ré-observée (dédup),
     et l'audit_log se remplit automatiquement.
  5. finish_run : on clôt le dossier avec le bilan.

Usage (faux marché actif) :
    docker compose --profile dev up -d
    docker compose exec app python scripts/collect_fake_market.py
"""

from __future__ import annotations

import asyncio

from osint.collecte.fake_market_extractor import FakeMarketExtractor
from osint.collecte.guardrails import Guardrails
from osint.config import get_config
from osint.persistance.db import transaction
from osint.persistance.repositories import create_run, finish_run
from osint.persistance.store import persist_listings

BASE_URL = "http://fake_market:8000"
PLATFORM = "fake_market"


async def collecter() -> tuple[list[dict], int]:
    """Lance la collecte et renvoie (annonces, actions consommées)."""
    cfg = get_config()
    # Dev : allowlist = faux marché, budget généreux pour un balayage complet.
    guardrails = Guardrails.from_config(cfg, allowlist=[PLATFORM], action_budget=500)
    concurrency = cfg.get("collecte", "concurrence_max", default=4)
    extractor = FakeMarketExtractor(BASE_URL, guardrails, concurrency=concurrency)
    listings = await extractor.run()
    return listings, guardrails.actions_used


def persister(listings: list[dict]) -> tuple[int, dict]:
    """Écrit les annonces en base dans une transaction. Renvoie (run_id, bilan)."""
    with transaction() as conn:
        run_id = create_run(
            conn,
            mode="A",
            trigger="manuel",
            actor="collector",
            config_snapshot={"base_url": BASE_URL, "platform": PLATFORM},
        )
        stats = persist_listings(
            conn, run_id=run_id, platform_name=PLATFORM, listings=listings, actor="collector"
        )
        finish_run(conn, run_id, status="completed", stats=stats, actor="collector")
    return run_id, stats


async def main() -> None:
    listings, actions = await collecter()
    print(f"=== Collecte : {len(listings)} annonces ({actions} actions) ===")

    run_id, stats = persister(listings)
    print(f"=== Persistance : run #{run_id} ===")
    print(f"  nouvelles : {stats['inserted']}")
    print(f"  ré-observées : {stats['observed']}")
    if stats["skipped"]:
        print(f"  ignorées (sans id) : {stats['skipped']}")


if __name__ == "__main__":
    asyncio.run(main())