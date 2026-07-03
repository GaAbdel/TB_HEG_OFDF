#!/usr/bin/env python3
"""Démonstration soutenance — LLM-BROWSE en NAVIGATEUR VISIBLE.

Ce script lance une exploration Mode B avec Chromium VISIBLE (headless=False),
pour que le jury voie l'agent agir en direct : ouvrir la page, fermer le pop-up
métier, parcourir les annonces, révéler un numéro masqué. Chaque action et son
raisonnement déclaré sont journalisés, puis scellés dans le journal d'audit.

IMPORTANT — à lancer depuis l'HÔTE (pas dans Docker) :
Le conteneur `app` n'a pas d'affichage ; pour VOIR le navigateur, on exécute ce
script sur la machine hôte, qui vise le site de démo exposé sur localhost:8002.

Prérequis (sur l'hôte, dans le venv) :
    pip install -r requirements.txt
    playwright install chromium
    export LLM_API_KEY=...            # (Git Bash : export ; PowerShell : $env:)
    docker compose --profile dev up -d mock_shop     # site de démo sur :8002

Usage :
    python scripts/demo_soutenance.py            # v1 (structure saine)
    python scripts/demo_soutenance.py v2         # v2 (structure différente)
"""

from __future__ import annotations

import asyncio
import sys

from osint.analyse.browse import run_browse
from osint.config import get_config

# Depuis l'hôte, le site de démo est exposé sur le port 8002.
BASE = "http://localhost:8002"


async def main() -> None:
    version = sys.argv[1] if len(sys.argv) > 1 else "v1"
    start_url = f"{BASE}/{version}"
    cfg = get_config()

    print("=" * 64)
    print("  DÉMONSTRATION — LLM-BROWSE (Mode B), navigateur visible")
    print("=" * 64)
    print(f"  Site cible      : {start_url}")
    print("  Périmètre borné : le domaine du site uniquement (garde-fou)")
    print("  Le navigateur va s'ouvrir. Observez : fermeture du pop-up,")
    print("  parcours des annonces, révélation du numéro masqué.")
    print("=" * 64)

    # headless=False -> fenêtre Chromium visible pour le jury.
    res = await run_browse(cfg, start_url, max_steps=20, headless=False)

    print("\n" + "=" * 64)
    print("  RÉSULTAT (relevé au mieux de l'agent)")
    print("=" * 64)
    print(res["result"])

    if res.get("audit_log"):
        print("\n" + "-" * 64)
        print("  TRAÇABILITÉ — chaque action est scellée (chaîne de hash)")
        print("-" * 64)
        print(f"  Journal : {res['audit_log']}")
        print("  Vérifier l'intégrité (falsification détectable) :")
        print(f"    python scripts/verify_browse_log.py {res['audit_log']}")


if __name__ == "__main__":
    asyncio.run(main())