#!/usr/bin/env python3
"""Démo bout-en-bout : LLM-EXPAND -> collecte ciblée sur le faux marché.

Élargit quelques termes de départ via LLM-EXPAND, puis collecte uniquement les
annonces qui correspondent à ces termes (recherche `?q=` par terme, résultats
dédupliqués). Illustre la chaîne amont complète : terme -> expansion -> collecte.

Usage (faux marché actif) :
    docker compose --profile dev up -d
    docker compose exec app python scripts/collect_with_expand.py
"""

from __future__ import annotations

import asyncio

from osint.analyse.expander import expand_terms
from osint.collecte.fake_market_extractor import FakeMarketExtractor
from osint.collecte.guardrails import Guardrails
from osint.config import get_config

BASE_URL = "http://fake_market:8000"
PLATFORM = "fake_market"
SEEDS = ["cigarettes", "ivoire"]


async def main() -> None:
    cfg = get_config()
    cfg.assert_lpd_compliance(consentement_cloud=True)

    # 1) Expansion des termes de départ (LLM-EXPAND).
    terms: list[str] = []
    for seed in SEEDS:
        r = expand_terms(cfg, seed)
        print(f"« {seed} »  ->  {len(r['terms'])} termes")
        terms.extend(r["terms"])
    terms = list(dict.fromkeys(terms))  # dédup en gardant l'ordre
    print(f"\nTotal : {len(terms)} termes de recherche enrichis.\n")

    # 2) Collecte ciblée sous garde-fous (une recherche ?q= par terme).
    guardrails = Guardrails.from_config(cfg, allowlist=[PLATFORM], action_budget=500)
    concurrency = cfg.get("collecte", "concurrence_max", default=4)
    extractor = FakeMarketExtractor(BASE_URL, guardrails, concurrency=concurrency, terms=terms)
    listings = await extractor.run()

    print(f"Collecte ciblée : {len(listings)} annonces "
          f"(actions consommées : {guardrails.actions_used}).\n")
    for it in listings[:15]:
        print(f"  - {it.get('title')}")
    if len(listings) > 15:
        print(f"  … (+{len(listings) - 15} autres)")


if __name__ == "__main__":
    asyncio.run(main())