#!/usr/bin/env python3
"""Ingestion du corpus de règles douanières dans Qdrant (collection customs_rules).

Lit data/rules/*.md, découpe par règle (### = un chunk), vectorise chaque règle
avec e5 (préfixe « passage: »), et indexe le tout dans Qdrant avec ses
métadonnées (catégorie, source, URL). Idempotent : ré-ingérer remplace les mêmes
règles (id déterministe dérivé de source+titre).

Prérequis : la collection existe (scripts/init_qdrant.py).

Usage :
    docker compose exec app python scripts/init_qdrant.py     # une fois
    docker compose exec app python scripts/ingest_rules.py
"""

from __future__ import annotations

import uuid
from pathlib import Path

from osint.analyse.embeddings import embed_passages
from osint.analyse.rules_corpus import parse_markdown_rules, rule_embedding_text
from osint.config import get_config
from osint.persistance.qdrant import _client

RULES_DIR = Path("/app/data/rules")
COLLECTION = "customs_rules"
# Espace de noms fixe -> id stable par règle (ré-ingestion = remplacement).
NAMESPACE = uuid.uuid5(uuid.NAMESPACE_DNS, "osint-ofdf.customs_rules")


def main() -> None:
    cfg = get_config()

    files = sorted(RULES_DIR.glob("*.md"))
    if not files:
        raise SystemExit(f"Aucun fichier .md dans {RULES_DIR}")
    rules: list[dict] = []
    for f in files:
        rules += parse_markdown_rules(f.read_text(encoding="utf-8"))
    print(f"{len(rules)} règles lues depuis {len(files)} fichier(s).")

    # Vectorisation (préfixe passage appliqué dans embed_passages).
    vectors = embed_passages(cfg, [rule_embedding_text(r) for r in rules])

    from qdrant_client.models import PointStruct

    points = [
        PointStruct(
            id=str(uuid.uuid5(NAMESPACE, f"{r['source']}|{r['title']}")),
            vector=vec,
            payload={
                "title": r["title"],
                "category": r["category"],
                "source": r["source"],
                "url": r["url"],
                "text": r["text"],
            },
        )
        for r, vec in zip(rules, vectors)
    ]

    client = _client(cfg)
    client.upsert(collection_name=COLLECTION, points=points)
    info = client.get_collection(COLLECTION)
    print(f"Indexé {len(points)} règles -> collection '{COLLECTION}' "
          f"(total : {info.points_count} points).")


if __name__ == "__main__":
    main()