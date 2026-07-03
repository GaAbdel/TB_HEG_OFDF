#!/usr/bin/env python3
"""Smoke test Browser-Use — vérifie que l'agent démarre, voit le navigateur
et navigue sur le mock_shop. PERMISSIF exprès (pas encore de garde-fous) :
le but est seulement de valider la base technique avant de construire le vrai
LLM-BROWSE bridé.

Prérequis :
  - browser-use==0.12.9 installé dans l'image
  - service mock_shop joignable à http://mock_shop:8000 (profil dev)
  - clé API disponible dans l'environnement du conteneur (LLM_API_KEY)

Usage :
    docker compose exec app python scripts/browse_smoke.py
"""

from __future__ import annotations

import asyncio
import os

from browser_use import Agent

# Le wrapper Anthropic peut être exposé à deux endroits selon la version.
try:
    from browser_use import ChatAnthropic  # 0.12.x
except ImportError:  # repli éventuel
    from browser_use.llm import ChatAnthropic  # type: ignore

# La session navigateur porte les futurs garde-fous (ici : minimal).
try:
    from browser_use.browser import BrowserSession
except ImportError:  # repli selon version
    from browser_use import BrowserSession  # type: ignore

MODEL = "claude-haiku-4-5-20251001"
API_KEY = os.environ.get("LLM_API_KEY") or os.environ.get("ANTHROPIC_API_KEY")


async def main() -> None:
    if not API_KEY:
        raise SystemExit("Aucune clé API trouvée (LLM_API_KEY / ANTHROPIC_API_KEY).")

    session = BrowserSession(headless=True)  # smoke : pas de allowed_domains encore

    agent = Agent(
        task=(
            "Va sur http://mock_shop:8000/v2 et donne-moi la liste des titres "
            "d'annonces visibles sur la page."
        ),
        llm=ChatAnthropic(model=MODEL, api_key=API_KEY),
        browser_session=session,
        use_vision=False,  # plus léger, pas de capture d'écran
    )

    history = await agent.run(max_steps=8)
    print("\n===== RÉSULTAT =====")
    print(history.final_result())


if __name__ == "__main__":
    asyncio.run(main())