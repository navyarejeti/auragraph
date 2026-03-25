"""
pipeline/chunker.py
───────────────────
Semantic chunking of textbook text into 400-700 token chunks.
Each chunk stores metadata: chunk_id, text, chapter, section, token_count.

Strategy:
  1. Detect chapter/section headings (numbered or ALL-CAPS patterns)
  2. Split at paragraph boundaries, respecting heading boundaries
  3. Merge short paragraphs until target token range is reached
  4. Never split a paragraph mid-sentence
"""
from __future__ import annotations

import re
import uuid
from dataclasses import dataclass, field
from typing import Optional

# Approximate tokens: 1 token ≈ 4 chars (GPT tokenizer rule of thumb)
CHARS_PER_TOKEN = 4
TARGET_MIN_TOKENS = 400
TARGET_MAX_TOKENS = 700
TARGET_MIN_CHARS  = TARGET_MIN_TOKENS * CHARS_PER_TOKEN   # 1600
TARGET_MAX_CHARS  = TARGET_MAX_TOKENS * CHARS_PER_TOKEN   # 2800


# ── Heading detection ─────────────────────────────────────────────────────────
_CHAPTER_RE = re.compile(
    r'^(?:'
    r'Chapter\s+\d+'                          # Chapter 3
    r'|CHAPTER\s+\d+'                         # CHAPTER 3
    r'|\d+\.\s+[A-Z][A-Za-z\s]{3,50}$'       # 3. Fourier Analysis
    r')',
    re.MULTILINE | re.IGNORECASE
)

_SECTION_RE = re.compile(
    r'^(?:'
    r'\d+\.\d+\s+[A-Za-z]'                   # 3.2 The Transform
    r'|\d+\.\d+\.\d+\s+[A-Za-z]'             # 3.2.1 Definition
    r'|#{1,3}\s+\S'                           # Markdown headings
    r')',
    re.MULTILINE
)


def _estimate_tokens(text: str) -> int:
    return max(1, len(text) // CHARS_PER_TOKEN)


def _detect_heading(line: str) -> tuple[str, str]:
    """Returns (level, heading_text) where level is 'chapter', 'section', or ''."""
    stripped = line.strip()
    if _CHAPTER_RE.match(stripped):
        return 'chapter', stripped
    if _SECTION_RE.match(stripped):
        return 'section', stripped
    return '', ''


@dataclass
class TextChunk:
    chunk_id:    str
    text:        str
    chapter:     str = ""
    section:     str = ""
    token_count: int = 0
    # embedding will be filled in by embedder.py
    embedding:   Optional[list[float]] = field(default=None, repr=False)

    def to_dict(self) -> dict:
        d = {
            "chunk_id":    self.chunk_id,
            "text":        self.text,
            "chapter":     self.chapter,
            "section":     self.section,
            "token_count": self.token_count,
        }
        if self.embedding is not None:
            d["embedding"] = self.embedding
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "TextChunk":
        return cls(
            chunk_id=d["chunk_id"],
            text=d["text"],
            chapter=d.get("chapter", ""),
            section=d.get("section", ""),
            token_count=d.get("token_count", _estimate_tokens(d["text"])),
            embedding=d.get("embedding"),
        )


def chunk_textbook(text: str) -> list[TextChunk]:
    """
    Split textbook text into semantic chunks of 400-700 tokens.

    Steps:
    1. Split into paragraphs on double newlines
    2. Track current chapter/section from headings
    3. Accumulate paragraphs until target token range is hit
    4. Emit chunk, reset buffer
    """
    if not text.strip():
        return []

    paragraphs = re.split(r'\n{2,}', text.strip())
    chunks: list[TextChunk] = []

    current_chapter = ""
    current_section = ""
    buf: list[str] = []
    buf_tokens = 0

    def _emit() -> None:
        nonlocal buf, buf_tokens
        if not buf:
            return
        body = "\n\n".join(buf).strip()
        if len(body) > 50:   # skip trivially short fragments
            chunks.append(TextChunk(
                chunk_id=str(uuid.uuid4()),
                text=body,
                chapter=current_chapter,
                section=current_section,
                token_count=_estimate_tokens(body),
            ))
        buf = []
        buf_tokens = 0

    for para in paragraphs:
        stripped = para.strip()
        if not stripped:
            continue

        # Check if this paragraph is a chapter or section heading
        first_line = stripped.split('\n')[0]
        level, heading_text = _detect_heading(first_line)

        if level == 'chapter':
            # New chapter: emit current buffer, reset both chapter and section
            _emit()
            current_chapter = heading_text
            current_section = ""
            # Don't add pure heading to buffer — it'll be captured in chapter metadata
            continue

        if level == 'section':
            # New section: emit if buffer is already in target range
            if buf_tokens >= TARGET_MIN_TOKENS:
                _emit()
            current_section = heading_text
            continue

        para_tokens = _estimate_tokens(stripped)

        # If adding this paragraph would exceed max, emit first
        if buf_tokens + para_tokens > TARGET_MAX_TOKENS and buf_tokens >= TARGET_MIN_TOKENS:
            _emit()

        buf.append(stripped)
        buf_tokens += para_tokens

        # If we're in the target range and hit a natural paragraph break, emit
        if buf_tokens >= TARGET_MIN_TOKENS:
            _emit()

    # Flush remaining
    _emit()

    # Post-process: merge any chunks that are still too short (< 200 chars)
    # by joining them with the next chunk
    merged: list[TextChunk] = []
    for c in chunks:
        if merged and len(merged[-1].text) < 800:
            prev = merged[-1]
            combined = prev.text + "\n\n" + c.text
            merged[-1] = TextChunk(
                chunk_id=prev.chunk_id,
                text=combined,
                chapter=prev.chapter or c.chapter,
                section=prev.section or c.section,
                token_count=_estimate_tokens(combined),
            )
        else:
            merged.append(c)

    return merged
