#!/usr/bin/env python3
"""Vérifie l'intégrité d'un journal d'audit LLM-BROWSE (chaîne de hash scellée).

Démontre l'auditabilité : si une seule ligne du journal est modifiée, la
vérification échoue et pointe la première anomalie.

Usage :
    docker compose exec app python scripts/verify_browse_log.py data/audit/browse_XXXX.jsonl
"""

from __future__ import annotations

import sys

from osint.analyse.browse_audit import read_browse_log, verify_browse_log


def main() -> None:
    if len(sys.argv) < 2:
        raise SystemExit("Usage : verify_browse_log.py <chemin_du_journal.jsonl>")
    path = sys.argv[1]

    entries = read_browse_log(path)
    ok, idx = verify_browse_log(path)

    print(f"Journal     : {path}")
    print(f"Entrées     : {len(entries)}")
    if ok:
        print("Intégrité   : ✅ INTACTE (chaîne de hash vérifiée)")
    else:
        print(f"Intégrité   : ❌ ROMPUE à l'entrée #{idx} (falsification détectée)")

    print("\nActions journalisées :")
    for e in entries:
        detail = e.get("detail", {})
        loc = detail.get("url") or detail.get("start_url") or ""
        print(f"  [{e['action']}] {loc}")
        reasoning = detail.get("reasoning")
        if reasoning and reasoning.get("next_goal"):
            print(f"      ↳ but : {reasoning['next_goal']}")


if __name__ == "__main__":
    main()