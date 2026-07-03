"""Client du service de modèle via LiteLLM.

Abstraction unique au-dessus des trois topologies (locale / centrale / cloud).
Le reste du pipeline appelle `complete(agent=..., messages=...)` sans jamais
connaitre l'emplacement réel du modèle.

Deux entrées : `ping` (sonde de disponibilité de l'endpoint) et `complete`
(envoie une requête au modèle résolu et renvoie le texte de la réponse).
"""


from __future__ import annotations
 
from typing import Any
 
from osint.config import Config
 
 
def ping(cfg: Config) -> tuple[bool, str]:
    """Vérifie que l'endpoint du modèle répond. Ne lève jamais.
 
    On interroge l'endpoint OpenAI-compatible (`/api/tags` pour Ollama,
    sinon le résolveur fournit l'api_base). En topologie cloud sans api_base,
    on considère la sonde non applicable.
    """
    try:
        import httpx  # import paresseux
    except ImportError:
        return False, "httpx non installé"
 
    spec = cfg.resolve_model()
    if not spec.api_base:
        return True, "topologie cloud (api_base implicite, sonde ignorée)"
 
    base = spec.api_base.rstrip("/")
    # Ollama expose /api/tags ; un endpoint OpenAI-compatible expose /models.
    for path in ("/api/tags", "/models", "/v1/models"):
        url = base + path
        try:
            r = httpx.get(url, timeout=3)
            if r.status_code < 500:
                return True, f"ok ({path}, {r.status_code})"
        except Exception:  # noqa: BLE001 — on tente le chemin suivant
            continue
    return False, f"aucune réponse du service de modèle ({base})"
 
 
def complete(
    cfg: Config,
    *,
    messages: list[dict[str, str]],
    agent: str | None = None,
    temperature: float = 0.0,
    max_tokens: int = 1024,
    **extra: Any,
) -> str:
    """Envoie une requête au modèle résolu et renvoie le texte de la réponse.
 
    Le modèle (et son éventuelle clé/endpoint) est déterminé par la topologie
    active via `cfg.resolve_model(agent)`. Le préfixe du nom de modèle
    (`anthropic/`, `openai/`, `ollama/`) indique à LiteLLM où router : le reste
    du pipeline n'a pas à le savoir.
 
    Note : le franchissement du garde-fou LPD (consentement cloud) est de la
    responsabilité de l'appelant, AVANT d'appeler cette fonction.
    """
    import litellm  # import paresseux : pas requis pour les tests hors-ligne
 
    spec = cfg.resolve_model(agent)
    response = litellm.completion(
        messages=messages,
        temperature=temperature,
        max_tokens=max_tokens,
        **spec.as_litellm_kwargs(),
        **extra,
    )
    return response.choices[0].message.content or ""
 