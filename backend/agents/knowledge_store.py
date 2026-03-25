"""
agents/knowledge_store.py  — AuraGraph Knowledge Store
═══════════════════════════════════════════════════════
Stores ALL raw source material (slides + textbook) per notebook in JSON.
Provides keyword-based chunk retrieval so every agent has full context.

Architecture
────────────
Upload phase:
  store_source_chunks(nb_id, slide_chunks, textbook_chunks)
  → persists every chunk verbatim, tagged with source + position

Retrieval phase:
  retrieve_relevant_chunks(nb_id, query, top_k) → list[Chunk]
  → returns the most relevant chunks from stored material
  → used by: note generation, doubt answering, mutation

Note-page index:
  store_note_pages(nb_id, pages)       → saves list of page strings
  get_note_page(nb_id, page_idx)       → returns one page string
  get_all_note_pages(nb_id)            → returns all pages
  update_note_page(nb_id, idx, text)   → replaces one page (mutation)

No external dependencies — uses only Python stdlib + existing json storage.
Retrieval uses Jaccard keyword overlap (fast, deterministic, no embeddings).
"""

import json
import os
import re
import threading
import uuid
from datetime import datetime
from pathlib import Path
from typing import Optional

STORE_DIR = Path(__file__).parent.parent / "knowledge_store"
STORE_DIR.mkdir(exist_ok=True)

# Per-notebook write locks — prevents concurrent uploads corrupting the JSON file
_STORE_LOCKS: dict[str, threading.Lock] = {}
_STORE_LOCKS_LOCK = threading.Lock()


def _get_store_lock(nb_id: str) -> threading.Lock:
    with _STORE_LOCKS_LOCK:
        if nb_id not in _STORE_LOCKS:
            _STORE_LOCKS[nb_id] = threading.Lock()
        return _STORE_LOCKS[nb_id]


# ── Stop-words for keyword extraction ────────────────────────────────────────
_STOP = frozenset(
    "a an the is are was were be been being have has had do does did will would "
    "could should may might shall can cannot must to of in on at by for with "
    "from that this these those it its we our they their he she you your "
    "and or but not if so as also both just only even all any some such "
    "i into about over after before under between through during while "
    "because since although though because which when where how what who".split()
)


def _keywords(text: str) -> set[str]:
    """Extract meaningful lowercase keywords from text."""
    words = re.findall(r'\b[a-zA-Z]{3,}\b', text.lower())
    return {w for w in words if w not in _STOP}


def _jaccard(a: set, b: set) -> float:
    if not a or not b:
        return 0.0
    inter = len(a & b)
    union = len(a | b)
    return inter / union if union else 0.0


# ── Per-notebook storage file helpers ─────────────────────────────────────────
def _store_path(nb_id: str) -> Path:
    return STORE_DIR / f"{nb_id}.json"


def _load_store(nb_id: str) -> dict:
    p = _store_path(nb_id)
    if not p.exists():
        return {"chunks": [], "note_pages": [], "stored_at": None}
    try:
        return json.loads(p.read_text(encoding='utf-8'))
    except Exception:
        return {"chunks": [], "note_pages": [], "stored_at": None}


def _save_store(nb_id: str, store: dict):
    # Caller must hold _get_store_lock(nb_id) before calling this.
    _store_path(nb_id).write_text(json.dumps(store, indent=2, ensure_ascii=False), encoding='utf-8')


# ── Public API ────────────────────────────────────────────────────────────────

# ── Storage hygiene ────────────────────────────────────────────────────────────
# Limit per-notebook knowledge store to 20 MB (raw source text).
# Beyond this the Jaccard retrieval gets slow and LLM context windows overflow anyway.
_MAX_STORE_BYTES = int(os.environ.get("MAX_KS_MB", "20")) * 1024 * 1024

import os as _os  # noqa: F811


def cleanup_orphaned_stores(active_nb_ids: set) -> int:
    """Delete knowledge store JSON files that belong to deleted notebooks.
    Call this periodically (e.g. from a background task or on notebook delete).
    Returns the count of files removed."""
    removed = 0
    for p in STORE_DIR.glob("*.json"):
        if p.stem not in active_nb_ids:
            try:
                p.unlink()
                removed += 1
            except OSError:
                pass
    return removed


class Chunk:
    """A single stored piece of source material."""
    __slots__ = ("chunk_id", "source", "position", "heading", "text", "keywords")

    def __init__(self, chunk_id: str, source: str, position: int,
                 heading: str, text: str):
        self.chunk_id  = chunk_id
        self.source    = source      # "slides" | "textbook"
        self.position  = position    # 0-indexed order
        self.heading   = heading     # slide title or detected heading
        self.text      = text        # full verbatim text
        self.keywords  = _keywords(heading + " " + text)

    def to_dict(self) -> dict:
        return {
            "chunk_id": self.chunk_id,
            "source":   self.source,
            "position": self.position,
            "heading":  self.heading,
            "text":     self.text,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Chunk":
        return cls(
            chunk_id=d["chunk_id"],
            source=d["source"],
            position=d["position"],
            heading=d.get("heading", ""),
            text=d["text"],
        )


def store_source_chunks(
    nb_id: str,
    slide_chunks: list[str],
    textbook_chunks: list[str],
    textbook_hash: str = "",
) -> dict:
    """
    Store ALL slide and textbook chunks verbatim for a notebook.
    Each call REPLACES existing chunks (re-upload scenario).
    FIX F3: textbook_hash is stored so VectorDB.load() can detect staleness.
    Returns summary: {"slides": N, "textbook": M, "total": N+M}
    """
    all_chunks = []

    for i, text in enumerate(slide_chunks):
        if not text.strip():
            continue
        # Extract heading from first line if it's a slide marker
        heading = ""
        lines = text.strip().split("\n")
        if lines and lines[0].startswith("---"):
            m = re.match(r'---\s*Slide\s+\d+:\s*(.*?)\s*---', lines[0])
            heading = m.group(1).strip() if m else lines[0].strip("- ").strip()
        elif lines:
            heading = lines[0].strip()[:80]

        all_chunks.append(Chunk(
            chunk_id=str(uuid.uuid4()),
            source="slides",
            position=i,
            heading=heading,
            text=text.strip(),
        ).to_dict())

    for i, text in enumerate(textbook_chunks):
        if not text.strip():
            continue
        # Use first sentence as heading for textbook chunks
        heading = re.split(r'[.!?]', text.strip())[0][:80].strip()
        all_chunks.append(Chunk(
            chunk_id=str(uuid.uuid4()),
            source="textbook",
            position=i,
            heading=heading,
            text=text.strip(),
        ).to_dict())

    # Enforce per-notebook size cap to prevent unbounded disk growth
    total_chars = sum(len(c["text"]) for c in all_chunks)
    if total_chars > _MAX_STORE_BYTES:
        import logging as _log
        _log.getLogger("auragraph").warning(
            "Knowledge store for %s exceeds %d MB limit (%d chars) — "
            "truncating to first %d chunks.",
            nb_id, _MAX_STORE_BYTES // 1024 // 1024, total_chars, len(all_chunks)
        )
        # Keep as many chunks as fit within the budget
        kept, budget = [], _MAX_STORE_BYTES
        for chunk in all_chunks:
            if budget - len(chunk["text"]) < 0:
                break
            kept.append(chunk)
            budget -= len(chunk["text"])
        all_chunks = kept

    with _get_store_lock(nb_id):
        store = _load_store(nb_id)
        store["chunks"]        = all_chunks
        store["stored_at"]     = datetime.now().isoformat()
        store["textbook_hash"] = textbook_hash   # FIX F3
        # Preserve existing note pages
        _save_store(nb_id, store)

    n_slides = sum(1 for c in all_chunks if c["source"] == "slides")
    n_text   = sum(1 for c in all_chunks if c["source"] == "textbook")
    return {"slides": n_slides, "textbook": n_text, "total": len(all_chunks)}


def retrieve_relevant_chunks(
    nb_id: str,
    query: str,
    top_k: int = 8,
    source_filter: Optional[str] = None,   # "slides" | "textbook" | None
) -> list[dict]:
    """
    Return the top_k most relevant chunks for a query using Jaccard keyword overlap.
    Each returned dict has: chunk_id, source, position, heading, text, score.

    Used by: note generation, doubt answering, mutation.
    """
    store = _load_store(nb_id)
    if not store["chunks"]:
        return []

    query_kw = _keywords(query)
    if not query_kw:
        # No keywords — return first top_k chunks of each source
        chunks = store["chunks"]
        if source_filter:
            chunks = [c for c in chunks if c["source"] == source_filter]
        return [dict(c, score=0.0) for c in chunks[:top_k]]

    scored = []
    for c in store["chunks"]:
        if source_filter and c["source"] != source_filter:
            continue
        chunk_kw = _keywords(c.get("heading", "") + " " + c["text"])
        score = _jaccard(query_kw, chunk_kw)
        if score > 0:
            scored.append((score, c))

    scored.sort(key=lambda x: -x[0])
    return [dict(c, score=round(s, 4)) for s, c in scored[:top_k]]


def build_quiz_context(nb_id: str, concept_name: str,
                       slide_top_k: int = 12, textbook_top_k: int = 6,
                       slide_chars: int = 5000, textbook_chars: int = 3000) -> str:
    """
    Build sanitized context for quiz/exam generation.

    Fetches slide and textbook chunks separately (same volumes as the old
    per-endpoint approach) so quiz questions stay grounded in both sources
    at full depth. Then runs garble detection and prepends a correction
    instruction when OCR noise is found.

    Responsible AI: raw chunks may contain OCR artefacts. We detect
    potentially garbled tokens and prepend an explicit instruction so the
    exam LLM corrects any noise rather than copying it into questions/options.
    """
    import re as _re

    slide_hits    = retrieve_relevant_chunks(nb_id, concept_name, top_k=slide_top_k,    source_filter="slides")
    textbook_hits = retrieve_relevant_chunks(nb_id, concept_name, top_k=textbook_top_k, source_filter="textbook")

    # Format each source with its own char budget
    def _fmt(chunks: list, char_limit: int) -> str:
        parts, budget = [], char_limit
        for c in chunks:
            text = c.get("text", "")
            if budget <= 0:
                break
            parts.append(text[:budget])
            budget -= len(text)
        return "\n\n".join(parts).strip()

    sc = _fmt(slide_hits,    slide_chars)
    tc = _fmt(textbook_hits, textbook_chars)

    if sc and tc:
        context = f"[FROM SLIDES]\n{sc}\n\n[FROM TEXTBOOK]\n{tc}"
    else:
        context = sc or tc

    if not context:
        return "(no course material available for this concept)"

    # Garble detection using vowel/consonant heuristic
    _VOWELS = set('aeiouAEIOUyY')
    _CONSONANT_RUN = _re.compile(r'[bcdfghjklmnpqrstvwxzBCDFGHJKLMNPQRSTVWXZ]{5,}')
    _DIGIT_IN_ALPHA = _re.compile(r'(?:[a-zA-Z]+[0-9]+[a-zA-Z]*|[a-zA-Z]*[0-9]+[a-zA-Z]+)')

    def _likely_garbled(w: str) -> bool:
        if not any(c.isalpha() for c in w):
            return False
        if len(w) < 4:
            return False
        # ALL-CAPS short words are acronyms (LSTM, HTTP, DNA) — not garble
        if w.isupper() and len(w) <= 8:
            return False
        if any(c.isdigit() for c in w) and _DIGIT_IN_ALPHA.fullmatch(w):
            return True
        alpha = ''.join(c for c in w if c.isalpha())
        if len(alpha) < 4:
            return False
        v = sum(1 for c in alpha if c in _VOWELS)
        if v == 0 and len(alpha) >= 5:
            return True
        if v / len(alpha) < 0.10 and len(alpha) >= 8:
            return True
        if len(alpha) >= 6 and _CONSONANT_RUN.search(alpha):
            return True
        return False

    words = context.split()
    garble_count = sum(1 for w in words if _likely_garbled(w))
    garble_ratio = garble_count / len(words) if words else 0

    if garble_ratio >= 0.03:
        header = (
            "⚠️ IMPORTANT — COURSE MATERIAL QUALITY NOTE:\n"
            "Some source material below may contain OCR artefacts from blurry or "
            "low-resolution image scans (e.g. 'hyptvnse' instead of 'hypotenuse'). "
            "You MUST correct any such garble using your domain knowledge. "
            "NEVER copy a garbled word into a question stem, option, or explanation. "
            "Always use the correct academic term.\n\n"
        )
        return header + context

    return context


def get_all_chunks(nb_id: str, source_filter: Optional[str] = None) -> list[dict]:
    """Return all stored chunks, optionally filtered by source."""
    store = _load_store(nb_id)
    chunks = store["chunks"]
    if source_filter:
        chunks = [c for c in chunks if c["source"] == source_filter]
    return chunks


def get_chunk_stats(nb_id: str) -> dict:
    """Return storage statistics for a notebook."""
    store = _load_store(nb_id)
    chunks = store["chunks"]
    n_slides  = sum(1 for c in chunks if c["source"] == "slides")
    n_text    = sum(1 for c in chunks if c["source"] == "textbook")
    total_chars = sum(len(c["text"]) for c in chunks)
    return {
        "total_chunks": len(chunks),
        "slide_chunks": n_slides,
        "textbook_chunks": n_text,
        "total_chars": total_chars,
        "stored_at": store.get("stored_at"),
    }


# ── Note-page index ───────────────────────────────────────────────────────────

def store_note_pages(nb_id: str, pages: list[str]):
    """
    Store the generated note split into pages.
    pages[i] = the full markdown text of page i.
    """
    with _get_store_lock(nb_id):
        store = _load_store(nb_id)
        store["note_pages"] = pages
        _save_store(nb_id, store)


def get_note_page(nb_id: str, page_idx: int) -> Optional[str]:
    """Return the text of a single note page by index."""
    store = _load_store(nb_id)
    pages = store.get("note_pages", [])
    if 0 <= page_idx < len(pages):
        return pages[page_idx]
    return None


def get_all_note_pages(nb_id: str) -> list[str]:
    """Return all stored note pages."""
    return _load_store(nb_id).get("note_pages", [])


def update_note_page(nb_id: str, page_idx: int, new_text: str) -> bool:
    """
    Replace a single note page with new_text (used after mutation).
    Returns True on success, False if page_idx is out of range.
    """
    with _get_store_lock(nb_id):
        store = _load_store(nb_id)
        pages = store.get("note_pages", [])
        if 0 <= page_idx < len(pages):
            pages[page_idx] = new_text
            store["note_pages"] = pages
            _save_store(nb_id, store)
            return True
    return False


def delete_notebook_store(nb_id: str):
    """Delete all stored content for a notebook (called on notebook delete)."""
    p = _store_path(nb_id)
    if p.exists():
        p.unlink()
