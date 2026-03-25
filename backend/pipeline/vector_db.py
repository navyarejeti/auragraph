"""
pipeline/vector_db.py — Azure AI Search + numpy in-memory fallback
────────────────────────────────────────────────────────────────────
Stores and retrieves textbook chunk embeddings for RAG.

Priority:
  1. Azure AI Search (persistent, scalable) — AZURE_SEARCH_ENDPOINT + KEY
  2. numpy in-memory cosine similarity      — always available

Azure AI Search index schema:
  id          (string, key)
  nb_id       (string, filterable)
  text        (string)
  heading     (string)
  source      (string, filterable)
  position    (int32)
  embedding   (Collection(Single), searchable, dimensions=1536, vectorSearch)

The vector field uses HNSW for approximate nearest-neighbour search.
"""
from __future__ import annotations

import json
import logging
import os
import re
from pathlib import Path
from typing import Optional

import numpy as np

from pipeline.chunker import TextChunk

logger = logging.getLogger(__name__)

_INDEX_DIR = Path(__file__).parent.parent / "vector_index"
_INDEX_DIR.mkdir(exist_ok=True)


def _search_configured() -> bool:
    ep  = os.environ.get("AZURE_SEARCH_ENDPOINT", "")
    key = os.environ.get("AZURE_SEARCH_KEY", "")
    return bool(ep and key
                and "placeholder" not in ep.lower()
                and "your-" not in key.lower())


# ═══════════════════════════════════════════════════════════════════════════════
# Azure AI Search backend
# ═══════════════════════════════════════════════════════════════════════════════

class _AzureSearchVectorDB:
    """
    Uses Azure AI Search with a hybrid (vector + keyword) index.
    One index stores chunks from ALL notebooks; filtering on nb_id scopes results.
    """

    _INDEX_CREATED = False

    def __init__(self):
        from azure.search.documents import SearchClient
        from azure.search.documents.indexes import SearchIndexClient
        from azure.core.credentials import AzureKeyCredential

        endpoint   = os.environ.get("AZURE_SEARCH_ENDPOINT", "").rstrip("/")
        key        = os.environ.get("AZURE_SEARCH_KEY", "")
        self._index_name = os.environ.get("AZURE_SEARCH_INDEX", "auragraph-chunks")

        cred = AzureKeyCredential(key)
        self._client       = SearchClient(endpoint, self._index_name, cred)
        self._index_client = SearchIndexClient(endpoint, cred)

        if not _AzureSearchVectorDB._INDEX_CREATED:
            self._ensure_index()
            _AzureSearchVectorDB._INDEX_CREATED = True

        logger.info("vector_db: using Azure AI Search (index=%s)", self._index_name)

    def _ensure_index(self):
        """Create the Azure AI Search index if it doesn't exist."""
        from azure.search.documents.indexes.models import (
            SearchIndex, SearchField, SearchFieldDataType,
            SimpleField, SearchableField,
            VectorSearch, HnswAlgorithmConfiguration, VectorSearchProfile,
            SemanticConfiguration, SemanticSearch, SemanticPrioritizedFields,
            SemanticField,
        )
        try:
            self._index_client.get_index(self._index_name)
            return   # already exists
        except Exception:
            pass

        try:
            fields = [
                SimpleField(name="id",       type=SearchFieldDataType.String, key=True),
                SimpleField(name="nb_id",    type=SearchFieldDataType.String, filterable=True),
                SimpleField(name="source",   type=SearchFieldDataType.String, filterable=True),
                SimpleField(name="position", type=SearchFieldDataType.Int32,  filterable=True),
                SearchableField(name="text",    type=SearchFieldDataType.String),
                SearchableField(name="heading", type=SearchFieldDataType.String),
                SearchField(
                    name="embedding",
                    type=SearchFieldDataType.Collection(SearchFieldDataType.Single),
                    searchable=True,
                    vector_search_dimensions=1536,
                    vector_search_profile_name="hnsw-profile",
                ),
            ]
            vector_search = VectorSearch(
                algorithms=[HnswAlgorithmConfiguration(name="hnsw")],
                profiles=[VectorSearchProfile(name="hnsw-profile", algorithm_configuration_name="hnsw")],
            )
            semantic_config = SemanticConfiguration(
                name="default",
                prioritized_fields=SemanticPrioritizedFields(
                    content_fields=[SemanticField(field_name="text")],
                    keywords_fields=[SemanticField(field_name="heading")],
                ),
            )
            index = SearchIndex(
                name=self._index_name,
                fields=fields,
                vector_search=vector_search,
                semantic_search=SemanticSearch(configurations=[semantic_config]),
            )
            self._index_client.create_index(index)
            logger.info("vector_db: created Azure AI Search index '%s'", self._index_name)
        except Exception as e:
            logger.warning("vector_db: index creation failed: %s", e)

    def add_chunks(self, nb_id: str, chunks: list[TextChunk]) -> None:
        """Upload chunk embeddings to Azure AI Search."""
        if not chunks:
            return
        docs = []
        for i, c in enumerate(chunks):
            if not c.embedding:
                continue
            # Pad or trim to 1536 for the index schema
            vec = list(c.embedding)
            if len(vec) < 1536:
                vec = vec + [0.0] * (1536 - len(vec))
            elif len(vec) > 1536:
                vec = vec[:1536]
            docs.append({
                "id":        f"{nb_id}_{i}_{hash(c.text) & 0xFFFFFFFF}",
                "nb_id":     nb_id,
                "text":      c.text[:32766],   # Azure Search field limit
                "heading":   getattr(c, "heading", "")[:512],
                "source":    getattr(c, "source", "textbook"),
                "position":  i,
                "embedding": vec,
            })
        try:
            self._client.upload_documents(docs)
            logger.info("vector_db: uploaded %d chunks to Azure Search for nb=%s", len(docs), nb_id)
        except Exception as e:
            logger.warning("vector_db: upload failed: %s", e)

    def search(self, nb_id: str, query_vec: Optional[np.ndarray],
               query_text: str, top_k: int = 8) -> list[TextChunk]:
        """Hybrid vector + keyword search filtered to nb_id."""
        from azure.search.documents.models import VectorizedQuery
        try:
            vector_queries = []
            if query_vec is not None:
                vec = list(query_vec.astype(float))
                if len(vec) < 1536:
                    vec = vec + [0.0] * (1536 - len(vec))
                elif len(vec) > 1536:
                    vec = vec[:1536]
                vector_queries.append(VectorizedQuery(
                    vector=vec, k_nearest_neighbors=top_k, fields="embedding"
                ))

            results = self._client.search(
                search_text=query_text or None,
                vector_queries=vector_queries,
                filter=f"nb_id eq '{nb_id}'",
                top=top_k,
                select=["text", "heading", "source", "position"],
            )
            chunks = []
            for r in results:
                c = TextChunk(text=r["text"])
                c.heading = r.get("heading", "")
                c.source  = r.get("source", "textbook")
                chunks.append(c)
            return chunks
        except Exception as e:
            logger.warning("vector_db: Azure Search query failed: %s", e)
            return []

    def delete_nb(self, nb_id: str) -> None:
        """Remove all chunks belonging to nb_id from the index."""
        try:
            results = self._client.search(
                search_text="*",
                filter=f"nb_id eq '{nb_id}'",
                select=["id"],
                top=1000,
            )
            ids = [{"id": r["id"]} for r in results]
            if ids:
                self._client.delete_documents(ids)
                logger.info("vector_db: deleted %d docs for nb=%s", len(ids), nb_id)
        except Exception as e:
            logger.warning("vector_db: delete_nb failed for %s: %s", nb_id, e)


# ═══════════════════════════════════════════════════════════════════════════════
# Numpy in-memory + disk-persisted backend (fallback)
# ═══════════════════════════════════════════════════════════════════════════════

class VectorDB:
    """
    Numpy cosine-similarity vector store.
    Falls back gracefully when Azure AI Search is not configured.
    When Azure AI Search IS configured, acts as a thin wrapper that delegates
    to _AzureSearchVectorDB for persistence and uses local RAM only as cache.
    """

    def __init__(self):
        self._chunks:   list[TextChunk] = []
        self._matrix:   Optional[np.ndarray] = None
        self._azure:    Optional[_AzureSearchVectorDB] = None

        if _search_configured():
            try:
                self._azure = _AzureSearchVectorDB()
            except Exception as e:
                logger.warning("Azure Search init failed — using numpy fallback: %s", e)

    # ── Chunk management ──────────────────────────────────────────────────────

    def add_chunks(self, chunks: list[TextChunk]) -> None:
        """Add chunks to in-memory store and build similarity matrix."""
        self._chunks.extend(chunks)
        self._rebuild_matrix()

    def _rebuild_matrix(self) -> None:
        valid = [c for c in self._chunks if c.embedding]
        if not valid:
            self._matrix = None
            return
        self._matrix = np.array([c.embedding for c in valid], dtype=np.float32)

    @property
    def size(self) -> int:
        return len(self._chunks)

    @property
    def chunks(self) -> list[TextChunk]:
        return self._chunks

    # ── Similarity search (numpy) ─────────────────────────────────────────────

    def search(self, query_vec: np.ndarray, top_k: int = 8) -> list[tuple[float, TextChunk]]:
        """Cosine similarity search. Returns (score, chunk) pairs sorted descending."""
        if self._matrix is None or len(self._chunks) == 0:
            return []
        q = query_vec.astype(np.float32)
        norm = np.linalg.norm(q)
        if norm == 0:
            return []
        q = q / norm
        sims = self._matrix @ q
        idx  = np.argsort(-sims)[:top_k]
        return [(float(sims[i]), self._chunks[i]) for i in idx if sims[i] > 0]

    # ── Azure AI Search integration ───────────────────────────────────────────

    def add_to_azure(self, nb_id: str, chunks: list[TextChunk]) -> None:
        """Upload chunks to Azure AI Search (no-op if not configured)."""
        if self._azure:
            self._azure.add_chunks(nb_id, chunks)

    def search_azure(self, nb_id: str, query_vec: Optional[np.ndarray],
                     query_text: str, top_k: int = 8) -> list[TextChunk]:
        """Hybrid search via Azure AI Search. Returns [] if not configured."""
        if self._azure:
            return self._azure.search(nb_id, query_vec, query_text, top_k)
        return []

    def has_azure(self) -> bool:
        return self._azure is not None

    # ── Disk persistence (numpy fallback) ─────────────────────────────────────

    def save(self, nb_id: str, textbook_hash: str = "") -> None:
        """Persist numpy index to disk."""
        if not self._chunks:
            return
        data = {
            "textbook_hash": textbook_hash,
            "chunks": [
                {
                    "text":      c.text,
                    "heading":   getattr(c, "heading", ""),
                    "source":    getattr(c, "source", "textbook"),
                    "embedding": c.embedding,
                }
                for c in self._chunks if c.embedding
            ],
        }
        path = _INDEX_DIR / f"{nb_id}.json"
        path.write_text(json.dumps(data), encoding="utf-8")
        logger.debug("vector_db: saved %d chunks to disk for nb=%s", len(data["chunks"]), nb_id)

    def load(self, nb_id: str, expected_hash: str = "") -> bool:
        """Load persisted numpy index. Returns True on success."""
        path = _INDEX_DIR / f"{nb_id}.json"
        if not path.exists():
            return False
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if expected_hash and data.get("textbook_hash") != expected_hash:
                logger.info("vector_db: hash mismatch for nb=%s — rebuilding", nb_id)
                return False
            self._chunks = []
            for cd in data.get("chunks", []):
                c = TextChunk(text=cd["text"])
                c.heading   = cd.get("heading", "")
                c.source    = cd.get("source", "textbook")
                c.embedding = cd.get("embedding", [])
                self._chunks.append(c)
            self._rebuild_matrix()
            logger.info("vector_db: loaded %d chunks from disk for nb=%s", len(self._chunks), nb_id)
            return True
        except Exception as e:
            logger.warning("vector_db: load failed for nb=%s: %s", nb_id, e)
            return False

    @staticmethod
    def delete(nb_id: str) -> None:
        """Delete persisted disk index for a notebook. Also cleans Azure Search if configured."""
        # Remove disk file
        path = _INDEX_DIR / f"{nb_id}.json"
        if path.exists():
            path.unlink()
        # Remove Azure AI Search documents for this notebook
        if _search_configured():
            try:
                db = VectorDB()
                if db.has_azure():
                    db._azure.delete_nb(nb_id)
            except Exception as e:
                logger.warning("vector_db.delete: Azure cleanup failed for %s: %s", nb_id, e)
