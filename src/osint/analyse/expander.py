"""LLM-EXPAND — expansion de requête avant collecte.

Étend un terme ou une catégorie en une liste de termes de recherche associés
(synonymes, désignations familières, variantes, formulations implicites), afin
d'élargir la collecte au-delà du mot-clé initial. Passe unique : prompt -> JSON
{"termes": [...]}. Ces termes alimenteraient les requêtes du module de collecte.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from osint.analyse.scorer import _extract_json, load_prompt, prompt_hash
from osint.model.litellm_client import complete

if TYPE_CHECKING:
    from osint.config import Config


def _parse_terms(raw: str) -> list[str]:
    """Extrait la liste de termes, dédupliquée et normalisée (logique pure)."""
    data = _extract_json(raw)
    raw_terms = data.get("termes") or data.get("terms") or []
    out: list[str] = []
    seen: set[str] = set()
    for t in raw_terms:
        s = str(t).strip().lower()
        if s and s not in seen:
            seen.add(s)
            out.append(s)
    return out


_VALID_CATEGORIES = {"tabac", "alcool", "cites", "viande", "contrefacon", "arme"}


def _parse_categories(raw: str) -> list[str]:
    """Extrait les catégories cibles, filtrées sur l'enum valide (logique pure)."""
    data = _extract_json(raw)
    raw_cats = data.get("categories") or data.get("categorie") or []
    if isinstance(raw_cats, str):
        raw_cats = [raw_cats]
    out: list[str] = []
    for c in raw_cats:
        s = str(c).strip().lower()
        if s in _VALID_CATEGORIES and s not in out:
            out.append(s)
    return out


def expand_terms(cfg: "Config", seed: str, *, prompt_version: str = "expand_v1") -> dict:
    """Interprète une consigne d'enquêteur (mot-clé, catégorie ou phrase en
    langage naturel) et l'optimise en une liste de termes de recherche."""
    system_prompt = load_prompt(prompt_version)
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": f"Consigne de l'enquêteur : {seed}"},
    ]
    raw = complete(cfg, agent="LLM-EXPAND", messages=messages,temperature=0.3, max_tokens=300, json_mode=True,)
    return {
        "seed": seed,
        "terms": _parse_terms(raw),
        "categories": _parse_categories(raw),
        "prompt_version": prompt_version,
        "prompt_hash": prompt_hash(system_prompt),
        "model": cfg.resolve_model("LLM-EXPAND").model,
    }