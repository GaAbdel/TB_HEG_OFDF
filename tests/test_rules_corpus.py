"""Tests du découpage du corpus de règles — sur le vrai fichier."""

from __future__ import annotations

from pathlib import Path

from osint.analyse.rules_corpus import parse_markdown_rules, rule_embedding_text

CORPUS = Path(__file__).parent.parent / "data" / "rules" / "regles_suisses_biens_restreints.md"
ENUM = {"tabac", "alcool", "cites", "viande", "contrefacon", "arme"}


def _rules() -> list[dict]:
    return parse_markdown_rules(CORPUS.read_text(encoding="utf-8"))


def test_nombre_de_regles():
    assert len(_rules()) == 18


def test_categories_conformes_a_l_enum():
    cats = {r["category"] for r in _rules()}
    assert cats <= ENUM, f"catégories hors enum : {cats - ENUM}"


def test_chaque_regle_a_les_champs():
    for r in _rules():
        assert r["title"] and r["text"]
        assert r["category"] in ENUM
        assert r["source"] and r["url"]


def test_distinction_ivoire_presente():
    titres = " ".join(r["title"].lower() for r in _rules())
    assert "mammouth" in titres        # piège : fossile, légal
    assert "tagua" in titres or "végétal" in titres  # piège : végétal, légal
    assert "éléphant" in titres        # réglementé


def test_texte_embedding_combine_titre_et_regle():
    r = {"title": "Titre", "text": "Énoncé."}
    assert rule_embedding_text(r) == "Titre. Énoncé."