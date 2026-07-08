"""LLM-PARSE — extraction structurée d'une annonce de site inconnu.

Quand un site n'a pas d'extracteur déterministe (structure inconnue), LLM-PARSE
lit le contenu brut (texte ou HTML) et en isole les champs par le sens. Passe
unique : prompt -> JSON structuré, puis validation de schéma avant tout usage
en aval (surface de risque LLM05 — Improper Output Handling).
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from osint.analyse.scorer import _extract_json, load_prompt, prompt_hash
from osint.model.litellm_client import complete

if TYPE_CHECKING:
    from osint.config import Config

REQUIRED_FIELDS = ("title", "price_amount", "price_currency", "description", "location", "seller")
_TAG_RE = re.compile(r"<[^>]+>")


def _strip_html(raw: str, *, max_chars: int = 6000) -> str:
    """Réduit le HTML à du texte lisible et borné (limite les tokens)."""
    text = re.sub(r"(?is)<(script|style)[^>]*>.*?</\1>", " ", raw)
    text = _TAG_RE.sub(" ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text[:max_chars]


def validate_record(rec: dict) -> tuple[bool, list[str]]:
    """Valide la sortie de LLM-PARSE contre le schéma attendu.

    Renvoie (ok, champs_problématiques). `title` est obligatoire et non vide ;
    price_amount doit être un nombre ou None.
    """
    problems: list[str] = []
    if not str(rec.get("title") or "").strip():
        problems.append("title")
    amount = rec.get("price_amount")
    if amount is not None and not isinstance(amount, (int, float)):
        problems.append("price_amount")
    return (not problems), problems


def parse_output(raw: str) -> dict:
    """Transforme la réponse brute en enregistrement normalisé (logique pure)."""
    data = _extract_json(raw)
    rec: dict = {}
    for f in REQUIRED_FIELDS:
        rec[f] = data.get(f)
    # Normalisation prix
    amt = rec.get("price_amount")
    if isinstance(amt, str):
        digits = re.sub(r"[^\d.]", "", amt.replace(",", "."))
        rec["price_amount"] = float(digits) if digits else None
    cur = rec.get("price_currency")
    rec["price_currency"] = cur.upper() if isinstance(cur, str) and cur else None
    return rec


def parse_listing_llm(cfg: "Config", content: str, *, prompt_version: str = "parse_v1") -> dict:
    """Extrait les champs d'une annonce inconnue. Renvoie record + traçabilité.

    Le garde-fou LPD (consentement cloud) est de la responsabilité de l'appelant.
    """
    system_prompt = load_prompt(prompt_version)
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": _strip_html(content)},
    ]
    raw = complete(cfg, agent="LLM-PARSE", messages=messages, temperature=0.0, max_tokens=500,  json_mode=True,)
    rec = parse_output(raw)
    ok, problems = validate_record(rec)
    rec.update(
        parse_ok=ok,
        parse_problems=problems,
        prompt_version=prompt_version,
        prompt_hash=prompt_hash(system_prompt),
        model=cfg.resolve_model("LLM-PARSE").model,
    )
    return rec