"""Tests du parsing de LLM-SCORE — logique pure, sans appel modèle."""

from __future__ import annotations

import pytest

from osint.analyse.scorer import _normalize_category, parse_score


def test_json_simple():
    raw = '{"score": 0.82, "categorie": "tabac", "justification": "non taxé"}'
    r = parse_score(raw)
    assert r["suspicion_score"] == 0.82
    assert r["category"] == "tabac"
    assert r["rationale"] == "non taxé"


def test_json_avec_balises_markdown():
    raw = '```json\n{"score": 0.1, "categorie": "aucune", "justification": "ok"}\n```'
    assert parse_score(raw)["category"] == "aucune"


def test_json_entoure_de_texte():
    raw = 'Voici mon analyse : {"score": 0.7, "categorie": "arme", "justification": "x"} fin.'
    assert parse_score(raw)["category"] == "arme"


def test_categorie_avec_accent_normalisee():
    # "contrefaçon" (cédille) doit devenir "contrefacon" (valeur de l'enum)
    assert _normalize_category("Contrefaçon") == "contrefacon"


def test_categorie_inconnue_devient_aucune():
    assert _normalize_category("arnaque") == "aucune"


def test_score_borne_dans_intervalle():
    assert parse_score('{"score": 1.7, "categorie": "alcool", "justification": ""}')["suspicion_score"] == 1.0
    assert parse_score('{"score": -0.5, "categorie": "aucune", "justification": ""}')["suspicion_score"] == 0.0


def test_reponse_non_json_leve():
    with pytest.raises(ValueError):
        parse_score("désolé, je ne peux pas répondre")