"""LLM-SCORE — notation de suspicion d'une annonce.

Charge un prompt VERSIONNÉ (prompts/score_vN.txt), construit les messages,
appelle le modèle via la couche LiteLLM, puis interprète la réponse JSON.

Le RAG est optionnel : si des règles douanières sont fournies (paramètre
`rules`), elles sont injectées dans le message pour ancrer le jugement ; sinon
le scoring repose sur le seul prompt et les connaissances du modèle.
"""

from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from pathlib import Path
from typing import TYPE_CHECKING

from osint.model.litellm_client import complete

if TYPE_CHECKING:
    from osint.config import Config

# Dossier des prompts : montés en lecture seule dans le conteneur (/app/prompts).
PROMPTS_DIR = Path(__file__).resolve().parents[3] / "prompts"

# Catégories autorisées = enum risk_category en base.
ALLOWED_CATEGORIES = {"tabac", "alcool", "cites", "viande", "contrefacon", "arme", "autre", "aucune"}


def load_prompt(version: str = "score_v1") -> str:
    """Lit le fichier de prompt versionné."""
    path = PROMPTS_DIR / f"{version}.txt"
    return path.read_text(encoding="utf-8")


def prompt_hash(text: str) -> str:
    """Empreinte du prompt (pour tracer quelle version a produit quel score)."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _format_annonce(listing: dict) -> str:
    parts = [f"Titre : {listing.get('title') or ''}",
             f"Description : {listing.get('description') or ''}"]
    if listing.get("price_amount") is not None:
        parts.append(f"Prix : {listing['price_amount']} {listing.get('price_currency') or ''}".strip())
    if listing.get("location"):
        parts.append(f"Lieu : {listing['location']}")
    return "\n".join(parts)


def _normalize_category(raw: str) -> str:
    """Minuscule + sans accents ; toute valeur hors liste -> 'aucune'."""
    cleaned = unicodedata.normalize("NFKD", raw or "").encode("ascii", "ignore").decode()
    cleaned = cleaned.lower().strip()
    return cleaned if cleaned in ALLOWED_CATEGORIES else "aucune"


def _extract_json(raw: str) -> dict:
    """Récupère l'objet JSON, même si le modèle l'enrobe de texte/balises."""
    text = raw.strip()
    # Retire d'éventuelles clôtures Markdown ```json ... ```
    text = re.sub(r"^```(?:json)?|```$", "", text, flags=re.MULTILINE).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        # repli : isole le premier bloc { ... }
        match = re.search(r"\{.*\}", text, flags=re.DOTALL)
        if not match:
            raise ValueError(f"réponse non-JSON du modèle : {raw[:200]!r}")
        return json.loads(match.group(0))


def parse_score(raw: str) -> dict:
    """Transforme la réponse brute du modèle en {suspicion_score, category, rationale}."""
    data = _extract_json(raw)
    score = float(data.get("score", 0.0))
    score = max(0.0, min(1.0, score))            # borne dans [0, 1]
    return {
        "suspicion_score": round(score, 3),
        "category": _normalize_category(str(data.get("categorie", "aucune"))),
        "rationale": str(data.get("justification", "")).strip(),
    }


def _format_rules(rules: list[dict] | None) -> str:
    """Met en forme les règles récupérées pour les injecter dans le prompt."""
    if not rules:
        return ""
    lines = ["", "Règles douanières potentiellement applicables "
             "(appuie-toi dessus si elles sont pertinentes) :"]
    for r in rules:
        lines.append(f"- [{r.get('category')}] {r.get('title')} "
                     f"({r.get('source')}) : {r.get('text')}")
    return "\n".join(lines)


def score_listing(
    cfg: "Config",
    listing: dict,
    *,
    prompt_version: str = "score_v1",
    rules: list[dict] | None = None,
) -> dict:
    """Note une annonce. Renvoie le score + la traçabilité (version/hash/modèle).

    Si `rules` est fourni (récupérées par le RAG), elles sont injectées dans le
    message : le jugement s'ancre alors sur des règles concrètes. Sans `rules`,
    c'est le scoring « nu ».

    Le franchissement du garde-fou LPD (consentement cloud) est de la
    responsabilité de l'appelant, AVANT d'appeler cette fonction.
    """
    system_prompt = load_prompt(prompt_version)
    user_content = _format_annonce(listing) + _format_rules(rules)
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_content},
    ]
    raw = complete(cfg, agent="LLM-SCORE", messages=messages, temperature=0.0, max_tokens=400, json_mode=True,)
    result = parse_score(raw)
    result.update(
        prompt_version=prompt_version,
        prompt_hash=prompt_hash(system_prompt),
        model=cfg.resolve_model("LLM-SCORE").model,
        rag_used=bool(rules),
        rag_refs=[r.get("title") for r in (rules or [])],
    )
    return result
