"""Extraction déterministe pilotée par une configuration de sélecteurs.

Plutôt que des sélecteurs codés en dur, l'extracteur reçoit une CONFIG
`{champ: sélecteur CSS}`. Cela rend l'extracteur réparable : LLM-CODE corrige
la configuration (un dictionnaire de sélecteurs), jamais du code arbitraire —
ce qui préserve l'auditabilité et évite l'exécution de code généré.

Fonctions pures (HTML + config -> enregistrement), testables sur fixtures.
"""

from __future__ import annotations

from bs4 import BeautifulSoup

# Configuration calée sur la structure de la v1 du mock_shop.
V1_SELECTORS: dict[str, str] = {
    "title": "h1.listing-title",
    "price": ".listing-price",
    "seller": ".seller",
    "location": ".location",
    "description": ".listing-description",
}

REQUIRED: tuple[str, ...] = ("title", "price", "description")


def extract_with_selectors(html: str, selectors: dict[str, str]) -> dict:
    """Applique chaque sélecteur et renvoie {champ: texte ou None}."""
    soup = BeautifulSoup(html, "html.parser")
    record: dict[str, str | None] = {}
    for field, sel in selectors.items():
        node = soup.select_one(sel) if sel else None
        record[field] = node.get_text(strip=True) if node else None
    return record


def missing_fields(record: dict, required: tuple[str, ...] = REQUIRED) -> list[str]:
    """Champs requis absents ou vides (signal d'un extracteur cassé)."""
    return [f for f in required if not str(record.get(f) or "").strip()]