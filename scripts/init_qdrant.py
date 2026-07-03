#!/usr/bin/env python3
"""Initialise les collections Qdrant (mémoire sémantique).

Crée les deux collections `customs_rules` et `confirmed_suspicious`
avec la dimension d'embedding multilingual-e5-large (1024) et la distance cosinus. Idempotent :
une collection déjà présente est ignorée.

Usage (depuis le conteneur app, qui a accès au réseau Docker) :
    docker compose exec app python scripts/init_qdrant.py
"""

from __future__ import annotations

from qdrant_client import QdrantClient
from qdrant_client.models import Distance, VectorParams

from osint.config import get_config


def main() -> int:
    cfg = get_config()
    host = cfg.get("qdrant", "host", default="qdrant")
    port = cfg.get("qdrant", "port", default=6333)
    dim = int(cfg.get("embeddings", "dimension", default=1024))
    collections = cfg.get("qdrant", "collections", default={}) or {}

    client = QdrantClient(host=host, port=port, timeout=10)
    existing = {c.name for c in client.get_collections().collections}

    for logical, name in collections.items():
        if name in existing:
            print(f"[init-qdrant] '{name}' existe déjà — ignorée")
            continue
        client.create_collection(
            collection_name=name,
            vectors_config=VectorParams(size=dim, distance=Distance.COSINE),
        )
        print(f"[init-qdrant] '{name}' créée (dim={dim}, cosine)")

    print("[init-qdrant] terminé.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())