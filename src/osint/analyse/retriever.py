"""Récupération de règles douanières (RAG) — interface + implémentation.

`RuleRetriever` est le CONTRAT : « donne-moi les règles pertinentes pour ce
texte ». `QdrantRuleRetriever` est l'implémentation locale (vectorise l'annonce
puis interroge Qdrant). Le scoring ne dépend que du contrat : une future base
documentaire centrale n'aurait qu'à fournir une autre implémentation du même
contrat, sans toucher au pipeline d'analyse.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

from osint.analyse.embeddings import embed_query
from osint.persistance.qdrant import _client

if TYPE_CHECKING:
    from osint.config import Config


class RuleRetriever(Protocol):
    """Contrat d'une source de règles."""

    def retrieve(self, text: str, *, k: int | None = None) -> list[dict]:
        """Renvoie les règles pertinentes pour `text` (les plus proches d'abord)."""
        ...


class QdrantRuleRetriever:
    """Récupère les règles dans la collection Qdrant `customs_rules`."""

    def __init__(
        self,
        cfg: "Config",
        *,
        collection: str = "customs_rules",
        top_k: int = 3,
        score_threshold: float = 0.0,
    ) -> None:
        self.cfg = cfg
        self.collection = collection
        self.top_k = top_k
        self.score_threshold = score_threshold

    @classmethod
    def from_config(cls, cfg: "Config") -> "QdrantRuleRetriever":
        rag = cfg.get("rag", default={}) or {}
        collection = cfg.get("qdrant", "collections", "customs_rules", default="customs_rules")
        return cls(
            cfg,
            collection=collection,
            top_k=int(rag.get("top_k", 3)),
            score_threshold=float(rag.get("score_threshold", 0.0)),
        )

    def retrieve(self, text: str, *, k: int | None = None) -> list[dict]:
        vector = embed_query(self.cfg, text)
        client = _client(self.cfg)
        hits = client.search(
            collection_name=self.collection,
            query_vector=vector,
            limit=k or self.top_k,
            score_threshold=self.score_threshold or None,
            with_payload=True,
        )
        return [{"score": round(h.score, 3), **(h.payload or {})} for h in hits]