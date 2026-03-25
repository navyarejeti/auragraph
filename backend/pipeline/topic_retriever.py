"""
pipeline/topic_retriever.py — RAG topic retrieval
───────────────────────────────────────────────────
For each slide topic, retrieves the most relevant textbook chunks using:
  1. Azure AI Search (hybrid vector + BM25) — when configured
  2. Numpy cosine similarity on in-memory VectorDB — always available
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pipeline.embedder import Embedder
    from pipeline.vector_db import VectorDB
    from pipeline.slide_analyzer import SlideTopic

logger = logging.getLogger(__name__)

_TEXTBOOK_BUDGET = 2000   # chars per topic in context window


def _chunks_to_context(chunks) -> str:
    parts, used = [], 0
    for c in chunks:
        text    = c.text if hasattr(c, "text") else str(c)
        heading = getattr(c, "heading", "")
        header  = f"[{heading}]\n" if heading else ""
        block   = header + text + "\n"
        if used + len(block) > _TEXTBOOK_BUDGET:
            break
        parts.append(block)
        used += len(block)
    return "\n---\n".join(parts) if parts else ""


class TopicRetriever:
    def __init__(self, vector_db: "VectorDB", embedder: "Embedder"):
        self._db      = vector_db
        self._embedder = embedder

    def retrieve_for_topic(self, topic: "SlideTopic",
                           nb_id: str = "", top_k: int = 4) -> str:
        """
        Retrieve relevant textbook context for one slide topic.
        Returns a plain-text string ready to paste into the LLM prompt.
        """
        query = f"{topic.topic} {' '.join(topic.key_points[:5])}"

        # 1. Azure AI Search (hybrid, persistent)
        if self._db.has_azure() and nb_id:
            query_vec = self._embedder.embed_query(query)
            chunks    = self._db.search_azure(nb_id, query_vec, query, top_k)
            if chunks:
                return _chunks_to_context(chunks)

        # 2. Numpy in-memory cosine similarity
        query_vec = self._embedder.embed_query(query)
        if query_vec is None or self._db.size == 0:
            return ""
        results = self._db.search(query_vec, top_k=top_k)
        return _chunks_to_context([c for _, c in results])

    def retrieve_all_topics(self, topics: list["SlideTopic"],
                            nb_id: str = "") -> dict[str, str]:
        """Retrieve context for every topic. Returns {topic_name: context_str}."""
        return {
            t.topic: self.retrieve_for_topic(t, nb_id=nb_id)
            for t in topics
        }
