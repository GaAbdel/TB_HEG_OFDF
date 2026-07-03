#!/usr/bin/env python3
"""Démonstration du scoring sans RAG sur quelques annonces types.

Note 4 annonces représentatives — une explicite, une implicite, un piège, une
bénigne — et compare le verdict du modèle à ce qu'on attend. But : voir si le
LLM distingue ce qu'un détecteur par mots-clés raterait.

Usage :
    docker compose exec app python scripts/score_sample.py
"""

from __future__ import annotations

import time

from osint.analyse.scorer import score_listing
from osint.config import get_config

# (annonce, niveau attendu, catégorie attendue)
ECHANTILLON = [
    (
        {"title": "Cartouches de cigarettes (x10) — non taxées",
         "description": "Lot de 10 cartouches, jamais déclarées à la douane, livraison discrète possible.",
         "price_amount": 380, "price_currency": "CHF"},
        "explicite", "tabac",
    ),
    (
        {"title": "Gnôle maison du grand-père, au litre",
         "description": "Distillée à la ferme, bien forte, bouteilles non étiquetées, je cède le stock.",
         "price_amount": 60, "price_currency": "CHF"},
        "implicite", "alcool",
    ),
    (
        {"title": "Ivoire végétal (tagua) — bijoux artisanaux",
         "description": "Graines de tagua, alternative éthique et légale à l'ivoire animal.",
         "price_amount": 90, "price_currency": "CHF"},
        "piège", "aucune",
    ),
    (
        {"title": "Canapé 3 places — très bon état",
         "description": "Canapé tissu gris, confortable, à venir chercher.",
         "price_amount": 300, "price_currency": "CHF"},
        "bénigne", "aucune",
    ),
]


def main() -> None:
    cfg = get_config()
    # Porte de consentement LPD (topologie cloud = transfert vers un tiers).
    cfg.assert_lpd_compliance(consentement_cloud=True)

    print(f"Modèle : {cfg.resolve_model('LLM-SCORE').model}\n")
    for annonce, niveau, cat_attendue in ECHANTILLON:
        r = score_listing(cfg, annonce)
        accord = "OK " if r["category"] == cat_attendue else "!! "
        print(f"[{niveau:9}] {annonce['title']}")
        print(f"   attendu  : catégorie={cat_attendue}")
        print(f"   {accord}obtenu : score={r['suspicion_score']:.2f}  catégorie={r['category']}")
        print(f"   justification : {r['rationale']}")
        print()
        time.sleep(2)  # respecter la limite de débit (5 req/min en palier Free)


if __name__ == "__main__":
    main()