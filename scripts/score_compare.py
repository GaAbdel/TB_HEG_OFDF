#!/usr/bin/env python3
"""Compare le scoring « nu » (sans règles) au scoring « RAG » (règles injectées).

Sur des cas choisis pour leur dépendance à des règles précises (seuils suisses,
distinction d'espèces), on score chaque annonce DEUX fois et on affiche les
règles que le RAG a récupérées. But : rendre visible l'apport du RAG.

Usage (corpus de règles déjà ingéré) :
    docker compose exec app python scripts/score_compare.py
"""

from __future__ import annotations

import time

from osint.analyse.retriever import QdrantRuleRetriever
from osint.analyse.scorer import score_listing
from osint.config import get_config

ECHANTILLON = [
    {"title": "Gnôle maison du grand-père, au litre",
     "description": "Distillée à la ferme, bien forte, bouteilles non étiquetées, je cède le stock."},
    {"title": "Ivoire végétal (tagua) — bijoux artisanaux",
     "description": "Graines de tagua, alternative éthique et légale à l'ivoire animal."},
    {"title": "Caviar importé, ramené de voyage",
     "description": "Pot de 200 g de caviar, jamais ouvert, à céder."},
]


def _texte(a: dict) -> str:
    return f"{a['title']}. {a['description']}"


def main() -> None:
    cfg = get_config()
    cfg.assert_lpd_compliance(consentement_cloud=True)
    retriever = QdrantRuleRetriever.from_config(cfg)

    for annonce in ECHANTILLON:
        print("=" * 70)
        print(annonce["title"])

        rules = retriever.retrieve(_texte(annonce))
        if rules:
            print("  règles récupérées :")
            for r in rules:
                print(f"    · {r['score']:.2f}  [{r['category']}] {r['title']}")
        else:
            print("  règles récupérées : aucune (sous le seuil)")

        nu = score_listing(cfg, annonce)
        time.sleep(3)
        rag = score_listing(cfg, annonce, rules=rules)
        time.sleep(3)

        print(f"  NU  : score={nu['suspicion_score']:.2f}  catégorie={nu['category']}")
        print(f"  RAG : score={rag['suspicion_score']:.2f}  catégorie={rag['category']}")
        print(f"        justification RAG : {rag['rationale']}")
    print("=" * 70)


if __name__ == "__main__":
    main()