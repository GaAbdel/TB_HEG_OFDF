"""Tests du chargeur de configuration et du résolveur de modèle."""

from __future__ import annotations

import textwrap

import pytest

from osint.config import Config, ConfigError

YAML = textwrap.dedent(
    """
    topologie: locale
    topologies:
      locale:
        api_base: ${OLLAMA_BASE_URL}
        model: ollama/qwen3:8b
      centrale:
        api_base: http://serveur-ia-interne:8000/v1
        model: openai/qwen3-8b
      cloud:
        api_base: null
        model: anthropic/claude-sonnet-4-5
    per_agent:
      LLM-CODE:
        model: ollama/qwen2.5-coder:7b
    lpd:
      exiger_consentement_cloud: true
    qdrant:
      collections:
        customs_rules: customs_rules
        confirmed_suspicious: confirmed_suspicious
    """
)


def make(monkeypatch, **env) -> Config:
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    import yaml

    return Config(yaml.safe_load(YAML))


def test_env_substitution(monkeypatch):
    cfg = make(monkeypatch, OLLAMA_BASE_URL="http://host.docker.internal:11434")
    assert cfg.resolve_model().api_base == "http://host.docker.internal:11434"


def test_env_unresolved_becomes_none(monkeypatch):
    # OLLAMA_BASE_URL non défini -> api_base None (distinct de chaine vide)
    monkeypatch.delenv("OLLAMA_BASE_URL", raising=False)
    cfg = make(monkeypatch)
    assert cfg.resolve_model().api_base is None


def test_default_model(monkeypatch):
    cfg = make(monkeypatch, OLLAMA_BASE_URL="http://x:11434")
    spec = cfg.resolve_model()  # aucun agent -> défaut topologie
    assert spec.model == "ollama/qwen3:8b"


def test_per_agent_override(monkeypatch):
    cfg = make(monkeypatch, OLLAMA_BASE_URL="http://x:11434")
    spec = cfg.resolve_model("LLM-CODE")
    assert spec.model == "ollama/qwen2.5-coder:7b"
    # api_base hérité du défaut topologie
    assert spec.api_base == "http://x:11434"


def test_agent_without_override_uses_default(monkeypatch):
    cfg = make(monkeypatch, OLLAMA_BASE_URL="http://x:11434")
    assert cfg.resolve_model("LLM-SCORE").model == "ollama/qwen3:8b"


def test_topology_switch(monkeypatch):
    import yaml

    raw = yaml.safe_load(YAML)
    raw["topologie"] = "centrale"
    cfg = Config(raw)
    spec = cfg.resolve_model()
    assert spec.model == "openai/qwen3-8b"
    assert spec.api_base == "http://serveur-ia-interne:8000/v1"


def test_litellm_kwargs(monkeypatch):
    cfg = make(monkeypatch, OLLAMA_BASE_URL="http://x:11434")
    kwargs = cfg.resolve_model().as_litellm_kwargs()
    assert kwargs["model"] == "ollama/qwen3:8b"
    assert kwargs["api_base"] == "http://x:11434"
    assert "api_key" not in kwargs  # absent en local


def test_lpd_guard_blocks_cloud(monkeypatch):
    import yaml

    raw = yaml.safe_load(YAML)
    raw["topologie"] = "cloud"
    cfg = Config(raw)
    assert cfg.cloud_consent_required() is True
    with pytest.raises(ConfigError, match="GARDE-FOU LPD"):
        cfg.assert_lpd_compliance(consentement_cloud=False)
    # accepté explicitement -> ne lève pas
    cfg.assert_lpd_compliance(consentement_cloud=True)


def test_lpd_guard_local_ok(monkeypatch):
    cfg = make(monkeypatch, OLLAMA_BASE_URL="http://x:11434")
    assert cfg.cloud_consent_required() is False
    cfg.assert_lpd_compliance()  # ne lève pas


def test_unknown_topology_raises(monkeypatch):
    import yaml

    raw = yaml.safe_load(YAML)
    raw["topologie"] = "inexistante"
    with pytest.raises(ConfigError, match="absente"):
        Config(raw).resolve_model()


def test_mode_b_sites_et_verrou(tmp_path):
    import yaml
    from osint.config import Config
    raw = {
        "topologie": "locale",
        "topologies": {"locale": {"modele": {"model": "ollama/qwen3:8b"}}},
        "mode_b": {
            "sites_autorises": [
                {"label": "Tutti", "base_url": "https://tutti.ch", "platform": "tutti"},
                {"label": "Incomplet"},  # ignoré (pas de base_url)
            ],
            "autonomous_search_enabled": False,
        },
    }
    cfg = Config(raw)
    labels = [s["label"] for s in cfg.mode_b_sites()]
    assert labels == ["Tutti"]                              # l'entrée incomplète est écartée
    assert cfg.mode_b_site_by_label("Tutti")["platform"] == "tutti"
    assert cfg.mode_b_site_by_label("Le Bon Coin") is None  # non autorisé
    assert cfg.mode_b_autonomous_enabled() is False         # verrou par défaut


def test_is_third_party_transfer_par_agent():
    """Le garde-fou LPD détecte un transfert cloud PAR AGENT, même en topologie locale."""
    from osint.config import Config
    cfg = Config({
        "topologie": "locale",
        "topologies": {"locale": {"model": "ollama/qwen3:8b", "api_base": "http://ollama"}},
        "modele": {"api_key": ""},
        "per_agent": {"LLM-BROWSE": {"model": "anthropic/claude-sonnet-4-6"}},
        "lpd": {"exiger_consentement_cloud": True},
    })
    # LLM-BROWSE part chez Anthropic => transfert tiers, MÊME si topologie locale.
    assert cfg.is_third_party_transfer("LLM-BROWSE") is True
    # Les autres agents restent locaux (Ollama).
    assert cfg.is_third_party_transfer("LLM-SCORE") is False
    # Un endpoint OpenAI-compatible INTERNE n'est pas un transfert tiers.
    cfg2 = Config({
        "topologie": "centrale",
        "topologies": {"centrale": {"model": "openai/qwen3-8b",
                                    "api_base": "http://serveur-ia-interne:8000/v1"}},
        "modele": {"api_key": ""},
    })
    assert cfg2.is_third_party_transfer("LLM-SCORE") is False
    # OpenAI public (sans api_base) = tiers externe.
    cfg3 = Config({
        "topologie": "cloud",
        "topologies": {"cloud": {"model": "openai/gpt-4o", "api_base": None}},
        "modele": {"api_key": "k"},
    })
    assert cfg3.is_third_party_transfer("LLM-SCORE") is True