#!/usr/bin/env python3
"""Démonstration de LLM-EXPAND : élargit quelques termes de départ.

Usage :
    docker compose exec app python scripts/expand_demo.py
"""

from __future__ import annotations

import time

from osint.analyse.expander import expand_terms
from osint.config import get_config

SEEDS = ["cigarettes", "ivoire", "eau-de-vie maison", "montre de luxe"]


def main() -> None:
    cfg = get_config()
    cfg.assert_lpd_compliance(consentement_cloud=True)
    print(f"Modèle : {cfg.resolve_model('LLM-EXPAND').model}\n")
    for seed in SEEDS:
        r = expand_terms(cfg, seed)
        print(f"« {seed} »  ->  {', '.join(r['terms'])}")
        time.sleep(2)


if __name__ == "__main__":
    main()