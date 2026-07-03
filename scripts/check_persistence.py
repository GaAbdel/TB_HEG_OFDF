#!/usr/bin/env python3
"""Vérification d'intégration de la couche persistance (contre la base réelle).

Exécute un mini-flux de bout en bout — run -> annonce + observation -> score ->
feedback -> ingestion -> clôture du run — puis vérifie la chaîne d'audit. Le
tout est annulé par un ROLLBACK final : la base reste intacte (aucune donnée de
test laissée).

Usage :
    docker compose exec app python scripts/check_persistence.py
"""

from __future__ import annotations

from osint.persistance import audit, db
from osint.persistance import repositories as repo


def main() -> int:
    pool = db.get_pool()
    with pool.connection() as conn:
        conn.autocommit = False
        try:
            run_id = repo.create_run(conn, mode="A", trigger="check")
            mv_id = repo.get_or_create_model_version(
                conn, agent="LLM-SCORE", model_name="ollama/qwen3:8b",
                prompt_version="score_v1", topology="locale",
            )
            pid = repo.platform_id(conn, "ricardo")
            listing_id, is_new = repo.upsert_listing(
                conn, run_id=run_id, actor="LLM-PARSE", platform_id=pid,
                external_id="CHECK-123", content_hash="hash-v1",
                title="Cartouches de cigarettes x200", structured={"qty": 200},
            )
            score_id = repo.add_score(
                conn, run_id=run_id, listing_id=listing_id, model_version_id=mv_id,
                category="tabac", suspicion_score=0.92,
                rationale="200 cartouches en vente privée",
                rag_refs=[{"rule": "LTab"}],
            )
            feedback_id = repo.add_feedback(
                conn, listing_id=listing_id, score_id=score_id,
                investigator_ref="enq-01", decision="confirme",
            )
            pending_before = repo.pending_ingestion(conn)
            repo.mark_ingested(conn, feedback_id)
            pending_after = repo.pending_ingestion(conn)
            repo.finish_run(conn, run_id, status="completed",
                            stats={"listings": 1, "scores": 1})

            ok, idx = audit.verify_db_chain(conn)

            print("=== Vérification d'intégration — couche persistance ===")
            print(f"  run={run_id}  model_version={mv_id}  platform_id={pid}")
            print(f"  annonce={listing_id} (nouvelle={is_new})  score={score_id}  feedback={feedback_id}")
            print(f"  en attente d'ingestion : avant={len(pending_before)} après={len(pending_after)}")
            print(f"  chaîne d'audit valide : {ok} (anomalie={idx})")
            print("  ROLLBACK — la base reste intacte.")
            return 0 if ok and not pending_after else 1
        finally:
            conn.rollback()


if __name__ == "__main__":
    raise SystemExit(main())