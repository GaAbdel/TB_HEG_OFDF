"""Tests de la chaîne de traçabilité.

Ces tests prouvent que la logique de hachage
détecte toute altération, suppression, insertion ou réordonnancement.
"""

from __future__ import annotations

from osint.persistance.audit import compute_entry_hash, seal, verify_chain


def build_chain(events: list[dict]) -> list[dict]:
    """Construit une chaîne scellée à partir d'une liste d'événements."""
    chain: list[dict] = []
    prev = None
    for ev in events:
        e = seal(prev, ev)
        chain.append(e)
        prev = e["entry_hash"]
    return chain


THREE = [
    {"actor": "system", "action": "run_start", "run_id": 1},
    {"actor": "LLM-PARSE", "action": "parse", "run_id": 1, "listing_id": 10},
    {"actor": "LLM-SCORE", "action": "score", "run_id": 1, "listing_id": 10},
]


# --- Propriétés du hash ------------------------------------------------------
def test_hash_deterministe():
    p = {"actor": "system", "action": "run_start"}
    assert compute_entry_hash(None, p) == compute_entry_hash(None, p)


def test_hash_depend_du_contenu():
    assert compute_entry_hash(None, {"action": "a"}) != compute_entry_hash(None, {"action": "b"})


def test_hash_depend_du_prev():
    p = {"action": "score"}
    assert compute_entry_hash("aaa", p) != compute_entry_hash("bbb", p)


def test_ordre_des_cles_sans_effet():
    assert compute_entry_hash(None, {"a": 1, "b": 2}) == compute_entry_hash(None, {"b": 2, "a": 1})


# --- Vérification de chaîne --------------------------------------------------
def test_chaine_valide():
    assert verify_chain(build_chain(THREE)) == (True, None)


def test_detecte_alteration_contenu():
    chain = build_chain(THREE)
    chain[1]["action"] = "falsifie"          # on change le contenu sans recalculer le hash
    ok, idx = verify_chain(chain)
    assert ok is False and idx == 1


def test_detecte_alteration_hash():
    chain = build_chain(THREE)
    chain[1]["entry_hash"] = "deadbeef"      # on falsifie directement le hash
    ok, idx = verify_chain(chain)
    assert ok is False and idx == 1


def test_detecte_suppression():
    chain = build_chain(THREE)
    del chain[1]                             # on retire une entrée
    ok, idx = verify_chain(chain)
    assert ok is False and idx == 1


def test_detecte_reordonnancement():
    chain = build_chain(THREE)
    chain[1], chain[2] = chain[2], chain[1]  # on permute deux entrées
    ok, idx = verify_chain(chain)
    assert ok is False and idx == 1


def test_chaine_vide_est_valide():
    assert verify_chain([]) == (True, None)