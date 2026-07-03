"""Accès Qdrant (mémoire sémantique).

Sonde de connectivité + vérification de présence des deux collections
attendues (customs_rules, confirmed_suspicious).
"""

from __future__ import annotations

from osint.config import Config


def _client(cfg: Config):
    from qdrant_client import QdrantClient  # import paresseux

    host = cfg.get("qdrant", "host", default="qdrant")
    port = cfg.get("qdrant", "port", default=6333)
    return QdrantClient(host=host, port=port, timeout=3)


def expected_collections(cfg: Config) -> list[str]:
    coll = cfg.get("qdrant", "collections", default={}) or {}
    return list(coll.values())


def ping(cfg: Config) -> tuple[bool, str]:
    """Vérifie la connectivité Qdrant et la présence des collections. Ne lève jamais."""
    try:
        import qdrant_client  # noqa: F401
    except ImportError:
        return False, "qdrant-client non installé"
    try:
        client = _client(cfg)
        present = {c.name for c in client.get_collections().collections}
        attendues = set(expected_collections(cfg))
        manquantes = attendues - present
        if manquantes:
            return False, f"collections manquantes : {sorted(manquantes)}"
        return True, "ok"
    except Exception as exc:  # noqa: BLE001 — sonde tolérante
        return False, str(exc)