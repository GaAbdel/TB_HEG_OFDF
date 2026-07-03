"""Embeddings multilingues (FR/DE) via fastembed sans torch .

`intfloat/multilingual-e5-large` -> multilingue, dimension 1024, compatible avec les collections Qdrant).

Les modèles de la famille « e5 » exigent un PRÉFIXE selon l'usage :
  - « query: »   pour une requête (l'annonce à analyser) ;
  - « passage: » pour un document indexé (une règle douanière).
Respecter ces préfixes est important pour la qualité de la recherche.

Le modèle (~2.2 Go) est téléchargé au premier appel puis mis en cache dans
`embeddings.cache_dir` (volume Docker persistant). L'import de fastembed est
lazy : ce module reste importable sans le modèle.
"""

from __future__ import annotations

from functools import lru_cache
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from osint.config import Config


@lru_cache(maxsize=2)
def _model(model_name: str, cache_dir: str | None):
    """Charge (une seule fois) le modèle fastembed. Coûteux : mis en cache."""
    from fastembed import TextEmbedding  # import paresseux

    return TextEmbedding(model_name=model_name, cache_dir=cache_dir)


def _params(cfg: "Config") -> tuple[str, str | None, str, str]:
    return (
        cfg.get("embeddings", "model", default="intfloat/multilingual-e5-large"),
        cfg.get("embeddings", "cache_dir", default=None),
        cfg.get("embeddings", "query_prefix", default="query: "),
        cfg.get("embeddings", "passage_prefix", default="passage: "),
    )


def embed_passages(cfg: "Config", texts: list[str]) -> list[list[float]]:
    """Vectorise des DOCUMENTS à indexer (règles). Applique le préfixe passage."""
    model_name, cache_dir, _, passage_prefix = _params(cfg)
    model = _model(model_name, cache_dir)
    prefixed = [f"{passage_prefix}{t}" for t in texts]
    return [vec.tolist() for vec in model.embed(prefixed)]


def embed_query(cfg: "Config", text: str) -> list[float]:
    """Vectorise une REQUÊTE (l'annonce). Applique le préfixe query."""
    model_name, cache_dir, query_prefix, _ = _params(cfg)
    model = _model(model_name, cache_dir)
    vec = next(iter(model.embed([f"{query_prefix}{text}"])))
    return vec.tolist()