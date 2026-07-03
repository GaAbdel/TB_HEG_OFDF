"""Tests de LLM-BROWSE (Mode B) — parties testables hors navigateur.

On teste : la consigne métier, le périmètre borné, la tolérance aux kwargs, et
le défi de pagination du mock_shop. L'exploration réelle (Browser-Use) se lance
via scripts/browse_demo.py.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

from fastapi.testclient import TestClient

from osint.analyse.browse import (
    _construct,
    build_browse_task,
    resolve_allowed_domains,
)

ROOT = Path(__file__).parent.parent
_spec = importlib.util.spec_from_file_location("mock_shop_app", ROOT / "mock_shop" / "app.py")
shop = importlib.util.module_from_spec(_spec)
sys.modules["mock_shop_app"] = shop
_spec.loader.exec_module(shop)
CLIENT = TestClient(shop.app)


# --- Consigne métier --------------------------------------------------------
def test_task_contient_url_et_contraintes():
    task = build_browse_task("http://mock_shop:8000/v2")
    assert "http://mock_shop:8000/v2" in task
    assert "télécharge" in task.lower()        # interdiction de téléchargement
    assert "site de départ" in task.lower()    # périmètre


# --- Périmètre borné (§283) -------------------------------------------------
def test_perimetre_extrait_le_domaine():
    domains = resolve_allowed_domains("http://mock_shop:8000/v2")
    assert "mock_shop" in domains
    assert any("mock_shop" in d and "http" in d for d in domains)


def test_perimetre_accepte_des_ajouts():
    domains = resolve_allowed_domains("http://mock_shop:8000/v2", extra=["cdn.example.com"])
    assert "cdn.example.com" in domains


# --- Tolérance aux kwargs non supportés -------------------------------------
def test_construct_retire_kwarg_inconnu():
    class Strict:
        def __init__(self, a):  # n'accepte QUE `a`
            self.a = a
    obj = _construct(Strict, a=1, use_thinking=False, controller="x")
    assert obj.a == 1                          # construit malgré les kwargs en trop


# --- Défi de pagination (mock_shop v2) --------------------------------------
def test_pagination_page1():
    html = CLIENT.get("/v2?page=1").text
    assert "Suivant" in html
    assert "Précédent" not in html
    assert "Page 1 / 2" in html


def test_pagination_page2():
    html = CLIENT.get("/v2?page=2").text
    assert "Précédent" in html
    assert "Suivant" not in html


def test_pagination_couvre_toutes_les_annonces():
    titres = CLIENT.get("/v2?page=1").text + CLIENT.get("/v2?page=2").text
    assert "Montre automatique" in titres
    assert "Vélo de course" in titres          # dernière annonce, page 2


def test_construct_isole_le_profil_ou_avertit(capsys):
    """L'isolation du profil est appliquée si supportée, sinon signalée."""
    from osint.analyse.browse import _construct

    # Version qui accepte user_data_dir : l'isolation est appliquée.
    class SessionAvecProfil:
        def __init__(self, allowed_domains=None, headless=True, user_data_dir=None):
            self.user_data_dir = user_data_dir

    s = _construct(SessionAvecProfil, allowed_domains=["x"], headless=True,
                   user_data_dir="/tmp/isole")
    assert s.user_data_dir == "/tmp/isole"

    # Version qui ne l'accepte pas : on n'échoue pas, mais on AVERTIT.
    class SessionSansProfil:
        def __init__(self, allowed_domains=None, headless=True):
            pass

    _construct(SessionSansProfil, allowed_domains=["x"], headless=True,
               user_data_dir="/tmp/isole")
    err = capsys.readouterr().err
    assert "isolation du profil non garantie" in err


def test_build_browse_llm_route_selon_le_provider():
    """La fabrique instancie la bonne classe Browser-Use selon le préfixe."""
    import types
    from osint.analyse.browse import _build_browse_llm

    # Faux module browser_use : chaque classe mémorise ses kwargs.
    class _Fake:
        def __init__(self, **kw): self.kw = kw
    class ChatAnthropic(_Fake): pass
    class ChatOpenAI(_Fake): pass
    class ChatOllama(_Fake): pass
    fake_bu = types.SimpleNamespace(
        ChatAnthropic=ChatAnthropic, ChatOpenAI=ChatOpenAI, ChatOllama=ChatOllama)

    from osint.config import Config

    def cfg_with(model, api_base=None):
        return Config({
            "topologie": "x",
            "topologies": {"x": {"model": model, "api_base": api_base}},
            "modele": {"api_key": "sk-test"},
        })

    # anthropic/
    llm = _build_browse_llm(cfg_with("anthropic/claude-sonnet-4-6"), bu_module=fake_bu)
    assert isinstance(llm, ChatAnthropic) and llm.kw["model"] == "claude-sonnet-4-6"

    # openai/ (endpoint interne) -> base_url transmis
    llm = _build_browse_llm(cfg_with("openai/mixtral", "http://ofdf-ia:8000/v1"), bu_module=fake_bu)
    assert isinstance(llm, ChatOpenAI) and llm.kw["base_url"] == "http://ofdf-ia:8000/v1"

    # ollama/ (local) -> host transmis
    llm = _build_browse_llm(cfg_with("ollama/qwen3:8b", "http://localhost:11434"), bu_module=fake_bu)
    assert isinstance(llm, ChatOllama) and llm.kw["host"] == "http://localhost:11434"


def test_build_browse_llm_provider_inconnu():
    import types
    import pytest
    from osint.analyse.browse import _build_browse_llm
    from osint.config import Config
    cfg = Config({"topologie": "x", "topologies": {"x": {"model": "cohere/xxx"}},
                  "modele": {"api_key": "k"}})
    with pytest.raises(ValueError, match="non supporté"):
        _build_browse_llm(cfg, bu_module=types.SimpleNamespace())