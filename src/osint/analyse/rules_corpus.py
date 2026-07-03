"""Découpage du corpus de règles douanières.

Le corpus de règles est un Markdown structuré : chaque règle est un bloc `###`
portant des champs (Catégorie, Source, URL, Règle). Le découpage « par
structure » produit UN chunk par règle — une unité de sens autonome, idéale
pour la recherche sémantique.

La fonction prend uniquement du texte Markdown en entrée et retourne une liste de règles, 
sans appeler Qdrant, sans calculer d’embeddings, sans lire de fichier, sans dépendre d’un service externe.
"""

from __future__ import annotations

import re

# Reconnaît une ligne de champ : « - **Nom** : valeur »
_FIELD_RE = re.compile(r"^-\s*\*\*(.+?)\*\*\s*:\s*(.*)$")


def _norm_key(key: str) -> str:
    import unicodedata

    cleaned = unicodedata.normalize("NFKD", key).encode("ascii", "ignore").decode()
    return cleaned.lower().strip()


def parse_markdown_rules(markdown: str) -> list[dict]:
    """Découpe le Markdown en règles : [{title, category, source, url, text}, ...]."""
    rules: list[dict] = []
    current: dict | None = None

    def flush() -> None:
        if current and current.get("text"):
            rules.append(current)

    for line in markdown.splitlines():
        if line.startswith("### "):
            flush()
            current = {"title": line[4:].strip(), "category": None,
                       "source": None, "url": None, "text": None}
            continue
        if current is None:
            continue
        m = _FIELD_RE.match(line.strip())
        if not m:
            continue
        key, value = _norm_key(m.group(1)), m.group(2).strip()
        if key.startswith("categ"):
            current["category"] = value
        elif key == "source":
            current["source"] = value
        elif key == "url":
            current["url"] = value
        elif key.startswith("regl"):
            current["text"] = value

    flush()
    return rules


def rule_embedding_text(rule: dict) -> str:
    """Texte à vectoriser pour une règle : titre + énoncé (le sens de la règle)."""
    return f"{rule.get('title', '')}. {rule.get('text', '')}".strip()