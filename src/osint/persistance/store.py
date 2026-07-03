"""Persistance d'une collecte : écrit les annonces en base, de façon traçable.

Orchestre les briques atomiques du repository (`upsert_listing`) pour
transformer une liste d'annonces collectées (de simples dicts) en lignes de la
base, avec déduplication (clé naturelle platform_id+external_id) et journal
d'audit automatique. Ne dépend PAS de la couche de collecte : reçoit des dicts.
"""

from __future__ import annotations

import hashlib
import json
from typing import TYPE_CHECKING

from osint.persistance import repositories as repo

if TYPE_CHECKING:
    from psycopg import Connection

# Champs qui composent l'empreinte de CONTENU (pour détecter un changement).
_HASHED_FIELDS = ("title", "description", "price_amount", "price_currency", "seller", "location")


def content_hash(listing: dict) -> str:
    """Empreinte SHA-256 stable du contenu d'une annonce.

    Sert à repérer qu'une annonce déjà vue a changé (prix, titre...) d'une
    collecte à l'autre. Indépendante de l'ordre des champs.
    """
    payload = {k: listing.get(k) for k in _HASHED_FIELDS}
    blob = json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def persist_listings(
    conn: "Connection",
    *,
    run_id: int,
    platform_name: str,
    listings: list[dict],
    actor: str = "collector",
) -> dict:
    """Écrit toutes les annonces sous la plateforme `platform_name`.

    Pour chaque annonce : `upsert_listing` (insère ou ré-observe selon la clé
    naturelle), qui enregistre aussi l'observation du run et trace l'action.
    Renvoie un bilan : {'total', 'inserted', 'observed', 'skipped'}.
    """
    pid = repo.platform_id(conn, platform_name)
    if pid is None:
        raise ValueError(f"plateforme inconnue en base : {platform_name!r}")

    inserted = observed = skipped = 0
    for it in listings:
        ext = it.get("external_id")
        if not ext:
            # Pas d'identifiant -> dédup impossible (cf. cascade de repli des
            # vrais extracteurs). Sur le faux marché, ne devrait pas arriver.
            skipped += 1
            continue
        _, is_new = repo.upsert_listing(
            conn,
            run_id=run_id,
            actor=actor,
            platform_id=pid,
            external_id=str(ext),
            content_hash=content_hash(it),
            url=it.get("url"),
            title=it.get("title"),
            description=it.get("description"),
            price_amount=it.get("price_amount"),
            price_currency=it.get("price_currency"),
            seller_label=it.get("seller"),
            structured={
                "location": it.get("location"),
                "source_platform_tag": it.get("platform"),
            },
        )
        if is_new:
            inserted += 1
        else:
            observed += 1

    return {
        "total": len(listings),
        "inserted": inserted,
        "observed": observed,
        "skipped": skipped,
    }