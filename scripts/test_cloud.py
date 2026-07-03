#!/usr/bin/env python3
"""Test minimal de l'accès au modèle, un seul appel.

Valide en une fois : la clé API, le routage LiteLLM vers le fournisseur, et le
franchissement du garde-fou LPD. Coût négligeable (une poignée de tokens).

Usage :
    docker compose exec app python scripts/test_cloud.py
"""

from __future__ import annotations

from osint.config import get_config
from osint.model.litellm_client import complete


def main() -> None:
    cfg = get_config()

    # Porte de consentement LPD : on reconnaît explicitement que la topologie
    # cloud transmet des données à un fournisseur tiers.
    # En topologie locale/centrale, cet appel ne fait rien (pas de transfert).
    cfg.assert_lpd_compliance(consentement_cloud=True)

    spec = cfg.resolve_model()
    print(f"Topologie active : {cfg.topologie}")
    print(f"Modèle résolu    : {spec.model}")
    print("Envoi d'un appel de test...")

    reponse = complete(
        cfg,
        messages=[{"role": "user", "content": "Réponds uniquement par le mot : OK"}],
        max_tokens=10,
    )
    print(f"Réponse du modèle : {reponse.strip()!r}")


if __name__ == "__main__":
    main()