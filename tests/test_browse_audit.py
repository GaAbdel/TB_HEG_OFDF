"""Tests du journal d'audit LLM-BROWSE fichier JSONL scellé.

Vérifie : construction des entrées, intégrité de la chaîne, round-trip
fichier, et surtout la DÉTECTION de falsification (le cœur de l'auditabilité).
"""

from __future__ import annotations

import json

from osint.analyse.browse_audit import (
    append_browse_log,
    build_browse_entries,
    read_browse_log,
    seal_entries,
    verify_browse_log,
    write_browse_log,
)

_RESULT = {
    "result": "5 annonces collectées",
    "start_url": "http://mock_shop:8000/v2",
    "allowed_domains": ["mock_shop", "http*://mock_shop/*"],
    "max_steps": 18,
    "model": "claude-haiku-4-5-20251001",
    "prompt_version": "browse_v1",
    "prompt_hash": "abc123",
    "trace": {
        "urls": ["http://mock_shop:8000/v2", "http://mock_shop:8000/v2/listing/1"],
        "actions": ["navigate", "click"],
        "thoughts": [
            {"eval": "ok", "memory": "page chargée", "next_goal": "ouvrir l'annonce 1"},
            {"eval": "ok", "memory": "sur l'annonce 1", "next_goal": "révéler le numéro"},
        ],
    },
}


def test_entrees_start_pas_done():
    entries = build_browse_entries(_RESULT)
    actions = [e["action"] for e in entries]
    assert actions == ["browse_start", "navigate", "click", "browse_done"]
    assert entries[0]["detail"]["allowed_domains"] == ["mock_shop", "http*://mock_shop/*"]
    assert entries[-1]["detail"]["steps"] == 2


def test_chaine_scellee_intacte():
    sealed = seal_entries(build_browse_entries(_RESULT))
    # chaînage : chaque prev_hash = entry_hash précédent
    assert sealed[0]["prev_hash"] is None
    for a, b in zip(sealed, sealed[1:]):
        assert b["prev_hash"] == a["entry_hash"]


def test_ecriture_lecture_et_verification(tmp_path):
    path = tmp_path / "browse.jsonl"
    write_browse_log(_RESULT, path)
    entries = read_browse_log(path)
    assert len(entries) == 4
    ok, idx = verify_browse_log(path)
    assert ok is True and idx is None


def test_raisonnement_capture_dans_le_detail():
    entries = build_browse_entries(_RESULT)
    step = entries[1]                          # 1er pas (navigate)
    assert step["detail"]["reasoning"]["next_goal"] == "ouvrir l'annonce 1"


def test_ajout_continu_prolonge_la_chaine(tmp_path):
    path = tmp_path / "browse.jsonl"
    append_browse_log(_RESULT, path)           # session 1
    append_browse_log(_RESULT, path)           # session 2

    entries = read_browse_log(path)
    assert len(entries) == 8                    # 2 sessions × 4 entrées
    # la 1re entrée de la session 2 scelle la dernière de la session 1
    assert entries[4]["prev_hash"] == entries[3]["entry_hash"]
    ok, idx = verify_browse_log(path)
    assert ok is True and idx is None           # une seule chaîne, intacte


def test_falsification_detectee_sur_journal_multisession(tmp_path):
    path = tmp_path / "browse.jsonl"
    append_browse_log(_RESULT, path)
    append_browse_log(_RESULT, path)

    lines = path.read_text(encoding="utf-8").splitlines()
    forged = json.loads(lines[5])              # une entrée de la session 2
    forged["detail"]["url"] = "http://site-pirate.example"
    lines[5] = json.dumps(forged, ensure_ascii=False)
    path.write_text("\n".join(lines), encoding="utf-8")

    ok, idx = verify_browse_log(path)
    assert ok is False and idx == 5