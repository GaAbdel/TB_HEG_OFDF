"""LLM-CODE — réparation autonome d'un extracteur cassé.

Quand la structure d'un site évolue, l'extracteur déterministe (piloté par une
config de sélecteurs CSS) renvoie des champs vides. LLM-CODE est un agent en
boucle perception-action :

    extraire -> détecter les champs manquants -> proposer de nouveaux sélecteurs
    -> appliquer -> ré-extraire -> recommencer (borné par max_iters).

Point d'architecture : l'agent répare une CONFIGURATION (dictionnaire de
sélecteurs), pas du code exécutable. Aucune exécution de code généré : la
surface de risque LLM06 (Excessive Agency) reste fermée, et chaque réparation
est un diff de sélecteurs auditable.

La fonction `repair_selectors` est pure quant au LLM : celui-ci est injecté
(`llm_fn`), ce qui rend la boucle testable sans appel modèle. `make_llm_repair_fn`
fournit l'implémentation réelle (via le service de modèle).
"""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import TYPE_CHECKING

from osint.analyse.scorer import _extract_json, load_prompt, prompt_hash
from osint.collecte.selector_extractor import (
    REQUIRED,
    extract_with_selectors,
    missing_fields,
)
from osint.model.litellm_client import complete

if TYPE_CHECKING:
    from osint.config import Config

# llm_fn(html, current_selectors, missing) -> {champ: nouveau_sélecteur}
RepairFn = Callable[[str, dict, list], dict]


def repair_selectors(
    llm_fn: RepairFn,
    html: str,
    current_selectors: dict[str, str],
    *,
    required: tuple[str, ...] = REQUIRED,
    max_iters: int = 3,
) -> dict:
    """Répare une config de sélecteurs jusqu'à extraire tous les champs requis.

    Renvoie {ok, selectors, record, iterations, missing, history}. Dégradation
    gracieuse : si le LLM ne propose plus rien d'utile, on s'arrête en renvoyant
    le meilleur état atteint (ok=False).
    """
    selectors = dict(current_selectors)
    history: list[dict] = []

    for i in range(max_iters + 1):
        record = extract_with_selectors(html, selectors)
        missing = missing_fields(record, required)
        history.append({"iteration": i, "missing": list(missing), "selectors": dict(selectors)})

        if not missing:
            return {"ok": True, "selectors": selectors, "record": record,
                    "iterations": i, "missing": [], "history": history}
        if i == max_iters:
            break

        proposed = llm_fn(html, selectors, missing) or {}
        # On n'applique que des propositions non vides, et on ignore le reste.
        useful = {k: v for k, v in proposed.items() if isinstance(v, str) and v.strip()}
        if not useful:
            break
        selectors.update(useful)

    record = extract_with_selectors(html, selectors)
    missing = missing_fields(record, required)
    return {"ok": not missing, "selectors": selectors, "record": record,
            "iterations": len(history) - 1, "missing": missing, "history": history}


def make_llm_repair_fn(cfg: "Config", *, prompt_version: str = "code_v1") -> RepairFn:
    """Construit la fonction de réparation réelle (appel au service de modèle).

    Le garde-fou LPD (consentement cloud) est de la responsabilité de l'appelant.
    """
    system_prompt = load_prompt(prompt_version)

    def llm_fn(html: str, current_selectors: dict, missing: list) -> dict:
        user = (
            "HTML de la page :\n" + html[:6000] + "\n\n"
            "Sélecteurs actuels (JSON) :\n" + json.dumps(current_selectors, ensure_ascii=False)
            + "\n\nChamps à réparer : " + ", ".join(missing)
        )
        raw = complete(
            cfg, agent="LLM-CODE",
            messages=[{"role": "system", "content": system_prompt},
                      {"role": "user", "content": user}],
            temperature=0.0, max_tokens=300,
        )
        proposed = _extract_json(raw)
        return proposed if isinstance(proposed, dict) else {}

    llm_fn.prompt_hash = prompt_hash(system_prompt)  # type: ignore[attr-defined]
    return llm_fn