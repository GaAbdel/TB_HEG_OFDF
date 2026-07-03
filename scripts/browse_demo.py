#!/usr/bin/env python3
"""Démo LLM-BROWSE (Mode B) — exploration bornée du mock_shop v2.

L'agent part de la page de liste, doit paginer (« Suivant ») pour voir toutes
les annonces, ouvrir chaque détail, et révéler le numéro masqué (bouton JS).
Le tout sous périmètre borné (allowed_domains) et budget de pas (max_steps).

Prérequis : service mock_shop joignable (profil dev), clé API dans l'env.

Usage :
    docker compose exec app python scripts/browse_demo.py
"""

from __future__ import annotations

import asyncio

from osint.analyse.browse import run_browse
from osint.config import get_config

START_URL = "http://mock_shop:8000/v2"


async def main() -> None:
    cfg = get_config()
    res = await run_browse(cfg, START_URL, max_steps=18)

    print(f"\nModèle           : {res['model']}")
    print(f"Périmètre borné  : {res['allowed_domains']}")
    print(f"Budget de pas    : {res['max_steps']}")
    print("\n===== RÉSULTAT =====")
    print(res["result"])

    if res["trace"]:
        print("\n----- Trace (audit) -----")
        for k, v in res["trace"].items():
            print(f"  {k}: {v}")

    if res.get("audit_log"):
        print(f"\nJournal d'audit scellé : {res['audit_log']}")
        print("Vérifier l'intégrité :")
        print(f"  docker compose exec app python scripts/verify_browse_log.py {res['audit_log']}")


if __name__ == "__main__":
    asyncio.run(main())