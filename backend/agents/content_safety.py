"""
agents/content_safety.py — Azure AI Content Safety
────────────────────────────────────────────────────
Screens BOTH student input (before LLM) and LLM output (before sending to student).

Design:
  • Input screening  — rejects the request before any LLM call (saves cost + latency)
  • Output screening — catches anything the LLM slips through
  • Async, non-blocking, cached — result cached per text hash for 5 min
  • Singleton client — no reconnection overhead per call
  • Strict on output, lenient on input (curse words in questions are stripped/redirected
    but never cause a hard 4xx — we clean and continue)

Severity scale: 0=Safe  2=Low  4=Medium  6=High
  Input threshold : 6  (only block truly severe hate/violence/CSAM in questions)
  Output threshold: 4  (medium+ in responses is always blocked)

Fallback: fail-open (True, "") so service outage never breaks studying.
"""
from __future__ import annotations

import asyncio
import hashlib
import logging
import os
import re
import time
from typing import Optional

logger = logging.getLogger(__name__)

_ENDPOINT  = os.environ.get("AZURE_CONTENT_SAFETY_ENDPOINT", "").rstrip("/")
_KEY       = os.environ.get("AZURE_CONTENT_SAFETY_KEY", "")
_OUTPUT_THRESHOLD = 4   # medium+ in AI responses → block
_INPUT_THRESHOLD  = 6   # high only in student input → block

# ── Simple in-process cache ───────────────────────────────────────────────────
# Key: (text_hash, threshold) → (is_safe, category, expires_at)
_CACHE: dict[tuple, tuple] = {}
_CACHE_TTL = 300  # 5 minutes


def _cache_get(text: str, threshold: int) -> Optional[tuple[bool, str]]:
    key = (hashlib.md5(text.encode(), usedforsecurity=False).hexdigest(), threshold)
    entry = _CACHE.get(key)
    if entry and entry[2] > time.monotonic():
        return entry[0], entry[1]
    return None


def _cache_set(text: str, threshold: int, is_safe: bool, category: str):
    key = (hashlib.md5(text.encode(), usedforsecurity=False).hexdigest(), threshold)
    _CACHE[key] = (is_safe, category, time.monotonic() + _CACHE_TTL)
    # Evict old entries if cache grows large
    if len(_CACHE) > 1000:
        now = time.monotonic()
        expired = [k for k, v in _CACHE.items() if v[2] < now]
        for k in expired[:200]:
            _CACHE.pop(k, None)


# ── Singleton client ──────────────────────────────────────────────────────────
_client = None
_client_lock = asyncio.Lock()


def _is_configured() -> bool:
    return bool(_ENDPOINT and _KEY
                and "placeholder" not in _ENDPOINT.lower()
                and "your-" not in _KEY.lower())


def _get_client():
    global _client
    if _client is None and _is_configured():
        try:
            from azure.ai.contentsafety import ContentSafetyClient
            from azure.core.credentials import AzureKeyCredential
            _client = ContentSafetyClient(
                endpoint=_ENDPOINT,
                credential=AzureKeyCredential(_KEY),
            )
        except Exception as e:
            logger.warning("ContentSafetyClient init failed: %s", e)
    return _client


# ── Core check ────────────────────────────────────────────────────────────────

async def _check(text: str, threshold: int) -> tuple[bool, str]:
    """Internal check with caching, singleton client, and httpx fallback."""
    if not _is_configured():
        return True, ""
    if not text or not text.strip():
        return True, ""

    # Truncate — API limit
    text_trunc = text[:10_000]

    # Cache hit
    cached = _cache_get(text_trunc, threshold)
    if cached is not None:
        return cached

    result = (True, "")

    # Try SDK (singleton client)
    client = _get_client()
    if client:
        try:
            from azure.ai.contentsafety.models import AnalyzeTextOptions, TextCategory
            req = AnalyzeTextOptions(
                text=text_trunc,
                categories=[
                    TextCategory.HATE,
                    TextCategory.SELF_HARM,
                    TextCategory.SEXUAL,
                    TextCategory.VIOLENCE,
                ],
            )
            resp = await asyncio.wait_for(
                asyncio.to_thread(client.analyze_text, req),
                timeout=3.0,  # never block more than 3s
            )
            for item in resp.categories_analysis:
                sev = item.severity or 0
                if sev >= threshold:
                    logger.warning("ContentSafety flagged: category=%s severity=%d", item.category, sev)
                    result = (False, str(item.category))
                    break
            _cache_set(text_trunc, threshold, result[0], result[1])
            return result
        except asyncio.TimeoutError:
            logger.warning("ContentSafety SDK timed out — pass-through")
            return True, ""
        except Exception as e:
            logger.warning("ContentSafety SDK error: %s — pass-through", e)
            return True, ""

    # httpx fallback
    try:
        import httpx
        url = f"{_ENDPOINT}/contentsafety/text:analyze?api-version=2024-09-01"
        async with httpx.AsyncClient(timeout=3.0) as http:
            r = await http.post(
                url,
                headers={"Ocp-Apim-Subscription-Key": _KEY, "Content-Type": "application/json"},
                json={"text": text_trunc[:5000], "categories": ["Hate", "SelfHarm", "Sexual", "Violence"]},
            )
        if r.status_code == 200:
            for cat in r.json().get("categoriesAnalysis", []):
                if (cat.get("severity") or 0) >= threshold:
                    result = (False, cat.get("category", "unknown"))
                    break
    except Exception as e:
        logger.warning("ContentSafety httpx fallback failed: %s — pass-through", e)

    _cache_set(text_trunc, threshold, result[0], result[1])
    return result


# ── Public API ────────────────────────────────────────────────────────────────

async def check_output(text: str) -> tuple[bool, str]:
    """
    Screen LLM-generated text before returning to the student.
    Threshold: medium+ (severity ≥ 4). Blocks the response if flagged.
    """
    return await _check(text, _OUTPUT_THRESHOLD)


async def check_input(text: str) -> tuple[bool, str]:
    """
    Screen student input before sending to the LLM.
    Threshold: high only (severity ≥ 6) — curse words at severity 2-4 are
    NOT blocked here; they are sanitised by sanitise_input() instead.
    Only truly harmful content (severe hate speech, CSAM, violence) is rejected.
    """
    return await _check(text, _INPUT_THRESHOLD)


# Keep legacy name for backwards compatibility
async def check_content_safety(text: str) -> tuple[bool, str]:
    """Legacy wrapper — screens as output (threshold=4)."""
    return await check_output(text)


# ── Input sanitisation ────────────────────────────────────────────────────────

# Profanity list — common English curse words. Student can still ask their
# academic question; the profanity is stripped so the LLM never sees it.
# We do NOT inject these words into generated responses.
_PROFANITY = re.compile(
    r'\b(fuck(?:ing?|ed?|s)?|shit(?:ty)?|ass(?:hole)?|bitch(?:es)?'
    r'|bastard|damn(?:it)?|crap|piss(?:ed)?|hell|cunt|dick|cock'
    r'|motherfuck(?:er|ing)?|bullshit|wtf|stfu)\b',
    re.IGNORECASE,
)


def sanitise_input(text: str) -> tuple[str, bool]:
    """
    Strip profanity from student input before sending to the LLM.
    Returns (cleaned_text, was_sanitised).
    The academic intent is preserved — only the offensive words are removed.
    We never echo them back.
    """
    cleaned, count = _PROFANITY.subn("", text)
    # Collapse multiple spaces left after removal
    cleaned = re.sub(r'  +', ' ', cleaned).strip()
    return cleaned, count > 0


# ── OCR garble word scorer — used by strip_error_exposure_language ────────────
# 
# These patterns match OCR-corrupted tokens that might slip through into
# student-facing output. The scorer is used as a lightweight pre-check
# before running strip_error_exposure_language on LLM output.
#
# Heuristic rules (same as image_ocr._clean_ocr_text):
#   - y/Y count as vowels (prevents false positives on rhythm, sync, glyph)
#   - ALL-CAPS short words treated as acronyms (LSTM, HTTP → not garble)
#   - Consonant run threshold = 5, minimum word length 6
#   - Vowel ratio < 10% only triggers for words >= 8 chars

_OCR_VOWELS = set('aeiouAEIOUyY')
_OCR_CONSONANT_RUN = re.compile(r'[bcdfghjklmnpqrstvwxzBCDFGHJKLMNPQRSTVWXZ]{5,}')
_OCR_DIGIT_IN_ALPHA = re.compile(r'(?:[a-zA-Z]+[0-9]+[a-zA-Z]*|[a-zA-Z]*[0-9]+[a-zA-Z]+)')


def _word_garble_score(word: str) -> float:
    """
    Return 1.0 if the word looks garbled (OCR noise), 0.0 if it looks clean.
    Binary: we use this to count garbled tokens across a text sample.
    """
    if not any(c.isalpha() for c in word):
        return 0.0
    if len(word) < 4:
        return 0.0
    # ALL-CAPS short words are acronyms
    if word.isupper() and len(word) <= 8:
        return 0.0
    # Digit embedded in alphabetic word
    if any(c.isdigit() for c in word) and _OCR_DIGIT_IN_ALPHA.fullmatch(word):
        return 1.0
    alpha = ''.join(c for c in word if c.isalpha())
    if len(alpha) < 4:
        return 0.0
    vowels = sum(1 for c in alpha if c in _OCR_VOWELS)
    if vowels == 0 and len(alpha) >= 5:
        return 1.0
    if vowels / len(alpha) < 0.10 and len(alpha) >= 8:
        return 1.0
    if len(alpha) >= 6 and _OCR_CONSONANT_RUN.search(alpha):
        return 1.0
    return 0.0


def strip_error_exposure_language(text: str) -> str:
    """
    Responsible AI post-processing: strip any phrases that expose internal
    errors or source defects to the student from LLM output.

    Safe to call with None or empty string — returns empty string in that case.
    """
    if not text:
        return text or ""
    if not isinstance(text, str):
        return str(text)
    # Patterns to remove entirely (the whole sentence containing the phrase)
    _EXPOSURE_PHRASES = [
        r'[^.!?\n]*\bOCR\s*(error|artifact|noise|garbl[a-z]*)[^.!?\n]*[.!?]?',
        r'[^.!?\n]*\btypo\b[^.!?\n]*[.!?]?',
        r'[^.!?\n]*\bmisspell[a-z]*\b[^.!?\n]*[.!?]?',
        r'[^.!?\n]*the\s+(correct\s+spelling|correct\s+term)\s+is\b[^.!?\n]*[.!?]?',
        r'[^.!?\n]*⚠️\s*Note\s+correction\s*:[^.!?\n]*[.!?]?',
        r'[^.!?\n]*\bslides?\s+contain[a-z]*\s+an?\s+error\b[^.!?\n]*[.!?]?',
        r'[^.!?\n]*\bthere\s+is\s+a\s+mistake\b[^.!?\n]*[.!?]?',
        r'[^.!?\n]*\bgarbl[a-z]*\b[^.!?\n]*[.!?]?',
    ]
    cleaned = text
    for pattern in _EXPOSURE_PHRASES:
        cleaned = re.sub(pattern, '', cleaned, flags=re.IGNORECASE)
    # Collapse double blank lines left after removal
    cleaned = re.sub(r'\n{3,}', '\n\n', cleaned).strip()
    return cleaned
