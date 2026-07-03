"""Tests de LLM-PARSE parsing et validation, sans appel modèle."""

from __future__ import annotations

from osint.analyse.parser_llm import _strip_html, parse_output, validate_record

_JSON = ('{"title": "Vélo de course", "price_amount": 450, "price_currency": "chf", '
         '"description": "Bon état", "location": "Genève", "seller": "marc"}')


def test_parse_output_normalise_devise():
    rec = parse_output(_JSON)
    assert rec["title"] == "Vélo de course"
    assert rec["price_amount"] == 450
    assert rec["price_currency"] == "CHF"          # mis en majuscules


def test_parse_output_prix_en_chaine_converti():
    rec = parse_output('{"title": "X", "price_amount": "1\'200.-", "price_currency": "CHF"}')
    assert rec["price_amount"] == 1200.0


def test_parse_output_balises_markdown():
    rec = parse_output('```json\n{"title": "Y", "price_amount": null}\n```')
    assert rec["title"] == "Y" and rec["price_amount"] is None


def test_validate_ok():
    ok, problems = validate_record(parse_output(_JSON))
    assert ok and problems == []


def test_validate_titre_manquant():
    ok, problems = validate_record({"title": "  ", "price_amount": None})
    assert not ok and "title" in problems


def test_validate_prix_non_numerique():
    ok, problems = validate_record({"title": "X", "price_amount": "cher"})
    assert not ok and "price_amount" in problems


def test_strip_html_enleve_scripts_et_balises():
    html = "<html><style>x{}</style><h1>Titre</h1><script>alert(1)</script><p>Texte</p></html>"
    out = _strip_html(html)
    assert "Titre" in out and "Texte" in out
    assert "alert" not in out and "<" not in out