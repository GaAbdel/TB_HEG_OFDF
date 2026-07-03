#!/usr/bin/env python3
"""Smoke tests post-déploiement.

Interroge successivement chaque service de la pile et vérifie la cohérence de
base du déploiement.

Usage :
    python scripts/smoke_test.py            # cible http://localhost:8000
    APP_URL=http://app:8000 python scripts/smoke_test.py
"""

from __future__ import annotations

import os
import sys

import httpx

APP_URL = os.environ.get("APP_URL", "http://localhost:8000")


def check_health() -> bool:
    print(f"[smoke] GET {APP_URL}/health")
    try:
        r = httpx.get(f"{APP_URL}/health", timeout=10)
    except Exception as exc:  # noqa: BLE001
        print(f"  ECHEC : API injoignable ({exc})")
        return False

    payload = r.json()
    print(f"  status={payload.get('status')} topologie={payload.get('topologie')}")
    for name, c in payload.get("checks", {}).items():
        mark = "OK " if c["ok"] else "KO "
        print(f"    [{mark}] {name:10s} {c['detail']}")
    return r.status_code == 200


def main() -> int:
    print("=== Smoke test — déploiement OSINT douane ===")
    ok = check_health()
    # TODO(phase pipeline) : injecter une fixture HTML et vérifier qu'un score
    # est produit de bout en bout.
    print("=== Résultat :", "SUCCES" if ok else "ECHEC", "===")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())