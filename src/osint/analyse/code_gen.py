"""Génération d'un extracteur de CODE corrigé (verrou OFDF, jamais exécuté).

Ossature minimale : LLM-CODE lit le source de l'extracteur cassé + un échantillon
du nouveau HTML, et propose une version corrigée. Le résultat est ÉCRIT dans un
dossier de propositions — JAMAIS importé ni exécuté par l'application. Un
développeur le relit et l'installe manuellement. Activation gouvernée par le
verrou `code_repair.enabled` (config).

Volontairement trivial (pas de git, pas de sandbox, pas d'installation
automatique) : l'OFDF fera évoluer ces mécanismes. Les instances tournant sur
VM jetables, le risque d'une proposition erronée reste borné.
"""

from __future__ import annotations

import inspect
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING

from osint.analyse.scorer import load_prompt
from osint.model.litellm_client import complete

if TYPE_CHECKING:
    from osint.config import Config

_BANNER = (
    "# ---------------------------------------------------------------------------\n"
    "# PROPOSITION AUTOMATIQUE (LLM-CODE) — NON INSTALLÉE, NON EXÉCUTÉE.\n"
    "# Générée le {when} pour la plateforme '{platform}'.\n"
    "# À RELIRE par un développeur, puis à installer MANUELLEMENT dans\n"
    "# src/osint/collecte/ et à enregistrer dans EXTRACTORS (pipeline.py).\n"
    "# Ne jamais exécuter sans relecture.\n"
    "# ---------------------------------------------------------------------------\n"
)


def _current_source(platform: str) -> tuple[str, str]:
    """Renvoie (chemin, source) de l'extracteur de CODE d'une plateforme."""
    from osint.orchestration.pipeline import EXTRACTORS
    cls = EXTRACTORS.get(platform)
    if cls is None:
        raise ValueError(
            f"'{platform}' n'a pas d'extracteur de code (chemin B). "
            f"La réparation de code ne concerne que les extracteurs .py."
        )
    path = inspect.getsourcefile(cls) or "?"
    return path, inspect.getsource(cls)


def _strip_fences(text: str) -> str:
    """Retire d'éventuelles balises Markdown ```python ... ```."""
    t = text.strip()
    if t.startswith("```"):
        lines = t.split("\n")[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        t = "\n".join(lines)
    return t.strip() + "\n"


def propose_extractor_code(cfg: "Config", platform: str, sample_html: str,
                           *, prompt_version: str = "codegen_v1") -> dict:
    """Génère un extracteur corrigé et l'ÉCRIT dans le dossier de propositions.

    Si `code_repair.validate` est vrai, une BOUCLE générer → vérification isolée →
    renvoyer l'erreur → régénérer s'exécute jusqu'à `code_repair.max_iters` ou
    succès. La vérification s'assure que le code se charge et respecte l'interface
    (pas la correction de l'extraction). Le fichier produit n'est jamais importé
    par l'application ; l'appelant doit avoir vérifié le verrou.
    """
    src_path, current_source = _current_source(platform)
    system_prompt = load_prompt(prompt_version)
    validate = cfg.code_repair_validate()
    max_iters = cfg.code_repair_max_iters() if validate else 0

    history: list[dict] = []
    code = ""
    check: dict = {"ok": True, "skipped": True}
    feedback = ""

    for i in range(max_iters + 1):
        user = (
            "Code source actuel de l'extracteur (cassé) :\n\n" + current_source
            + "\n\n---\n\nNouveau HTML de la page qui casse l'extraction :\n\n"
            + (sample_html or "")[:8000]
            + (("\n\n---\n\nLa tentative précédente a échoué : " + feedback
                + "\nCorrige ces erreurs.") if feedback else "")
        )
        raw = complete(
            cfg, agent="LLM-CODE",
            messages=[{"role": "system", "content": system_prompt},
                      {"role": "user", "content": user}],
            temperature=0.0, max_tokens=2000,
        )
        code = _strip_fences(raw)

        if validate:
            from osint.analyse.code_sandbox import check_candidate
            check = check_candidate(code)
            history.append({"iteration": i, "ok": check.get("ok"),
                            "stage": check.get("stage"), "error": check.get("error")})
            if check.get("ok") or i == max_iters:
                break
            feedback = f"[{check.get('stage')}] {check.get('error')}"
        else:
            break

    when = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    statut = ("validé (charge + interface) en %d tentative(s)" % (len(history))
              if check.get("ok") and not check.get("skipped")
              else ("NON validé — dernière erreur : %s" % check.get("error"))
              if not check.get("ok")
              else "non testé (vérification désactivée)")
    header = _BANNER.format(when=when, platform=platform) + f"# Vérification : {statut}\n"
    content = header + "\n" + code
    out_dir = Path(cfg.code_repair_proposals_dir())
    out_dir.mkdir(parents=True, exist_ok=True)
    filename = f"{platform}_{when}.py"
    (out_dir / filename).write_text(content, encoding="utf-8")

    return {"filename": filename, "path": str(out_dir / filename),
            "source_path": src_path, "content": content,
            "ok": bool(check.get("ok")), "validated": not check.get("skipped", False),
            "iterations": len(history), "history": history}


def list_proposals(cfg: "Config") -> list[dict]:
    """Liste les propositions déposées (nom, date de modification, contenu)."""
    d = Path(cfg.code_repair_proposals_dir())
    if not d.exists():
        return []
    out = []
    for p in sorted(d.glob("*.py"), reverse=True):
        out.append({
            "filename": p.name,
            "modified": datetime.fromtimestamp(p.stat().st_mtime, timezone.utc).isoformat(),
            "content": p.read_text(encoding="utf-8"),
        })
    return out


def discard_proposal(cfg: "Config", filename: str) -> bool:
    """Supprime une proposition. Refuse tout nom contenant un séparateur/.. ."""
    if "/" in filename or "\\" in filename or ".." in filename:
        return False
    p = Path(cfg.code_repair_proposals_dir()) / filename
    if p.exists() and p.suffix == ".py":
        p.unlink()
        return True
    return False