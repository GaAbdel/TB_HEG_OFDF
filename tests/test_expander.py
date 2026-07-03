"""Tests du parsing de LLM-EXPAND (4.3) — logique pure, sans appel modèle."""

from __future__ import annotations

from osint.analyse.expander import _parse_terms


def test_liste_simple():
    assert _parse_terms('{"termes": ["clopes", "cartouches"]}') == ["clopes", "cartouches"]


def test_balises_markdown():
    assert _parse_terms('```json\n{"termes": ["ivoire"]}\n```') == ["ivoire"]


def test_cle_anglaise_acceptee():
    assert _parse_terms('{"terms": ["whisky"]}') == ["whisky"]


def test_deduplication_et_minuscule():
    assert _parse_terms('{"termes": ["Clopes", "clopes", " CLOPES "]}') == ["clopes"]


def test_liste_vide():
    assert _parse_terms('{"termes": []}') == []


def test_consigne_langage_naturel(monkeypatch):
    """EXPAND interprète une phrase d'enquêteur et renvoie des termes (modèle simulé)."""
    import osint.analyse.expander as exp

    captured = {}

    def fake_complete(cfg, *, agent, messages, **kw):
        captured["user"] = messages[-1]["content"]
        return '{"termes": ["puff", "cigarette électronique jetable", "vape"]}'

    monkeypatch.setattr(exp, "complete", fake_complete)

    class _Cfg:
        def resolve_model(self, agent):
            class M: model = "qwen3:8b"
            return M()

    out = exp.expand_terms(_Cfg(), "cherche des puffs jetables car la nouvelle loi les interdit")
    # la consigne libre est bien transmise au modèle…
    assert "puffs jetables" in captured["user"]
    assert "Consigne de l'enquêteur" in captured["user"]
    # …et ressort optimisée en termes de recherche
    assert "puff" in out["terms"] and "vape" in out["terms"]