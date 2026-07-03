#!/usr/bin/env python3
"""Démo LLM-CODE : réparation autonome d'un extracteur cassé.

L'extracteur déterministe est calé sur la structure v1 du mock_shop. On lui
soumet une page v2 (structure changée) : les sélecteurs échouent. LLM-CODE
inspecte le HTML et propose de nouveaux sélecteurs jusqu'à réextraire les
champs requis.

Le HTML v2 est rendu localement (pas besoin de serveur). Seul l'agent de
réparation appelle le vrai modèle.

Usage :
    docker compose exec app python scripts/code_repair_demo.py
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

from fastapi.testclient import TestClient

from osint.analyse.code_repair import make_llm_repair_fn, repair_selectors
from osint.collecte.selector_extractor import V1_SELECTORS
from osint.config import get_config

# Rendu local de la page v2 du mock_shop (sans serveur).
ROOT = Path(__file__).resolve().parent.parent
_spec = importlib.util.spec_from_file_location("mock_shop_app", ROOT / "mock_shop" / "app.py")
shop = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(shop)
HTML_V2 = TestClient(shop.app).get("/v2/listing/1").text


def main() -> None:
    cfg = get_config()
    cfg.assert_lpd_compliance(consentement_cloud=True)
    print(f"Modèle : {cfg.resolve_model('LLM-CODE').model}")
    print(f"Sélecteurs de départ (v1) : {V1_SELECTORS}\n")

    llm_fn = make_llm_repair_fn(cfg)
    res = repair_selectors(llm_fn, HTML_V2, V1_SELECTORS, max_iters=3)

    print(f"Réparé : {res['ok']}  (itérations : {res['iterations']})")
    print(f"Sélecteurs finaux : {res['selectors']}")
    print(f"Champs extraits   : {res['record']}\n")
    print("Historique :")
    for h in res["history"]:
        print(f"  passe {h['iteration']} — manquants : {h['missing']}")


if __name__ == "__main__":
    main()