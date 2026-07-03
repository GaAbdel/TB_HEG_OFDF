"""Gestion des connexions PostgreSQL (couche d'accès).

Unique endroit du code qui ouvre des connexions : un pool partagé et un
gestionnaire de contexte `transaction()` garantissant commit/rollback
automatiques. Les imports lourds (psycopg_pool) sont lazy pour que ce
module reste importable sans la base.
"""

from __future__ import annotations
 
import os
from contextlib import contextmanager
from typing import TYPE_CHECKING, Iterator
 
from osint.config import Config, get_config
 
if TYPE_CHECKING:
    from psycopg import Connection
 
 
def dsn(cfg: Config | None = None) -> str:
    """Construit la chaîne de connexion depuis config.yaml + ${POSTGRES_PASSWORD}."""
    cfg = cfg or get_config()
    host = cfg.get("postgres", "host", default="postgres")
    port = cfg.get("postgres", "port", default=5432)
    db = cfg.get("postgres", "db", default="osint")
    user = cfg.get("postgres", "user", default="osint")
    pwd = os.environ.get("POSTGRES_PASSWORD", "")
    return f"postgresql://{user}:{pwd}@{host}:{port}/{db}"
 
 
_pool = None
 
 
def get_pool():
    """Pool de connexions partagé (créé paresseusement)."""
    global _pool
    if _pool is None:
        from psycopg.rows import dict_row
        from psycopg_pool import ConnectionPool
 
        _pool = ConnectionPool(
            conninfo=dsn(), min_size=1, max_size=10, open=False,
            kwargs={"row_factory": dict_row},
        )
        _pool.open()
    return _pool
 
 
def close_pool() -> None:
    """Ferme le pool (arrêt propre de l'application)."""
    global _pool
    if _pool is not None:
        _pool.close()
        _pool = None
 
 
@contextmanager
def transaction() -> Iterator["Connection"]:
    """Emprunte une connexion dans une transaction.
 
    Commit si le bloc se termine normalement, rollback si une exception est
    levée ; la connexion est rendue au pool à la sortie.
    """
    with get_pool().connection() as conn:
        with conn.transaction():
            yield conn