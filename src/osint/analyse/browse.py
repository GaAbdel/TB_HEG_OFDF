"""LLM-BROWSE — Mode B : exploration bornée de sites inconnus/dynamiques.

Fondé sur Browser-Use. Conformément au principe planificateur/exécuteur ,
le modèle propose des actions mais l'exécution reste contrainte par des
garde-fous déterministes portés par la session navigateur :

  - allowed_domains : périmètre de navigation borné, le navigateur
    refuse toute sortie du domaine d'amorce ;
  - max_steps : budget d'actions plafonné ;
  - exclude_actions : actions retirées (ex. recherche Google) pour empêcher
    l'agent de quitter le périmètre ;
  - use_vision=False / lecture seule : pas de capture, pas d'écriture ;
  - la trace des actions est récupérée pour la piste d'audit.

Browser-Use n'est pas testable hors d'un navigateur réel : ce module est conçu
pour être lancé en conditions réelles (scripts/browse_demo.py). Les fonctions
pures (consigne, périmètre, normalisation de la trace) sont, elles, testées.
"""

from __future__ import annotations

import os
import re
import sys
import tempfile
from typing import TYPE_CHECKING
from urllib.parse import urlparse

from osint.analyse.scorer import load_prompt, prompt_hash

if TYPE_CHECKING:
    from osint.config import Config

# Actions retirées par défaut : empêchent l'agent de quitter le périmètre.
DEFAULT_EXCLUDED_ACTIONS: tuple[str, ...] = ("search_google",)


def build_browse_task(start_url: str, *, focus: str = "",
                      generated_terms: list[str] | None = None,
                      prompt_version: str = "browse_v1") -> str:
    """Construit la consigne métier (lecture seule) à partir du prompt versionné.

    `focus` (optionnel, saisi par l'enquêteur) oriente l'exploration : s'il est
    fourni, l'agent PRIORISE les annonces pouvant relever de cet objet — y
    compris les formulations implicites ou détournées — tout en continuant de
    relever ce qui paraît suspect au-delà. Sans focus, l'exploration reste libre
    (comportement par défaut). C'est l'enquêteur qui décide d'orienter ou non ;
    l'agent ne fixe jamais lui-même une cible.

    `generated_terms` (issus de LLM-EXPAND) sont fournis à l'agent comme des
    EXEMPLES NON LIMITATIFS de formes possibles, jamais comme un filtre littéral :
    ils aident un modèle peu capable sans l'enfermer dans la correspondance de
    mots-clés, ce qui ferait manquer les annonces déguisées (cœur du système).
    """
    template = load_prompt(prompt_version)
    task = template.replace("{start_url}", start_url)
    focus = (focus or "").strip()
    terms = [t for t in (generated_terms or []) if t]
    if "{focus_block}" in task:
        if focus:
            exemples = ""
            if terms:
                exemples = (
                    "Exemples de formes possibles (liste NON exhaustive, ne pas s'y "
                    f"limiter) : {', '.join(terms)}.\n"
                )
            bloc = (
                f"\nObjet prioritaire de la recherche : {focus}\n"
                f"{exemples}"
                "Relève EN PRIORITÉ les annonces pouvant relever de cet objet, y "
                "compris les formulations implicites ou détournées (désignations "
                "vagues, absence de mention explicite). Ne te limite pas à une "
                "correspondance littérale de mots. Continue néanmoins de relever "
                "les autres annonces rencontrées, même hors de cet objet, dans la "
                "limite du budget d'actions.\n"
            )
        else:
            bloc = ""
        task = task.replace("{focus_block}", bloc)
    return task


def resolve_allowed_domains(start_url: str, extra: list[str] | None = None) -> list[str]:
    """Périmètre borné du Mode B : le domaine d'amorce (+ ajouts éventuels).

    On autorise l'hôte nu et un motif http*://hôte/* (certains contrôles de
    domaine de Browser-Use comparent l'URL complète).
    """
    host = urlparse(start_url).hostname or ""
    domains: list[str] = []
    if host:
        domains.append(host)
        domains.append(f"http*://{host}/*")
    if extra:
        domains.extend(extra)
    return domains


# ----------------------------------------------------------------------------
# Multi-fournisseur pour LLM-BROWSE — voir _build_browse_llm() plus bas.
# ----------------------------------------------------------------------------
# Contrairement aux agents EXPAND/SCORE/PARSE/CODE (qui passent par LiteLLM,
# basculement de fournisseur piloté par config.yaml sans code), Browser-Use
# n'utilise pas LiteLLM : il impose ses propres classes de modèles. Pour rester
# fidèle au principe « le modèle est un paramètre de config », _build_browse_llm
# lit le préfixe du modèle résolu (anthropic/ | openai/ | ollama/) et instancie
# la classe Browser-Use correspondante. L'OFDF adapte donc LLM-BROWSE comme les
# autres agents, en une ligne de config.yaml (per_agent: LLM-BROWSE).


# Kwargs dont le retrait silencieux serait dangereux (isolation du profil) :
# si la version de Browser-Use ne les accepte pas, on le SIGNALE.
_CRITICAL_KWARGS = {"user_data_dir"}


def _construct(cls, **kwargs):
    """Instancie `cls`, en retirant les kwargs non supportés par la version.

    Browser-Use 0.12.9 n'expose pas exactement les mêmes paramètres que les
    versions ultérieures ; cette tolérance évite un crash sur un kwarg optionnel
    (use_thinking, controller…) tout en conservant les garde-fous essentiels.

    Un kwarg d'isolation critique (ex. user_data_dir) retiré est SIGNALÉ sur
    stderr : son absence pourrait laisser l'agent toucher au profil réel.
    """
    while True:
        try:
            return cls(**kwargs)
        except TypeError as exc:
            m = re.search(r"unexpected keyword argument '(\w+)'", str(exc))
            if m and m.group(1) in kwargs:
                name = m.group(1)
                if name in _CRITICAL_KWARGS:
                    print(
                        f"[browse] ATTENTION : '{name}' non supporté par cette "
                        f"version de Browser-Use — isolation du profil non "
                        f"garantie. Fermez votre navigateur avant la démo.",
                        file=sys.stderr,
                    )
                kwargs.pop(name)
                continue
            raise


def _build_browse_llm(cfg: "Config", model_override: str | None = None, *, bu_module=None):
    """Instancie le client LLM de Browser-Use selon le FOURNISSEUR configuré.

    Lit le modèle résolu pour LLM-BROWSE (config.yaml, éventuellement surchargé
    par per_agent) et route vers la classe Browser-Use adaptée :
      - anthropic/<modele>  -> ChatAnthropic (clé API)
      - openai/<modele>     -> ChatOpenAI   (clé + base_url : endpoint interne OFDF, vLLM, TGI…)
      - ollama/<modele>     -> ChatOllama   (host : serveur Ollama local)

    Ainsi l'OFDF adapte LLM-BROWSE en une ligne de config, comme les autres
    agents — y compris vers un modèle 100 % local s'il est assez capable.
    `bu_module` est injectable pour les tests (sans dépendance réelle).
    """
    if bu_module is None:
        import browser_use as bu_module  # import paresseux

    spec = cfg.resolve_model("LLM-BROWSE")
    raw = model_override or spec.model
    provider, sep, name = raw.partition("/")
    if not sep:                                   # pas de préfixe -> Anthropic par défaut
        provider, name = "anthropic", raw
    api_key = spec.api_key or os.environ.get("LLM_API_KEY") or os.environ.get("ANTHROPIC_API_KEY")

    cls_name = {"anthropic": "ChatAnthropic", "openai": "ChatOpenAI",
                "ollama": "ChatOllama"}.get(provider)
    if cls_name is None:
        raise ValueError(
            f"Fournisseur LLM-BROWSE non supporté : '{provider}'. Utilisez un préfixe "
            f"anthropic/, openai/ ou ollama/ dans config.yaml (per_agent: LLM-BROWSE)."
        )
    cls = getattr(bu_module, cls_name, None)
    if cls is None:
        raise ImportError(
            f"Cette version de Browser-Use n'expose pas '{cls_name}'. "
            f"Mettez à jour browser-use ou choisissez un autre fournisseur pour LLM-BROWSE."
        )

    if provider == "anthropic":
        return _construct(cls, model=name, api_key=api_key)
    if provider == "openai":
        # Endpoint OpenAI-compatible : base_url pointe vers le serveur interne.
        return _construct(cls, model=name, api_key=api_key, base_url=spec.api_base)
    # ollama : host = URL du serveur Ollama (pas de clé requise).
    return _construct(cls, model=name, host=spec.api_base)


def _trace(history) -> dict:
    """Extrait, au mieux, une trace auditable de la session (selon la version)."""
    trace: dict = {}
    for name, attr in (("urls", "urls"), ("actions", "action_names")):
        try:
            value = getattr(history, attr)()
            trace[name] = value
        except Exception:  # pragma: no cover - dépend de la version de la lib
            pass
    # Raisonnement déclaré par l'agent à chaque pas (explicabilité indicative).
    try:  # pragma: no cover - dépend de la version de la lib
        thoughts = []
        for t in history.model_thoughts():
            thoughts.append({
                "eval": getattr(t, "evaluation_previous_goal", None),
                "memory": getattr(t, "memory", None),
                "next_goal": getattr(t, "next_goal", None),
            })
        trace["thoughts"] = thoughts
    except Exception:  # pragma: no cover
        pass
    return trace


async def run_browse(
    cfg: "Config",
    start_url: str,
    *,
    max_steps: int = 12,
    headless: bool = True,
    model: str | None = None,
    focus: str = "",
    generated_terms: list[str] | None = None,
    allowed_domains: list[str] | None = None,
    exclude_actions: tuple[str, ...] = DEFAULT_EXCLUDED_ACTIONS,
    audit_log_dir: str | None = "data/audit",
    user_data_dir: str | None = None,
) -> dict:
    """Lance une exploration bornée (Mode B) et renvoie le résultat + la trace.

    Le garde-fou LPD (consentement cloud) est vérifié avant tout appel distant.

    Isolation du navigateur : par défaut, un profil JETABLE (dossier temporaire
    dédié) est utilisé, pour ne JAMAIS toucher au profil personnel de
    l'utilisateur (plugins, réglages). Passez `user_data_dir` pour imposer un
    dossier précis.
    """
    cfg.assert_lpd_compliance(consentement_cloud=True)
    # Avertissement LPD par agent : Browser-Use pilote LLM-BROWSE, qui peut
    # résoudre vers un fournisseur cloud (Anthropic) même en topologie locale.
    # Dans ce cas, les données explorées transitent par un tiers => on le SIGNALE
    # explicitement (auditabilité, souveraineté des données), sans bloquer :
    # l'exploration Mode B est déclenchée sciemment par l'enquêteur.
    if cfg.is_third_party_transfer("LLM-BROWSE") and cfg.get(
        "lpd", "exiger_consentement_cloud", default=True
    ):
        provider = cfg.resolve_model("LLM-BROWSE").model.split("/", 1)[0]
        print(
            f"⚠️  AVERTISSEMENT LPD : LLM-BROWSE utilise un fournisseur cloud "
            f"({provider}). Les données explorées sont transmises à un tiers "
            f"hors du périmètre OFDF (art. 34 LPD).",
            file=sys.stderr,
        )

    # Imports paresseux : browser_use n'est requis qu'à l'exécution réelle.
    from browser_use import Agent
    from browser_use.browser import BrowserSession

    try:
        from browser_use import Controller
    except ImportError:  # pragma: no cover
        Controller = None  # type: ignore

    # Modèle résolu (préfixé) pour la trace ; la fabrique route vers le bon fournisseur.
    model = model or cfg.resolve_model("LLM-BROWSE").model
    browse_llm = _build_browse_llm(cfg, model)
    domains = allowed_domains if allowed_domains is not None else resolve_allowed_domains(start_url)
    system_prompt = load_prompt("browse_v1")

    # Profil de navigateur ISOLÉ et jetable : garantit qu'on ne touche jamais
    # au profil personnel de l'utilisateur (plugins, historique, réglages).
    profile_dir = user_data_dir or tempfile.mkdtemp(prefix="osint_browse_profile_")

    # Exécuteur : la session porte le périmètre borné (garde-fou déterministe)
    # et un profil isolé (protection du navigateur personnel).
    session = _construct(
        BrowserSession,
        allowed_domains=domains,
        headless=headless,
        user_data_dir=profile_dir,
    )

    agent_kwargs = dict(
        task=build_browse_task(start_url, focus=focus, generated_terms=generated_terms),
        llm=browse_llm,
        browser_session=session,
        use_vision=True,      # lecture seule, pas de capture
        use_thinking=False,    # stabilise le format de sortie (corrige les erreurs Pydantic)
    )
    if Controller is not None and exclude_actions:
        agent_kwargs["controller"] = _construct(Controller, exclude_actions=list(exclude_actions))

    agent = _construct(Agent, **agent_kwargs)
    history = await agent.run(max_steps=max_steps)

    result = {
        "result": history.final_result(),
        "start_url": start_url,
        "allowed_domains": domains,
        "max_steps": max_steps,
        "model": model,
        "prompt_version": "browse_v1",
        "focus": focus or None,
        "generated_terms": [t for t in (generated_terms or []) if t] or None,
        "prompt_hash": prompt_hash(system_prompt),
        "trace": _trace(history),
    }

    # Journal d'audit scellé (fichier JSONL unique, ajout continu, même chaîne
    # de hash que l'audit central : un seul journal pour tout l'historique).
    if audit_log_dir:
        from osint.analyse.browse_audit import append_browse_log
        log_path = append_browse_log(result, f"{audit_log_dir}/browse.jsonl")
        result["audit_log"] = str(log_path)

    return result