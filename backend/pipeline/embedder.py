"""
pipeline/embedder.py — Azure OpenAI Embeddings + TF-IDF fallback
─────────────────────────────────────────────────────────────────
Generates dense vector embeddings for textbook chunks.

Primary:  Azure OpenAI text-embedding-3-large  (1536-dim)
          requires AZURE_OPENAI_ENDPOINT + AZURE_OPENAI_API_KEY +
                   AZURE_EMBEDDING_DEPLOYMENT
Fallback: TF-IDF sparse vectors normalised to unit length (pure numpy)
"""
from __future__ import annotations

import logging
import math
import os
import re
from typing import Optional

import numpy as np

from pipeline.chunker import TextChunk

logger = logging.getLogger(__name__)

EMBEDDING_DIM_AZURE = 1536
EMBEDDING_DIM_TFIDF = 1024

_STOP = frozenset(
    "a an the is are was were be been being have has had do does did will would "
    "could should may might shall can cannot must to of in on at by for with "
    "from that this these those it its we our they their he she you your "
    "and or but not if so as also both just only even all any some such "
    "i into about over after before under between through during while "
    "because since although though because which when where how what who".split()
)


def _tokenise(text: str) -> list[str]:
    return [w for w in re.findall(r'\b[a-zA-Z]{2,}\b', text.lower()) if w not in _STOP]


# ── Azure OpenAI Embeddings ──────────────────────────────────────────────────

def _azure_embedding_configured() -> bool:
    endpoint   = os.environ.get("AZURE_OPENAI_ENDPOINT", "")
    api_key    = os.environ.get("AZURE_OPENAI_API_KEY", "")
    deployment = os.environ.get("AZURE_EMBEDDING_DEPLOYMENT", "").strip()
    return bool(
        endpoint and api_key and deployment
        and "mock"        not in endpoint.lower()
        and "placeholder" not in endpoint.lower()
        and "placeholder" not in api_key.lower()
    )


def _get_azure_client():
    """Build an openai.AzureOpenAI client for embeddings."""
    try:
        import openai
        return openai.AzureOpenAI(
            azure_endpoint=os.environ.get("AZURE_OPENAI_ENDPOINT", "").rstrip("/"),
            api_key=os.environ.get("AZURE_OPENAI_API_KEY", ""),
            api_version=os.environ.get("AZURE_OPENAI_API_VERSION", "2024-02-01"),
        )
    except Exception as e:
        logger.warning("Azure embedding client init failed: %s", e)
        return None


def _embed_azure(texts: list[str], client) -> Optional[np.ndarray]:
    """
    Call Azure OpenAI text-embedding-3-large for a batch of texts.
    Returns (N, 1536) float32 L2-normalised array, or None on failure.
    """
    deployment = os.environ.get("AZURE_EMBEDDING_DEPLOYMENT", "").strip()
    if not deployment:
        return None
    try:
        all_vecs = []
        for i in range(0, len(texts), 16):   # Azure max batch = 16
            resp = client.embeddings.create(model=deployment, input=texts[i:i+16])
            all_vecs.extend(item.embedding for item in resp.data)
        arr = np.array(all_vecs, dtype=np.float32)
        norms = np.linalg.norm(arr, axis=1, keepdims=True)
        norms = np.where(norms == 0, 1.0, norms)
        return arr / norms
    except Exception as e:
        logger.warning("Azure embedding call failed: %s", e)
        return None


# ── TF-IDF fallback ──────────────────────────────────────────────────────────

class _TFIDFVectoriser:
    def __init__(self):
        self.vocab: dict[str, int] = {}
        self.idf: np.ndarray = np.array([])

    def fit(self, corpus: list[str]) -> None:
        df: dict[str, int] = {}
        tokenised = [_tokenise(t) for t in corpus]
        N = len(corpus)
        for tokens in tokenised:
            for term in set(tokens):
                df[term] = df.get(term, 0) + 1
        top = sorted(df.items(), key=lambda x: -x[1])[:EMBEDDING_DIM_TFIDF]
        self.vocab = {term: idx for idx, (term, _) in enumerate(top)}
        dim = len(self.vocab)
        idf_arr = np.ones(dim, dtype=np.float32)
        for term, idx in self.vocab.items():
            idf_arr[idx] = math.log((N + 1) / (df[term] + 1)) + 1.0
        self.idf = idf_arr

    def transform(self, texts: list[str]) -> np.ndarray:
        dim = len(self.vocab)
        if dim == 0:
            return np.zeros((len(texts), 1), dtype=np.float32)
        mat = np.zeros((len(texts), dim), dtype=np.float32)
        for row, text in enumerate(texts):
            tokens = _tokenise(text)
            tf: dict[str, int] = {}
            for t in tokens:
                tf[t] = tf.get(t, 0) + 1
            total = max(len(tokens), 1)
            for term, count in tf.items():
                if term in self.vocab:
                    col = self.vocab[term]
                    mat[row, col] = (count / total) * self.idf[col]
        norms = np.linalg.norm(mat, axis=1, keepdims=True)
        norms = np.where(norms == 0, 1.0, norms)
        return mat / norms


# ── Public API ────────────────────────────────────────────────────────────────

class Embedder:
    """
    Embed TextChunks in-place.
    Azure OpenAI text-embedding-3-large → TF-IDF fallback.
    """

    def __init__(self):
        self._azure_client = _get_azure_client() if _azure_embedding_configured() else None
        self._tfidf: Optional[_TFIDFVectoriser] = None
        self._dim: int = 0

    def embed_chunks(self, chunks: list[TextChunk]) -> str:
        """Embed all chunks in-place. Returns 'azure' or 'tfidf'."""
        if not chunks:
            return "none"
        texts = [c.text for c in chunks]

        if self._azure_client is not None:
            vecs = _embed_azure(texts, self._azure_client)
            if vecs is not None:
                self._dim = vecs.shape[1]
                for chunk, vec in zip(chunks, vecs):
                    chunk.embedding = vec.tolist()
                logger.info("Embedded %d chunks via Azure (dim=%d)", len(chunks), self._dim)
                return "azure"

        logger.info("Azure embedding unavailable — using TF-IDF fallback")
        v = _TFIDFVectoriser()
        v.fit(texts)
        vecs = v.transform(texts)
        self._tfidf = v
        self._dim   = vecs.shape[1]
        for chunk, vec in zip(chunks, vecs):
            chunk.embedding = vec.tolist()
        logger.info("Embedded %d chunks via TF-IDF (dim=%d)", len(chunks), self._dim)
        return "tfidf"

    def embed_query(self, query: str) -> Optional[np.ndarray]:
        """Embed a single query. Returns 1-D numpy array or None."""
        if self._azure_client is not None:
            vecs = _embed_azure([query], self._azure_client)
            if vecs is not None:
                return vecs[0]
        if self._tfidf is not None:
            return self._tfidf.transform([query])[0]
        return None

    def rebuild_from_chunks(self, chunks: list) -> None:
        """Rebuild TF-IDF vectoriser from previously persisted chunks (no Azure needed)."""
        if self._azure_client is not None:
            return   # Azure always reconstructs from env vars
        if not chunks:
            return
        texts = [c.text for c in chunks if hasattr(c, "text")]
        if not texts:
            return
        v = _TFIDFVectoriser()
        v.fit(texts)
        self._tfidf = v
        logger.info("Embedder.rebuild_from_chunks: TF-IDF refitted on %d chunks", len(texts))

    @property
    def dim(self) -> int:
        return self._dim
