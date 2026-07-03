"""Chaîne de traçabilité — journal d'audit.

Chaque entrée scelle la précédente :

    entry_hash = SHA-256(prev_hash + contenu_canonique)

Altérer ou supprimer une entrée casse tous les hash en aval, ce qui rend la
falsification détectable. La logique de hachage est testable sans base;
seules `append()` et `verify_db_chain()` touchent PostgreSQL.
"""


from __future__ import annotations
 
import hashlib
import json
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any
 
if TYPE_CHECKING:
    from psycopg import Connection
 
# Champs scellés par le hash. L'ordre est sans importance (sérialisation triée).
SEALED_FIELDS = ("run_id", "listing_id", "actor", "action", "detail", "created_at")
 
# Clé de verrou consultatif : sérialise les ajouts concurrents (voir append).
_AUDIT_LOCK_KEY = 4319
 
 
def _canonical(payload: dict[str, Any]) -> str:
    """Sérialisation JSON déterministe (clés triées, séparateurs fixes)."""
    return json.dumps(
        payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str
    )
 
 
def compute_entry_hash(prev_hash: str | None, payload: dict[str, Any]) -> str:
    """Hash d'une entrée : SHA-256(prev_hash + contenu canonique)."""
    base = (prev_hash or "") + _canonical(payload)
    return hashlib.sha256(base.encode("utf-8")).hexdigest()
 
 
def _payload(entry: dict[str, Any]) -> dict[str, Any]:
    """Projette une entrée sur ses seuls champs scellés."""
    return {k: entry.get(k) for k in SEALED_FIELDS}
 
 
def seal(prev_hash: str | None, entry: dict[str, Any]) -> dict[str, Any]:
    """Complète une entrée avec son prev_hash et son entry_hash."""
    entry_hash = compute_entry_hash(prev_hash, _payload(entry))
    return {**entry, "prev_hash": prev_hash, "entry_hash": entry_hash}
 
 
def verify_chain(entries: list[dict[str, Any]]) -> tuple[bool, int | None]:
    """Vérifie l'intégrité d'une séquence ordonnée d'entrées.
 
    Retourne (True, None) si la chaîne est intacte, sinon (False, index) où
    `index` est la position de la première anomalie (contenu altéré, maillon
    rompu, insertion, suppression ou réordonnancement).
    """
    prev = None
    for i, e in enumerate(entries):
        if e.get("prev_hash") != prev:                                  # maillon rompu
            return False, i
        if e.get("entry_hash") != compute_entry_hash(prev, _payload(e)):  # contenu altéré
            return False, i
        prev = e["entry_hash"]
    return True, None
 
 
# --- Accès base ---------------------------------------------------------------
def append(
    conn: "Connection",
    *,
    actor: str,
    action: str,
    detail: dict[str, Any] | None = None,
    run_id: int | None = None,
    listing_id: int | None = None,
) -> dict[str, Any]:
    """Ajoute une entrée d'audit scellée. À appeler DANS une transaction.
 
    Un verrou consultatif transactionnel sérialise les ajouts concurrents :
    sans lui, deux transactions pourraient lire la même tête de chaîne et la
    bifurquer.
    """
    from psycopg.types.json import Jsonb
 
    conn.execute("SELECT pg_advisory_xact_lock(%s)", (_AUDIT_LOCK_KEY,))
    row = conn.execute(
        "SELECT entry_hash FROM audit_log ORDER BY id DESC LIMIT 1"
    ).fetchone()
    prev_hash = row["entry_hash"] if row else None
 
    created_at = datetime.now(timezone.utc)
    entry = {
        "run_id": run_id,
        "listing_id": listing_id,
        "actor": actor,
        "action": action,
        "detail": detail or {},
        "created_at": created_at.isoformat(),
    }
    sealed = seal(prev_hash, entry)
 
    conn.execute(
        "INSERT INTO audit_log (run_id, listing_id, actor, action, detail, "
        "prev_hash, entry_hash, created_at) VALUES (%s,%s,%s,%s,%s,%s,%s,%s)",
        (
            run_id,
            listing_id,
            actor,
            action,
            Jsonb(detail or {}),
            sealed["prev_hash"],
            sealed["entry_hash"],
            created_at,
        ),
    )
    return sealed
 
 
def verify_db_chain(conn: "Connection") -> tuple[bool, int | None]:
    """Relit tout le journal depuis la base et vérifie la chaîne.
 
    Hypothèse : session PostgreSQL en UTC (cas par défaut de l'image postgres)
    pour que created_at.isoformat() reconstruise exactement la valeur scellée.
    """
    rows = conn.execute(
        "SELECT run_id, listing_id, actor, action, detail, prev_hash, entry_hash, "
        "created_at FROM audit_log ORDER BY id"
    ).fetchall()
    entries = [
        {
            "run_id": r["run_id"],
            "listing_id": r["listing_id"],
            "actor": r["actor"],
            "action": r["action"],
            "detail": r["detail"],
            "prev_hash": r["prev_hash"],
            "entry_hash": r["entry_hash"],
            "created_at": r["created_at"].isoformat(),
        }
        for r in rows
    ]
    return verify_chain(entries)