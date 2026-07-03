"""Journalisation auditable des sessions LLM-BROWSE fichier JSONL scellé.

La trace d'une exploration Mode B est écrite dans un fichier JSONL, chaque ligne
étant une entrée d'audit SCELLÉE par la même chaîne de hash que le journal
central (osint.persistance.audit) : entry_hash = SHA-256(prev_hash + contenu).
Toute altération d'une ligne casse la chaîne en aval et devient détectable.

On réutilise la logique de scellement (pure) de audit.py — donc aucune base de
données n'est touchée, et le tout est testable hors conteneur.
"""


from __future__ import annotations
 
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
 
from osint.persistance.audit import seal, verify_chain
 
ACTOR = "LLM-BROWSE"
 
 
def build_browse_entries(result: dict, *, started_at: datetime | None = None) -> list[dict]:
    """Construit la séquence d'entrées (non scellées) d'une session BROWSE.
 
    Une entrée d'ouverture (paramètres + périmètre borné), une entrée par pas
    (action + URL), une entrée de clôture. Les champs correspondent à ceux
    scellés par la chaîne d'audit centrale.
    """
    ts = (started_at or datetime.now(timezone.utc)).isoformat()
    entries: list[dict] = []
 
    def add(action: str, detail: dict[str, Any]) -> None:
        entries.append({
            "run_id": None, "listing_id": None, "actor": ACTOR,
            "action": action, "detail": detail, "created_at": ts,
        })
 
    add("browse_start", {
        "start_url": result.get("start_url"),
        "allowed_domains": result.get("allowed_domains"),
        "max_steps": result.get("max_steps"),
        "model": result.get("model"),
        "prompt_version": result.get("prompt_version"),
        "prompt_hash": result.get("prompt_hash"),
    })
 
    trace = result.get("trace") or {}
    urls = trace.get("urls") or []
    actions = trace.get("actions") or []
    thoughts = trace.get("thoughts") or []
    for i, action in enumerate(actions):
        detail: dict[str, Any] = {"step": i + 1, "url": urls[i] if i < len(urls) else None}
        if i < len(thoughts) and thoughts[i]:
            # Raisonnement DÉCLARÉ par l'agent (explicabilité indicative, non une
            # preuve du calcul interne du modèle). Aligné au mieux par index.
            detail["reasoning"] = thoughts[i]
        add(action, detail)
 
    add("browse_done", {
        "steps": len(actions),
        "result_chars": len(result.get("result") or ""),
    })
    return entries
 
 
def seal_entries(entries: list[dict]) -> list[dict]:
    """Scelle une séquence d'entrées en chaîne (comme l'audit central)."""
    sealed: list[dict] = []
    prev: str | None = None
    for e in entries:
        s = seal(prev, e)
        sealed.append(s)
        prev = s["entry_hash"]
    return sealed
 
 
def write_browse_log(result: dict, path: str | Path, *, started_at: datetime | None = None) -> Path:
    """Écrit (en ÉCRASANT) la trace scellée d'une session BROWSE en JSONL."""
    sealed = seal_entries(build_browse_entries(result, started_at=started_at))
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for s in sealed:
            f.write(json.dumps(s, ensure_ascii=False) + "\n")
    return path
 
 
def append_browse_log(result: dict, path: str | Path, *, started_at: datetime | None = None) -> Path:
    """Ajoute une session au journal UNIQUE en prolongeant la chaîne de hash.
 
    Un seul fichier accumule l'historique de toutes les sessions : la première
    entrée d'une nouvelle session scelle la dernière de la précédente, si bien
    que tout le journal forme une seule chaîne inviolable.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
 
    prev: str | None = None
    if path.exists():
        existing = read_browse_log(path)
        if existing:
            prev = existing[-1]["entry_hash"]
 
    entries = build_browse_entries(result, started_at=started_at)
    with path.open("a", encoding="utf-8") as f:
        for e in entries:
            s = seal(prev, e)
            f.write(json.dumps(s, ensure_ascii=False) + "\n")
            prev = s["entry_hash"]
    return path
 
 
def read_browse_log(path: str | Path) -> list[dict]:
    """Relit un journal JSONL en liste d'entrées."""
    lines = Path(path).read_text(encoding="utf-8").splitlines()
    return [json.loads(line) for line in lines if line.strip()]
 
 
def verify_browse_log(path: str | Path) -> tuple[bool, int | None]:
    """Vérifie l'intégrité d'un journal BROWSE. (True, None) si intact, sinon
    (False, index) à la première anomalie."""
    return verify_chain(read_browse_log(path))