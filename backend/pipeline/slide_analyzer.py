# -*- coding: utf-8 -*-
"""
pipeline/slide_analyzer.py
--------------------------
Step 4 - Slide Understanding.

Sends the full slide text to GPT-4o once and gets back a structured list of
topics in lecture order.  Each topic has:
  - topic: the concept name (becomes a ## heading in the notes)
  - slide_text: the verbatim slide content for this topic
  - key_points: list of key facts extracted from the slide

This structured output drives the entire downstream retrieval and generation:
  - One retrieval query per topic  (Step 5)
  - One note generation call per topic  (Step 6)

LLM call budget: exactly 1 call for the entire slide deck.

Fallback: if the LLM call fails, a deterministic regex parser extracts
topics from slide boundary markers (--- Slide N: Title ---).
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import re
from dataclasses import dataclass, field
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass
class SlideTopic:
    """One lecture topic extracted from the slide deck."""
    topic:      str
    slide_text: str              # verbatim slide content for this topic
    key_points: list[str] = field(default_factory=list)


# -- Prompt --------------------------------------------------------------------

_SLIDE_ANALYSIS_SYSTEM = """\
You are an expert academic content analyst.
Your job is to extract the structured lecture outline from raw slide text.

Source text quality - YOU are the ground truth:
The input may come from OCR of handwritten notes or scanned slides. The source text
tells you the TOPIC and rough content; your own knowledge determines what is correct.

Before writing any key_point, verify it against what you know:
  - Formulas    - verify every operator, sign, Jacobian, fraction, exponent.
  - Definitions - check for missing conditions or qualifiers.
  - Claims      - check direction, scope, and completeness.

If the source has an error, write the CORRECT statement in key_points - not the
erroneous source version. OCR math is often garbled ("E[X] = mu", "integral from
0 to T", garbled fractions) - reconstruct the correct expression from context.
"""

_SLIDE_ANALYSIS_USER = """\
Below is the full text of a lecture slide deck.
Extract the lecture topics IN SLIDE ORDER.

IMPORTANT: The text may contain multiple files separated by markers like:
  ============================================================
  === FILE: filename.pdf ===
  ============================================================
Each file is a separate set of slides. You MUST extract topics from ALL files.
Do NOT stop after the first file. Every file's content must be represented in your output.

For each topic output:
  - "topic": short concept name (3-6 words max, suitable as a section heading)
  - "key_points": list of ALL key facts, formulas, definitions, algorithms, and properties
    from the slides for this topic. Do NOT cap or summarise - include every distinct
    concept so the note generator can cover the slides completely.
  - "slide_text": the VERBATIM slide text for this topic, including the EXACT
    --- Page N --- or --- Slide N --- marker line(s). These marker lines MUST be
    preserved character-for-character. Never remove or paraphrase them.

Rules:
  1. Follow slide order exactly - do NOT reorder topics.
  2. ONE TOPIC PER SLIDE — this is the most important rule.
     Count every --- Slide N --- or --- Page N --- marker in the input.
     Each such marker MUST produce its own separate topic entry.
     The ONLY exception: two consecutive slides that are an explicit
     continuation (e.g. "Definition (cont.)" or "Proof — Part 2 of 2").
     A new formula, a new definition, a new algorithm, a new theorem, a new
     sub-heading, or ANY change in subject = a NEW topic entry.
     If you are unsure: make separate entries. NEVER fold content into a previous topic.
     If there are 4 slide markers → output at least 4 topic entries.
     If there are 10 slide markers → output at least 10 topic entries.
  3. Ignore ONLY these metadata slide types: cover page, title slide, table of
     contents, references / bibliography, agenda, outline, "thank you", author page.
     EVERYTHING else — including introductory concept slides, motivation slides,
     definition slides, short slides — MUST become its own topic entry.
  4. Each topic must correspond to actual teaching content from the slides.
  5. EVERY topic MUST have non-empty "slide_text" containing the verbatim slide
     content for that topic.  If a topic genuinely has no slide text, omit it
     entirely rather than returning an entry with an empty slide_text field.
  6. key_points must represent the CORRECT mathematical or conceptual statement.
     If the slide text has OCR artifacts or garbled math, interpret using your own
     knowledge - state the formula/concept correctly, not as the OCR garbled it.
  7. FILE COVERAGE (critical): If multiple files are present, ensure at least one
     topic per file is present in your output. Never silently drop an entire file.
  8. PAGE COVERAGE (critical): Count the --- Page N --- and --- Slide N --- markers
     in the input. Every such page that is not pure metadata MUST appear in at least
     one topic's slide_text WITH its marker line preserved.
  9. EXERCISE AND EXAMPLE LINES (critical): Lines starting with "Exercise N." or
     "Example N." are TEACHING CONTENT — they show students what to practice and
     what the concept looks like in application. They MUST be included verbatim in
     slide_text and listed in key_points. Never treat them as optional or student work.
  10. Output ONLY valid JSON in this exact format - a JSON object with a "topics" key containing the array.
     No preamble, no markdown fences, no extra keys.

Required output format:
{"topics": [
  {
    "topic": "Fourier Transform",
    "key_points": [
      "converts time domain to frequency domain",
      "F(omega) = integral of f(t) times complex exponential"
    ],
    "slide_text": "--- Slide 3: Fourier Transform ---\\nContent here..."
  }
]}

SLIDE TEXT:
{slides}
"""


# -- LLM Helpers (Azure via openai SDK + Groq fallback) ------------------------

import asyncio as _asyncio


def _azure_ok() -> bool:
    ep  = os.environ.get("AZURE_OPENAI_ENDPOINT", "")
    key = os.environ.get("AZURE_OPENAI_API_KEY",  "")
    # FIX (round 4): mirror main.py - also reject "placeholder" endpoints/keys
    return (
        bool(ep) and bool(key)
        and "mock"        not in ep.lower()
        and "placeholder" not in ep.lower()
        and "placeholder" not in key.lower()
    )


def _groq_ok() -> bool:
    key = os.environ.get("GROQ_API_KEY", "")
    return key not in ("", "your-groq-api-key-here")


def _parse_topics_json(content: str) -> Optional[list[dict]]:
    """Parse JSON content into a list of topic dicts, unwrapping common wrappers.

    Handles:
      - bare JSON arrays
      - objects with well-known keys (topics, lecture_topics, outline, ...)
      - objects with any unknown key whose value is a list  (catch-all)
      - malformed/truncated output - scans for the first [ ... ] array fragment
    """
    # Strip markdown fences if present
    content = re.sub(r'^```[a-z]*\s*', '', content.strip(), flags=re.MULTILINE)
    content = re.sub(r'```\s*$', '', content.strip(), flags=re.MULTILINE)
    content = content.strip()

    try:
        parsed = json.loads(content)
    except json.JSONDecodeError:
        # Try to extract the first JSON array embedded anywhere in the text
        m = re.search(r'\[', content)
        if m:
            try:
                # json.JSONDecoder.raw_decode finds the largest valid object starting at pos
                decoder = json.JSONDecoder()
                parsed, _ = decoder.raw_decode(content, m.start())
            except json.JSONDecodeError:
                logger.warning("slide_analyzer: JSON parse failed; raw content head: %r", content[:300])
                return None
        else:
            logger.warning("slide_analyzer: no JSON array found; raw content head: %r", content[:300])
            return None

    if isinstance(parsed, list):
        return parsed
    if isinstance(parsed, dict):
        # Well-known wrapper keys first
        for key in ("topics", "lecture_topics", "outline", "data", "result", "items"):
            if key in parsed and isinstance(parsed[key], list):
                return parsed[key]
        # Catch-all: return the first non-empty list value found
        for val in parsed.values():
            if isinstance(val, list) and val:
                return val
    return None


async def _call_azure_json(slides_text: str) -> Optional[list[dict]]:
    """
    Slide analysis via Azure OpenAI - true async httpx.
    FIX C1: was asyncio.to_thread(AzureOpenAI(...)), now httpx.AsyncClient.
    Includes one 429 retry with Retry-After back-off.
    """
    if not _azure_ok():
        return None
    try:
        import httpx
        endpoint   = os.environ.get("AZURE_OPENAI_ENDPOINT", "").rstrip("/")
        api_key    = os.environ.get("AZURE_OPENAI_API_KEY",  "")
        api_ver    = os.environ.get("AZURE_OPENAI_API_VERSION", "2024-10-21")
        deployment = os.environ.get("AZURE_OPENAI_DEPLOYMENT", "gpt-4o")
        url = f"{endpoint}/openai/deployments/{deployment}/chat/completions?api-version={api_ver}"
        user_content = _SLIDE_ANALYSIS_USER.replace("{slides}", slides_text)  # no inner truncation - chunking already limits size
        payload = {
            "messages": [
                {"role": "system", "content": _SLIDE_ANALYSIS_SYSTEM},
                {"role": "user",   "content": user_content},
            ],
            "max_tokens":     16000,
            "temperature":    0.1,
            "response_format": {"type": "json_object"},  # forces valid JSON object output
        }
        headers = {"api-key": api_key, "Content-Type": "application/json"}
        for attempt in range(2):
            async with httpx.AsyncClient(timeout=120.0) as client:
                resp = await client.post(url, json=payload, headers=headers)
            if resp.status_code == 429 and attempt == 0:
                wait = int(resp.headers.get("Retry-After", "10"))
                logger.warning("slide_analyzer Azure 429 - retrying in %d s", wait)
                await _asyncio.sleep(wait)
                continue
            resp.raise_for_status()
            choice = resp.json()["choices"][0]
            if choice.get("finish_reason") == "length":
                # JSON output was truncated — parsing it would silently drop the last N topics.
                # Return None so Groq / deterministic fallback handles this chunk instead.
                logger.warning(
                    "slide_analyzer Azure: response truncated (finish_reason=length) — "
                    "falling back to Groq / deterministic parser for this chunk"
                )
                return None
            raw = choice["message"]["content"].strip()
            logger.info("slide_analyzer Azure raw response (first 300 chars): %r", raw[:300])
            topics = _parse_topics_json(raw)
            logger.info("slide_analyzer Azure parsed %s topics", len(topics) if topics else 0)
            return topics
    except Exception as e:
        logger.warning("slide_analyzer Azure call failed: %s", e)
    return None


async def _call_groq_json(slides_text: str) -> Optional[list[dict]]:
    """
    Slide analysis via Groq - true async httpx.
    FIX C1: was asyncio.to_thread(OpenAI(...)), now httpx.AsyncClient.
    Includes one 429 retry with Retry-After back-off.
    """
    if not _groq_ok():
        return None
    try:
        import httpx
        api_key = os.environ.get("GROQ_API_KEY", "")
        model   = os.environ.get("GROQ_MODEL", "llama-3.3-70b-versatile")
        user_prompt = (
            # no inner truncation - chunking already limits size
            _SLIDE_ANALYSIS_USER.replace("{slides}", slides_text)
            + "\n\nIMPORTANT: Output ONLY valid JSON with a \"topics\" key. No markdown fences. No explanation."
        )
        payload = {
            "model":       model,
            "messages":    [
                {"role": "system", "content": _SLIDE_ANALYSIS_SYSTEM},
                {"role": "user",   "content": user_prompt},
            ],
            "max_tokens":  32_000,   # llama-3.3-70b-versatile supports 32k; 8192 caused truncated JSON on large chunks
            "temperature": 0.1,
        }
        headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
        for attempt in range(2):
            async with httpx.AsyncClient(timeout=120.0) as client:
                resp = await client.post(
                    "https://api.groq.com/openai/v1/chat/completions",
                    json=payload, headers=headers,
                )
            if resp.status_code == 429 and attempt == 0:
                wait = int(resp.headers.get("Retry-After", "6"))
                logger.warning("slide_analyzer Groq 429 - retrying in %d s", wait)
                await _asyncio.sleep(wait)
                continue
            resp.raise_for_status()
            choice = resp.json()["choices"][0]
            if choice.get("finish_reason") == "length":
                # JSON truncated — drop to deterministic fallback rather than losing topics.
                logger.warning(
                    "slide_analyzer Groq: response truncated (finish_reason=length) — "
                    "falling back to deterministic parser for this chunk"
                )
                return None
            raw = choice["message"]["content"].strip()
            logger.info("slide_analyzer Groq raw response (first 300 chars): %r", raw[:300])
            topics = _parse_topics_json(raw)
            logger.info("slide_analyzer Groq parsed %s topics", len(topics) if topics else 0)
            return topics
    except Exception as e:
        logger.warning("slide_analyzer Groq call failed: %s", e)
    return None


# -- Deterministic Fallback ----------------------------------------------------

# Match --- Slide N --- (PPTX), --- Page N --- (PDF), and --- Page: name --- (image OCR)
_SLIDE_BOUNDARY = re.compile(
    r'^---\s*(?:Slide|Page)\s+(\d+)(?::\s*(.*?))?\s*---\s*$'
    r'|^---\s*Page:\s*([^\-].*?)\s*---\s*$',
    re.MULTILINE,
)


def _deterministic_parse(slides_text: str) -> list[SlideTopic]:
    """
    Parse slide topics from boundary markers without an LLM.
    Groups slides by detected title; skips metadata/empty slides.
    Used as fallback when Azure is unavailable.
    """
    parts = re.split(
        r'(?=^---\s*(?:Slide\s+\d+|Page(?:\s+\d+|:)))',
        slides_text, flags=re.MULTILINE
    )
    topics: list[SlideTopic] = []

    _META = re.compile(
        r'\b(table of contents|references|bibliography|acknowledgement|'
        r'thank you|agenda|outline|questions|q&a|title page|cover page|'
        r'course overview|learning objectives|about this course|welcome to|'
        r'course introduction|lecture overview|recap|revision)\b'
        r'|^(cover|title|contents|intro|introduction)$',
        re.I,
    )

    for part in parts:
        part = part.strip()
        if not part:
            continue

        m = _SLIDE_BOUNDARY.match(part.split('\n')[0])
        if not m:
            continue

        body = part[m.end():].strip()

        if m.group(1):  # numbered format: --- Slide N --- / --- Page N ---
            title = (m.group(2) or '').strip()
            num   = m.group(1)
            # Use inline title if present; otherwise extract from body content.
            # "Slide N" is only the final fallback when the body yields nothing.
            display_title = title or _derive_topic_name_from_body(body, f"Slide {num}")
        else:           # image OCR format: --- Page: filename ---
            title = (m.group(3) or '').strip()
            display_title = title or "Image Notes"
            num   = None

        # Skip metadata / empty slides
        if not body and not title:
            continue
        if title and _META.search(title):
            continue
        if not body and len(title) < 3:
            continue
        # Skip only truly empty author/date/institution slides — body is very
        # short AND has no colons, bullets, or equations AND has ≤6 words.
        # Anything with actual sentences or structured content is kept.
        # IMPORTANT: never skip a page whose body is a [Figure: ...] annotation.
        # Image-only slides get annotated with [Figure: description] before the
        # analyzer runs. Skipping such a page silently drops the image from the
        # entire pipeline — it would never enter any topic's slide_text.
        if body and len(body) < 60 and not re.search(r'[:,;]|[=+*/^]|\\[a-zA-Z]', body):
            if '[Figure:' not in body and len(body.split()) <= 6:
                continue

        # Merge into previous topic ONLY when the same non-empty title
        # appears on consecutive slides (e.g. "Transforms (cont.)").
        # Never auto-merge pages that simply have no inline title — those
        # are distinct slides and must each become their own det_topic so
        # the bipartite safety-union can detect LLM-missed concepts.
        if topics and title and title.lower() == topics[-1].topic.lower():
            topics[-1].slide_text += "\n\n" + part
            if body:
                topics[-1].key_points.extend(_extract_bullets(body))  # no [:2] cap
        else:
            topics.append(SlideTopic(
                topic=display_title,
                slide_text=part,
                key_points=_extract_bullets(body),  # no cap -- include all key points
            ))

    return topics


def _extract_bullets(text: str) -> list[str]:
    """Pull out bullet-point-like lines as key points.

    NO hard cap — every formula, definition, and algorithm line must enter
    the key_points list so the note-generation checklist is complete.
    Long lines (formulas, LaTeX) are explicitly included.
    """
    lines = text.split('\n')
    bullets = []
    seen: set[str] = set()
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith('---'):
            continue
        # Skip [Figure: ...] annotations — image context, not content obligations
        if stripped.startswith('[Figure:') or stripped.startswith('[Textbook Figure:'):
            continue
        norm = stripped.lower()
        if norm in seen:
            continue
        seen.add(norm)
        # Bullet markers
        if stripped.startswith(('-', '–', '*', '•', '->')):
            point = stripped.lstrip('–-*•-> ').strip()
            if len(point) > 8:
                bullets.append(point)
        # Any non-trivial content line (no upper length limit — formulas can be long)
        elif len(stripped) > 8:
            bullets.append(stripped)
    return bullets  # NO :5 cap


def _derive_topic_name_from_body(body: str, fallback: str) -> str:
    """
    Derive a meaningful topic name from slide body text when the slide marker
    has no inline title (e.g. "--- Slide 14 ---" with no ": Title" part).

    Strategy (tried in order):
      1. First line that looks like a heading (ALL-CAPS, Title Case ≥ 3 words,
         or starts with a #)
      2. First bullet point content (stripped of leading -/•/*)
            3. First sentence of the first non-trivial line (up to 80 chars, trimmed
         at the last word boundary before a comma/semicolon/period)
      4. fallback (the original "Slide N" string)

        The result is title-cased and capped at 80 characters.
    """
    if not body:
        return fallback

    lines = [l.strip() for l in body.splitlines() if l.strip()]
    # Strip slide marker lines and [Figure: ...] annotations
    lines = [l for l in lines
             if not re.match(r'^---\s*(?:Slide|Page)', l, re.I)
             and not l.startswith('[')]

    if not lines:
        return fallback

    def _clean(s: str) -> str:
        """Strip bullet markers and trailing punctuation, title-case, cap length."""
        s = re.sub(r'^[\-\–\*\•\>\s]+', '', s).strip()
        s = re.sub(r'[\.\:\;\,]+$', '', s).strip()
        if len(s) > 80:
            # Trim at last space before 80 chars, never leave empty.
            clipped = s[:80]
            if ' ' in clipped:
                clipped = clipped.rsplit(' ', 1)[0]
            s = clipped.strip() or s[:80].strip()
        return s.strip()

    # 1. Explicit heading line
    for line in lines:
        # ALL-CAPS line (likely a slide title)
        if line.isupper() and len(line.split()) >= 2:
            return _clean(line).title()
        # Markdown heading
        if line.startswith('#'):
            return _clean(re.sub(r'^#+\s*', '', line))
        # Title Case line with ≥ 3 words (but not a full sentence)
        words = line.split()
        if (len(words) >= 3
                and sum(1 for w in words if w[0].isupper()) >= len(words) * 0.6
                and not line.endswith(('.', '?', '!'))
                and len(line) <= 70):
            return _clean(line)

    # 2. First bullet point
    for line in lines:
        if re.match(r'^[\-\–\*\•]\s+\S', line):
            cleaned = _clean(line)
            if len(cleaned.split()) >= 2:
                return cleaned.title() if cleaned.islower() else cleaned

    # 3. First substantive line — take up to 60 chars
    first = lines[0]
    cleaned = _clean(first)
    if len(cleaned.split()) >= 2:
        return cleaned.title() if cleaned.islower() else cleaned

    return fallback


def _heading_looks_suspicious(heading: str) -> bool:
    """Detect headings that are likely noisy/truncated and worth AI polishing."""
    h = (heading or '').strip()
    if not h:
        return True
    if re.fullmatch(r'Slide\s+\d+', h, flags=re.IGNORECASE):
        return True
    if len(h) >= 70:
        return True
    if re.search(r'\[[^\]]*$', h):
        return True
    if re.search(r'[^a-zA-Z0-9\s\-\(\),:/&]', h):
        return True
    # Truncation often leaves connector words dangling at the end.
    if re.search(r'\b(of|for|and|or|to|with|from|in|on|by)$', h, flags=re.IGNORECASE):
        return True
    return False


def _normalize_heading_text(text: str) -> str:
    """Normalize heading output from AI into a clean, single-line title."""
    h = re.sub(r'\s+', ' ', (text or '').strip())
    h = re.sub(r'^["\'\-\*\#\d\.\)\s]+', '', h)
    h = h.rstrip(' .:;,')
    if len(h) > 80:
        clipped = h[:80]
        if ' ' in clipped:
            clipped = clipped.rsplit(' ', 1)[0]
        h = clipped.strip() or h[:80].strip()
    return h


async def _suggest_heading_with_llm(slide_text: str, current_heading: str) -> Optional[str]:
    """Ask Azure/Groq for a short clean heading for one page's content."""
    system = (
        "You generate clean academic section headings from one slide/page. "
        "Return ONLY the heading text, no quotes, no markdown, no explanations. "
        "Length: 3-8 words, title case."
    )
    user = (
        "Create a clean heading for this page content. "
        f"Current heading: {current_heading}\n\n"
        "Page content:\n"
        f"{slide_text[:2000]}"
    )

    async def _azure_call() -> Optional[str]:
        if not _azure_ok():
            return None
        try:
            import httpx
            endpoint   = os.environ.get("AZURE_OPENAI_ENDPOINT", "").rstrip("/")
            api_key    = os.environ.get("AZURE_OPENAI_API_KEY", "")
            api_ver    = os.environ.get("AZURE_OPENAI_API_VERSION", "2024-10-21")
            deployment = os.environ.get("AZURE_OPENAI_DEPLOYMENT", "gpt-4o")
            url = f"{endpoint}/openai/deployments/{deployment}/chat/completions?api-version={api_ver}"
            payload = {
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                "max_tokens": 32,
                "temperature": 0.0,
            }
            headers = {"api-key": api_key, "Content-Type": "application/json"}
            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.post(url, json=payload, headers=headers)
            if not resp.is_success:
                return None
            return resp.json()["choices"][0]["message"]["content"].strip()
        except Exception:
            return None

    async def _groq_call() -> Optional[str]:
        if not _groq_ok():
            return None
        try:
            import httpx
            api_key = os.environ.get("GROQ_API_KEY", "")
            model   = os.environ.get("GROQ_MODEL", "llama-3.3-70b-versatile")
            payload = {
                "model": model,
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                "max_tokens": 32,
                "temperature": 0.0,
            }
            headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.post("https://api.groq.com/openai/v1/chat/completions", json=payload, headers=headers)
            if not resp.is_success:
                return None
            return resp.json()["choices"][0]["message"]["content"].strip()
        except Exception:
            return None

    raw = await _azure_call()
    if raw is None:
        raw = await _groq_call()
    if not raw:
        return None

    candidate = _normalize_heading_text(raw)
    if len(candidate.split()) < 2:
        return None
    return candidate


async def _polish_topic_headings(topics: list[SlideTopic]) -> list[SlideTopic]:
    """Polish only suspicious headings via a tiny LLM prompt."""
    if not topics:
        return topics

    idxs = [i for i, t in enumerate(topics) if _heading_looks_suspicious(t.topic)]
    if not idxs:
        return topics

    sem = asyncio.Semaphore(4)

    async def _polish_one(i: int) -> tuple[int, Optional[str]]:
        topic = topics[i]
        async with sem:
            suggestion = await _suggest_heading_with_llm(topic.slide_text, topic.topic)
            return i, suggestion

    polished = list(topics)
    changed = 0
    for i, suggestion in await asyncio.gather(*[_polish_one(i) for i in idxs], return_exceptions=False):
        if suggestion and suggestion.lower() != polished[i].topic.lower():
            logger.info("slide_analyzer: heading polish '%s' -> '%s'", polished[i].topic, suggestion)
            polished[i] = SlideTopic(
                topic=suggestion,
                slide_text=polished[i].slide_text,
                key_points=polished[i].key_points,
            )
            changed += 1

    if changed:
        logger.info("slide_analyzer: polished %d heading(s)", changed)
    return polished


# -- Public API ----------------------------------------------------------------

_SLIDE_CHUNK_SIZE = 18_000   # chars per LLM call — kept small so the topics JSON never approaches the 16k-token output limit
# FIX G2: no longer hard-truncate the full deck; instead split into chunks
# and merge the resulting topic lists.


def _split_at_slide_boundary(text: str, max_chars: int) -> list[str]:
    """
    Split slide text at slide boundary markers so each chunk ends on a complete
    slide, keeping chunk size <= max_chars. Falls back to hard split if no markers.
    Handles all three marker formats:
      --- Slide N ---     (PPTX)
      --- Page N ---      (PDF)
      --- Page: name ---  (image OCR)
    """
    if len(text) <= max_chars:
        return [text]
    # Find all slide marker positions (all three formats)
    boundaries = [m.start() for m in re.finditer(
        r'(?m)^---\s*(?:(?:Slide|Page)\s+\d+|Page:\s*[^\-\n])', text
    )]
    if not boundaries:
        # No markers - hard split
        return [text[i:i + max_chars] for i in range(0, len(text), max_chars)]

    chunks, start = [], 0
    for boundary in boundaries[1:]:  # skip first (it IS the start)
        if boundary - start >= max_chars:  # >= so a chunk of exactly max_chars still splits
            # Accumulated content since last cut exceeds limit - cut here
            chunks.append(text[start:boundary])
            start = boundary
    # Add remainder
    if start < len(text):
        chunks.append(text[start:])
    return chunks if chunks else [text]


async def analyse_slides(slides_text: str) -> list[SlideTopic]:
    """
    Extract structured topics from slide text.

    FIX G2: For long decks (> 38 k chars), the text is split at slide
    boundaries and analysed in multiple LLM calls. Topics from all chunks are
    concatenated in order.  No slide is silently dropped.

    Chunks are processed CONCURRENTLY (asyncio.gather) so a 3-chunk deck
    takes ~1× instead of ~3× the single-chunk time.

    Priority per chunk: Azure -> Groq -> deterministic regex parser.
    Returns a list of SlideTopic objects in lecture order.
    """
    if not slides_text.strip():
        return []

    chunks = _split_at_slide_boundary(slides_text, _SLIDE_CHUNK_SIZE)
    logger.info("slide_analyzer: %d chunk(s) to analyse (parallel)", len(chunks))

    async def _analyse_chunk(chunk_idx: int, chunk_text: str) -> list[SlideTopic]:
        logger.info(
            "slide_analyzer: analysing chunk %d/%d (%d chars)",
            chunk_idx + 1, len(chunks), len(chunk_text),
        )
        raw_topics = await _call_azure_json(chunk_text)
        if not raw_topics:
            raw_topics = await _call_groq_json(chunk_text)

        chunk_topics: list[SlideTopic] = []
        if raw_topics:
            for item in raw_topics:
                if not isinstance(item, dict):
                    continue
                topic_name = str(item.get("topic", "")).strip()
                if not topic_name:
                    continue
                slide_text = str(item.get("slide_text", "")).strip()
                key_points = [str(kp) for kp in item.get("key_points", []) if kp]
                if not slide_text and key_points:
                    slide_text = "\n".join(f"- {kp}" for kp in key_points)
                    logger.warning(
                        "slide_analyzer: topic %r had empty slide_text - "
                        "backfilled from %d key_points", topic_name, len(key_points)
                    )
                chunk_topics.append(SlideTopic(
                    topic=topic_name,
                    slide_text=slide_text,
                    key_points=key_points,
                ))
        else:
            chunk_topics.extend(_deterministic_parse(chunk_text))
        return chunk_topics

    # Run all chunks in parallel
    chunk_results = await asyncio.gather(
        *[_analyse_chunk(i, chunk) for i, chunk in enumerate(chunks)],
        return_exceptions=True,
    )

    all_topics: list[SlideTopic] = []
    for i, result in enumerate(chunk_results):
        if isinstance(result, Exception):
            logger.warning("slide_analyzer chunk %d failed: %s — using fallback", i + 1, result)
            all_topics.extend(_deterministic_parse(chunks[i]))
        else:
            all_topics.extend(result)

    if all_topics:
        before_dedup = len(all_topics)
        all_topics = _deduplicate_topics(all_topics)

        # ── Safety union: page-number tracking (primary) + word-overlap (fallback)
        #
        # PRIMARY: PDF extractor stamps a unique number on every --- Page N ---
        # marker.  If the LLM preserved them verbatim in slide_text (which the
        # prompt requires), we know EXACTLY which pages it covered vs dropped —
        # no word-guessing needed.
        #
        # FALLBACK: If the LLM stripped every marker from slide_text, fall back
        # to bipartite word-overlap matching so nothing is silently lost.

        full_source = "\n".join(chunks)

        # All page/slide numbers in the SOURCE
        all_page_nums: set[int] = {
            int(m) for m in re.findall(r'---\s*(?:Slide|Page)\s+(\d+)', full_source)
        }
        # Page/slide numbers that appear in ANY LLM topic's slide_text
        llm_page_nums: set[int] = {
            int(m) for t in all_topics
            for m in re.findall(r'---\s*(?:Slide|Page)\s+(\d+)', t.slide_text)
        }

        added = 0

        if all_page_nums and llm_page_nums:
            # ── PRIMARY PATH ────────────────────────────────────────────────
            missing_page_nums = all_page_nums - llm_page_nums
            logger.info(
                "slide_analyzer: source pages %s | LLM-covered %s | missing %s",
                sorted(all_page_nums), sorted(llm_page_nums), sorted(missing_page_nums),
            )

            if missing_page_nums:
                # Build page-number → raw text block lookup
                page_blocks: dict[int, str] = {}
                for block in re.split(
                    r'(?=^---\s*(?:Slide|Page)\s+\d+)', full_source, flags=re.MULTILINE
                ):
                    bm = re.match(r'---\s*(?:Slide|Page)\s+(\d+)', block.strip())
                    if bm:
                        page_blocks[int(bm.group(1))] = block.strip()

                for pnum in sorted(missing_page_nums):
                    block = page_blocks.get(pnum)
                    if not block:
                        continue
                    body = re.sub(r'^---[^\n]*---', '', block, count=1).strip()
                    if len(body) < 10:       # genuinely empty page
                        continue
                    tm = re.match(r'---\s*(?:Slide|Page)\s+\d+(?::\s*(.*?))?\s*---', block)
                    inline_title = (tm.group(1) or '').strip() if tm else ''
                    topic_name = inline_title or f"Slide {pnum}"
                    all_topics.append(SlideTopic(
                        topic=topic_name,
                        slide_text=block,
                        key_points=_extract_bullets(body),
                    ))
                    added += 1
                    logger.info(
                        "slide_analyzer: page-number union added missed page %d '%s'",
                        pnum, topic_name,
                    )

        else:
            # ── FALLBACK PATH: word-overlap bipartite matching ────────────────
            # LLM dropped the --- Page N --- markers from slide_text.
            logger.info(
                "slide_analyzer: no page markers in LLM slide_text — using word-overlap union"
            )
            _SKIP_W = {"slide", "page", "figure", "table", "notes", "lecture",
                       "course", "university", "professor", "content", "example"}

            def _wset(text: str) -> set[str]:
                return {w.lower() for w in re.findall(r'[a-zA-Z]{4,}', text)
                        if w.lower() not in _SKIP_W}

            det_topics: list[SlideTopic] = []
            for chunk in chunks:
                det_topics.extend(_deterministic_parse(chunk))

            if det_topics:
                llm_word_sets = [_wset(t.slide_text) for t in all_topics]
                pairs_w: list[tuple[int, int, int]] = []
                for di, dt in enumerate(det_topics):
                    dw = _wset(dt.slide_text)
                    if not dw:
                        continue
                    for li, lw in enumerate(llm_word_sets):
                        score = len(dw & lw)
                        if score >= 2:
                            pairs_w.append((score, di, li))

                pairs_w.sort(reverse=True)
                claimed_d: set[int] = set()
                claimed_l: set[int] = set()
                for score, di, li in pairs_w:
                    if di not in claimed_d and li not in claimed_l:
                        claimed_d.add(di)
                        claimed_l.add(li)

                for di, dt in enumerate(det_topics):
                    if di not in claimed_d:
                        all_topics.append(dt)
                        added += 1
                        logger.info(
                            "slide_analyzer: word-overlap union added missed topic '%s'",
                            dt.topic,
                        )

        after_dedup = len(all_topics) - added
        logger.info(
            "slide_analyzer: %d LLM topics → %d after dedup → +%d from bipartite union = %d total. Topics: %s",
            before_dedup, after_dedup, added, len(all_topics),
            [t.topic for t in all_topics],
        )
        # ── Post-process: split any topic that the LLM collapsed multiple slides
        # into. This is the final safety net: if the LLM returns 1 topic for 4
        # slides (putting all markers inside that 1 slide_text), we forcibly split
        # it into separate per-slide topics so the note generator covers each one.
        all_topics = _enforce_one_topic_per_slide(all_topics)
        logger.info(
            "slide_analyzer: after per-slide enforcement: %d topics",
            len(all_topics),
        )
        all_topics = await _polish_topic_headings(all_topics)
        return all_topics

    logger.info("slide_analyzer: using deterministic fallback parser")
    topics = _deterministic_parse(slides_text)
    logger.info("slide_analyzer: extracted %d topics via fallback", len(topics))
    return await _polish_topic_headings(topics)


def _enforce_one_topic_per_slide(topics: list[SlideTopic]) -> list[SlideTopic]:
    """
    Split any topic whose slide_text contains more than one slide/page marker
    into individual per-slide topics.

    This is the final safety net for the case where the LLM collapses multiple
    slides into a single topic entry, causing the note generator to produce
    notes that seem to cover only 1 slide.

    Split logic:
    - Tokenise slide_text on --- Slide N --- / --- Page N --- boundaries.
    - Each boundary block becomes its own SlideTopic.
    - Topic name: use inline title from the marker if present, else "Slide N".
    - key_points: distribute bullet lines from each block.
    - Exception: if the block body is < 10 chars it is skipped (empty page).
    - A topic with only 1 marker is returned as-is (no split needed).
    """
    _MARKER_RE = re.compile(r'^(---\s*(?:Slide|Page)\s+\d+(?::[^\-\n]*)?\s*---)', re.MULTILINE)
    _NUM_RE    = re.compile(r'(?:Slide|Page)\s+(\d+)')

    result: list[SlideTopic] = []

    for t in topics:
        markers = list(_MARKER_RE.finditer(t.slide_text))
        if len(markers) <= 1:
            result.append(t)
            continue

        # Split the slide_text at each marker boundary
        blocks: list[tuple[str, str]] = []  # (marker_line, body)
        for i, m in enumerate(markers):
            marker_line = m.group(1)
            body_start  = m.end()
            body_end    = markers[i + 1].start() if i + 1 < len(markers) else len(t.slide_text)
            body        = t.slide_text[body_start:body_end].strip()
            blocks.append((marker_line, body))

        split_count = 0
        for marker_line, body in blocks:
            if len(body) < 10:   # genuinely empty slide — skip
                continue
            # Derive topic name: use inline title if present, else extract
            # a meaningful name from the slide body. Fall back to "Slide N"
            # only when the body gives no usable text either.
            inline = re.search(r'---\s*(?:Slide|Page)\s+\d+\s*:\s*(.*?)\s*---', marker_line)
            nm = _NUM_RE.search(marker_line)
            if inline and inline.group(1).strip():
                topic_name = inline.group(1).strip()
            else:
                fallback = f"Slide {nm.group(1)}" if nm else t.topic
                topic_name = _derive_topic_name_from_body(body, fallback)
            result.append(SlideTopic(
                topic      = topic_name,
                slide_text = marker_line + "\n" + body,
                key_points = _extract_bullets(body),
            ))
            split_count += 1

        if split_count > 1:
            logger.info(
                "slide_analyzer: split collapsed topic %r into %d per-slide topics",
                t.topic, split_count,
            )
        elif split_count == 0:
            # All blocks were empty — keep original to avoid data loss
            result.append(t)

    return result


def _topic_similarity(a: str, b: str) -> float:
    """
    Jaccard word-overlap similarity between two topic names (0.0 to 1.0).
    Used to detect EXACT duplicate topics across PDF files / chunks.

    Uses Jaccard (|A∩B|/|A∪B|) rather than the asymmetric /min formulation,
    because /min caused single-word topics like 'Z-Transform' → {'transform'}
    to match ANY other transform with similarity 1.0, collapsing all topics.

    Stop list: ONLY function words (articles/prepositions/conjunctions).
    Domain terms (theorem, analysis, transform, …) are kept because they are
    the primary distinguishing words for academic topics.
    """
    # Keep only true function words — never domain terms
    stop = {"the", "a", "an", "of", "and", "in", "to", "for", "on", "with",
            "is", "are", "its", "their", "this", "that", "by", "or", "at"}
    def words(s):
        # Keep words of length >= 2 AND pure digit tokens (e.g. "1" in "Slide 1").
        # Without digits, words("Slide 1") == words("Slide 2") == {'slide'},
        # making Jaccard = 1.0 and collapsing ALL "Slide N" topics into one.
        return {w for w in s.lower().replace("-", " ").replace("_", " ").split()
                if (len(w) >= 2 or w.isdigit()) and w not in stop}
    wa, wb = words(a), words(b)
    if not wa or not wb:
        return 0.0
    # Jaccard: penalises both missing and extra words symmetrically
    return len(wa & wb) / len(wa | wb)


def _deduplicate_topics(topics: list) -> list:
    """
    Merge topic entries that refer to the same concept across multiple PDF files.

    Duplicates arise when multiple PDFs cover the same topic, or when the LLM
    uses slightly different names across chunks ("DFT" vs "DFT Overview").

    Strategy:
      - Topics with Jaccard similarity >= 0.85 are merged (near-identical names only).
      - This is intentionally conservative: it is far better to have two slightly
        redundant ## sections than to silently drop a whole topic.
      - Merged entry keeps the first occurrence name.
      - slide_text values are concatenated so ALL content is preserved.
      - key_points are deduplicated while preserving order.

    Result: no duplicate ## sections in the generated notes.
    """
    THRESHOLD = 0.85  # conservative: only merge truly identical topic names
    merged = []
    used = [False] * len(topics)

    for i, t in enumerate(topics):
        if used[i]:
            continue
        group = [t]
        used[i] = True
        for j in range(i + 1, len(topics)):
            if not used[j] and _topic_similarity(t.topic, topics[j].topic) >= THRESHOLD:
                group.append(topics[j])
                used[j] = True

        if len(group) == 1:
            merged.append(t)
        else:
            # Combine: use first topic name, merge all slide texts, dedup key_points
            combined_text = "\n\n".join(
                f"[{g.topic}]\n{g.slide_text}" if g.topic != group[0].topic else g.slide_text
                for g in group
            )
            seen_kp: set = set()
            combined_kp = []
            for g in group:
                for kp in g.key_points:
                    norm = kp.strip().lower()
                    if norm not in seen_kp:
                        seen_kp.add(norm)
                        combined_kp.append(kp.strip())

            logger.info(
                "dedup: merged %d topics under '%s' (%s)",
                len(group), group[0].topic,
                ", ".join(f"'{g.topic}'" for g in group[1:])
            )
            merged.append(SlideTopic(
                topic      = group[0].topic,
                slide_text = combined_text,
                key_points = combined_kp,
            ))

    return merged
