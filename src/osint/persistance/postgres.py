"""Accès PostgreSQL (mémoire épisodique).

Pour l'instant : sonde de connectivité utilisée par /health. 
"""

from __future__ import annotations

import os

from osint.config import Config


def dsn(cfg: Config) -> str:
    """Construit la chaine de connexion a partir de config.yaml + env."""
    host = cfg.get("postgres", "host", default="postgres")
    port = cfg.get("postgres", "port", default=5432)
    db = cfg.get("postgres", "db", default="osint")
    user = cfg.get("postgres", "user", default="osint")
    password = os.environ.get("POSTGRES_PASSWORD", "")
    return f"postgresql://{user}:{password}@{host}:{port}/{db}"


def ping(cfg: Config) -> tuple[bool, str]:
    """Vérifie la connectivité PostgreSQL. Ne lève jamais."""
    try:
        import psycopg  # import paresseux
    except ImportError:
        return False, "psycopg non installé"
    try:
        with psycopg.connect(dsn(cfg), connect_timeout=3) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT 1")
                cur.fetchone()
        return True, "ok"
    except Exception as exc:  # noqa: BLE001 — sonde tolérante
        return False, str(exc)