#!/usr/bin/env python3
"""Régénère les fixtures HTML du faux marché (pour tests/test_parsers.py).

Capture quelques pages du faux marché EN MÉMOIRE (via TestClient, sans lancer
de serveur) et les écrit dans tests/fixtures/fake_market/. Les fixtures sont
ensuite versionnées : les tests d'extraction deviennent stables et reproductibles.

Usage (racine, venv actif avec fastapi + httpx) :
    python scripts/capture_fixtures.py
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT / "fake_market"))

import app as fm  # noqa: E402  (le faux marché)
from fastapi.testclient import TestClient  # noqa: E402

OUT = ROOT / "tests" / "fixtures" / "fake_market"
OUT.mkdir(parents=True, exist_ok=True)

PAGES = {
    "search_page1.html": "/search?page=1",   # page de résultats (pagination)
    "listing_9004.html": "/listing/9004",     # positif explicite (CITES, éléphant)
    "listing_8000.html": "/listing/8000",     # piège (ivoire végétal tagua)
    "listing_1000.html": "/listing/1000",     # annonce bénigne
}


def main() -> None:
    client = TestClient(fm.app)
    for name, path in PAGES.items():
        (OUT / name).write_text(client.get(path).text, encoding="utf-8")
        print(f"  {name}  <-  {path}")
    print(f"Fixtures écrites dans {OUT}")


if __name__ == "__main__":
    main()