"""Chargement de la configuration et résolution du modèle par agent.

Ce module centralise l'accès a `config.yaml` et implémente le résolveur de
modèle : il fusionne le modèle par défaut de la topologie active avec
d'éventuelles surcharges propres a un agent (bloc `per_agent`).

Le service de modèle étant entièrement abstrait par LiteLLM, la topologie de
déploiement (locale / centrale / cloud) est un simple paramètre.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

_ENV_PATTERN = re.compile(r"\$\{([^}]+)\}")

DEFAULT_CONFIG_PATH = Path(os.environ.get("OSINT_CONFIG", "config.yaml"))


class ConfigError(RuntimeError):
    """Erreur de configuration (fichier manquant, topologie inconnue, etc.)."""


@dataclass(frozen=True)
class ModelSpec:
    """Résolution d'un modèle pour un agent donné."""

    model: str
    api_base: str | None
    api_key: str | None = None

    def as_litellm_kwargs(self) -> dict[str, Any]:
        """Arguments prêts a passer a `litellm.completion(...)`."""
        kwargs: dict[str, Any] = {"model": self.model}
        if self.api_base:
            kwargs["api_base"] = self.api_base
        if self.api_key:
            kwargs["api_key"] = self.api_key
        return kwargs


def _substitute_env(value: Any) -> Any:
    """Remplace récursivement les références ${VAR} par les variables d'env.

    Une référence non définie est remplacée par None (et non par une chaine
    vide) afin de distinguer "absent" de "vide" en aval.
    """
    if isinstance(value, str):
        def repl(match: re.Match[str]) -> str:
            return os.environ.get(match.group(1), "")

        substituted = _ENV_PATTERN.sub(repl, value)
        # Si toute la valeur était une unique référence non résolue -> None
        if substituted == "" and _ENV_PATTERN.fullmatch(value):
            return None
        return substituted
    if isinstance(value, dict):
        return {k: _substitute_env(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_substitute_env(v) for v in value]
    return value


class Config:
    """Vue typée sur `config.yaml`."""

    def __init__(self, raw: dict[str, Any]) -> None:
        self._raw = _substitute_env(raw)

    # --- Chargement ----------------------------------------------------------
    @classmethod
    def load(cls, path: Path | str = DEFAULT_CONFIG_PATH) -> "Config":
        path = Path(path)
        if not path.exists():
            raise ConfigError(f"Fichier de configuration introuvable : {path}")
        with path.open(encoding="utf-8") as fh:
            raw = yaml.safe_load(fh) or {}
        return cls(raw)

    # --- Accès générique -----------------------------------------------------
    def get(self, *keys: str, default: Any = None) -> Any:
        node: Any = self._raw
        for key in keys:
            if not isinstance(node, dict) or key not in node:
                return default
            node = node[key]
        return node

    @property
    def topologie(self) -> str:
        # Surcharge par variable d'environnement (12-factor) : permet d'utiliser
        # une topologie différente selon la machine SANS modifier config.yaml.
        # Cas d'usage : dev sur laptop (TOPOLOGIE=cloud, tout en API) alors que
        # le livrable reste `locale` par défaut (souveraineté sur la VM OFDF).
        env = os.environ.get("TOPOLOGIE")
        if env:
            return env.strip()
        return self.get("topologie", default="locale")

    # --- Mode B : exploration (allowlist + verrou recherche autonome) ---------
    def mode_b_sites(self) -> list[dict]:
        """Sites autorisés pour l'exploration Mode B (label + base_url).

        Cette liste EST le périmètre légal : l'enquêteur choisit dedans, il ne
        l'étend pas. Ajouter un site est une action d'administration (config).
        """
        sites = self.get("mode_b", "sites_autorises", default=[]) or []
        out = []
        for s in sites:
            if isinstance(s, dict) and s.get("label") and s.get("base_url"):
                out.append({
                    "label": str(s["label"]),
                    "base_url": str(s["base_url"]),
                    "platform": str(s.get("platform") or s["label"]),
                })
        return out

    def mode_b_site_by_label(self, label: str) -> dict | None:
        """Retourne le site autorisé correspondant au label, ou None (non autorisé)."""
        for s in self.mode_b_sites():
            if s["label"] == label:
                return s
        return None

    def mode_b_autonomous_enabled(self) -> bool:
        """Verrou du Mode B-2 (recherche autonome de sites).

        Désactivé par défaut : son activation relève d'une décision de
        l'administrateur OFDF. Tant que False, l'endpoint refuse toute recherche
        autonome et l'action de recherche web reste exclue de l'agent.
        """
        return bool(self.get("mode_b", "autonomous_search_enabled", default=False))

    # --- Réparation de CODE (verrou, comme B-2) -------------------------------

    def code_repair_enabled(self) -> bool:
        """Verrou de la réparation d'extracteurs de CODE (.py) par LLM-CODE.

        Désactivé par défaut : franchit la frontière d'auditabilité (génération
        de code). Son activation relève d'une décision de l'administrateur OFDF.
        Même activé, le code proposé n'est JAMAIS exécuté par l'application : il
        est déposé dans un dossier de propositions et installé MANUELLEMENT par
        un développeur.
        """
        return bool(self.get("code_repair", "enabled", default=False))

    def code_repair_proposals_dir(self) -> str:
        """Dossier où LLM-CODE dépose les extracteurs proposés (jamais exécutés)."""
        return str(self.get("code_repair", "proposals_dir", default="data/extractor_proposals"))

    def code_repair_validate(self) -> bool:
        """Si vrai, le code proposé est passé au dispositif d'exécution isolée
        (sous-processus + timeout) et corrigé en boucle. Sinon, généré une seule
        fois sans exécution."""
        return bool(self.get("code_repair", "validate", default=True))

    def code_repair_max_iters(self) -> int:
        """Nombre maximal de tentatives de correction dans la boucle."""
        return int(self.get("code_repair", "max_iters", default=3))

    # --- Résolution du modèle ------------------------------------------------
    def resolve_model(self, agent: str | None = None) -> ModelSpec:
        """Résout le modèle pour un agent.

        Stratégie : modèle par défaut de la topologie active, surchargé le cas
        échéant par le bloc `per_agent[<agent>]`. C'est l'unique point ou la
        topologie influe sur le code : tout le reste du pipeline ignore ou
        s'exécute le modèle.
        """
        topo = self.topologie
        topo_block = self.get("topologies", topo)
        if topo_block is None:
            raise ConfigError(
                f"Topologie '{topo}' absente du bloc 'topologies' de config.yaml"
            )

        model = topo_block.get("model")
        api_base = topo_block.get("api_base")
        api_key = self.get("modele", "api_key")

        # Surcharge par agent (optionnelle)
        if agent:
            override = (self.get("per_agent") or {}).get(agent) or {}
            model = override.get("model", model)
            api_base = override.get("api_base", api_base)

        if not model:
            raise ConfigError(
                f"Aucun modèle résolu pour l'agent '{agent}' (topologie '{topo}')"
            )
        return ModelSpec(model=model, api_base=api_base, api_key=api_key)

    # --- Garde-fou LPD (LLM02) -----------------------------------------------
    def is_third_party_transfer(self, agent: str | None = None) -> bool:
        """Vrai si le modèle résolu pour cet agent transmet les données HORS du
        périmètre OFDF (fournisseur cloud public : Anthropic, OpenAI public).

        Contrairement à `cloud_consent_required` (qui ne regarde que la topologie
        globale), cette détection tient compte du routage `per_agent` : un seul
        agent (ex. LLM-BROWSE) peut sortir dans le cloud même si la topologie
        globale est `locale`. Un endpoint OpenAI-compatible INTERNE (topologie
        centrale, api_base privé) reste dans le périmètre => pas un transfert tiers.
        """
        spec = self.resolve_model(agent)
        provider = spec.model.split("/", 1)[0] if "/" in spec.model else ""
        if provider == "anthropic":
            return True
        if provider == "openai":
            base = spec.api_base or ""
            # Sans api_base (ou api_base public) => OpenAI public = tiers externe.
            # Un api_base interne (serveur IA OFDF) reste dans le périmètre.
            return (not base) or ("openai.com" in base)
        return False  # ollama = local, aucun transfert

    def cloud_consent_required(self) -> bool:
        """Vrai si la topologie active est cloud et le garde-fou de consentement actif."""
        return self.topologie == "cloud" and bool(
            self.get("lpd", "exiger_consentement_cloud", default=True)
        )

    def assert_lpd_compliance(
        self,
        consentement_cloud: bool = False,
        agents: list[str] | None = None,
    ) -> None:
        """Bloque l'exécution qui transmettrait des données à un fournisseur tiers
        sans consentement explicite (souveraineté des données, art. 34 LPD).

        Deux niveaux de détection, cumulés :
          - topologie globale « cloud » ;
          - `agents` : chaque agent est contrôlé INDIVIDUELLEMENT via
            `is_third_party_transfer`, ce qui couvre le routage `per_agent` (un
            seul agent, ex. LLM-BROWSE, peut sortir dans le cloud alors que la
            topologie globale reste « locale »).
        """
        # Le garde-fou peut être désactivé explicitement en configuration.
        if not self.get("lpd", "exiger_consentement_cloud", default=True):
            return

        # Détection des transferts vers un tiers, avec le fournisseur concerné.
        cibles: list[str] = []
        if self.topologie == "cloud":
            provider = self.resolve_model().model.split("/", 1)[0]
            cibles.append(f"topologie=cloud ({provider})")
        for agent in agents or []:
            if self.is_third_party_transfer(agent):
                provider = self.resolve_model(agent).model.split("/", 1)[0]
                cibles.append(f"{agent} ({provider})")

        if cibles and not consentement_cloud:
            detail = ", ".join(dict.fromkeys(cibles))  # dédupliqué, ordre stable
            raise ConfigError(
                "Attention : traitement dans le cloud — les données sont "
                f"transmises à un fournisseur tiers ({detail})."
            )


# Singleton paresseux, pratique pour l'API et les scripts.
_config: Config | None = None


def get_config(reload: bool = False) -> Config:
    global _config
    if _config is None or reload:
        _config = Config.load()
    return _config