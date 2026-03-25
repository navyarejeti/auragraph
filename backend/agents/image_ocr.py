"""
agents/image_ocr.py — Azure AI Vision + Groq vision fallback
──────────────────────────────────────────────────────────────
Extracts text from handwritten/printed notes images, and describes
slide figures for embedding into study notes.

Priority (OCR):
  1. Azure AI Vision (dense captions + OCR) — AZURE_VISION_ENDPOINT + KEY
  2. Groq vision (llama-4-scout)             — GROQ_API_KEY
  3. pytesseract                             — local
  4. Placeholder text

Priority (figure description):
  1. Groq vision (LLM — understands academic diagrams)
  2. Azure AI Vision dense captions (CV fallback)
  3. Generic fallback string
"""
from __future__ import annotations

import base64
import io
import logging
import os
from pathlib import Path

logger = logging.getLogger(__name__)

IMAGE_EXTENSIONS = {
    '.jpg', '.jpeg', '.png', '.webp',
    '.bmp', '.tiff', '.tif', '.heic', '.heif',
}

_MIME_MAP = {
    '.jpg': 'image/jpeg', '.jpeg': 'image/jpeg',
    '.png': 'image/png',  '.webp': 'image/webp',
    '.bmp': 'image/bmp',  '.tiff': 'image/tiff',
    '.tif': 'image/tiff', '.heic': 'image/heic',
    '.heif': 'image/heif',
}

# ── OCR post-processing: responsible clean-up pass ────────────────────────────
# This is the Responsible AI layer at the data-ingestion boundary.
# Raw OCR output — especially from blurry or low-resolution images — frequently
# contains garbled words, broken math, and nonsense character sequences. Feeding
# this raw noise directly into note generation causes:
#   • Garbled terminology appearing as correct text in student notes
#   • Quiz questions and options containing nonsense strings (e.g. "hyptvnse")
#   • The note LLM explicitly calling out OCR errors, making students distrust notes
#
# Principle: errors introduced by our toolchain must NEVER surface to students.
# We silently reconstruct intent from context before any downstream use.

_OCR_CLEAN_SYSTEM = """\
You are an academic OCR correction engine with deep domain expertise across
engineering, mathematics, physics, and science subjects.

You receive raw text extracted by OCR from a lecture slide or handwritten note image.
The source image may have been blurry, low-resolution, or poorly lit, so the OCR
output likely contains character-level errors — garbled words, broken symbols,
substituted letters (e.g. 'l' for '1', 'O' for '0', 'vv' for 'w'),
and mangled technical terminology.

YOUR ONLY JOB:
Reconstruct what the professor INTENDED to write, using your domain knowledge
and the surrounding academic context as the authoritative guide.

RULES (non-negotiable):
1. Fix garbled words and OCR noise silently — no annotations, no [sic], no corrections noted.
2. Reconstruct correct technical terminology from context.
   Examples: "hyptvnse" → "hypotenuse", "resistanc3" → "resistance",
   "intgral" → "integral", "eigenvalu3" → "eigenvalue",
   "Fourer" → "Fourier", "Laplce" → "Laplace", "diffrntial" → "differential".
3. Reconstruct broken math into valid LaTeX ($...$ inline, $$...$$ display).
4. Preserve the original document structure: headings, bullets, numbering, tables.
5. If a word is ambiguous but the academic context makes the intent clear, use the
   academically correct term. Never leave a known garble in the output.
6. Do NOT add, invent, or expand content. Only reconstruct what is already there.
7. Do NOT mention corrections, errors, or OCR issues anywhere in the output.
8. Output ONLY the cleaned text — no preamble, no explanations.
"""

_OCR_CLEAN_USER = """\
Below is raw OCR output from a lecture slide image. It may contain garbled words,
broken technical terms, and corrupted math. Reconstruct the intended academic content.

RAW OCR TEXT:
{raw_text}

Output only the reconstructed text. Do not note any corrections.
"""

# ── prompts ───────────────────────────────────────────────────────────────────

_OCR_SYSTEM = """\
You are a precise academic transcription assistant.
Your only job is to faithfully extract every piece of text from an image of
lecture notes — handwritten or printed — without omitting anything.
"""

_OCR_PROMPT = """\
The image contains lecture notes (handwritten, printed, or mixed).

Transcribe ALL visible text EXACTLY as written. Follow these rules:

CONTENT TO INCLUDE:
• Every heading and subheading (preserve hierarchy)
• All bullet points and numbered lists
• Mathematical formulas → convert to LaTeX inline ($...$) or display ($$...$$)
  e.g. "x squared" → $x^2$, "integral from 0 to T" → $\\int_0^T$
• Arrows, labels, and annotations on diagrams
• Tables → reproduce as a Markdown pipe-table
• Anything circled, underlined, or starred (mark with ** emphasis **)

DIAGRAMS:
• If there is a diagram/figure, add: [Diagram: one-line description of what it shows]

FORMAT RULES:
• Start directly with the text — no preamble
• Use blank lines between sections
• Preserve indentation hierarchy with bullets

Do NOT skip, paraphrase, or summarise anything.
"""

_DESCRIBE_PROMPT = """\
Describe this diagram/figure from a lecture slide or academic notes.

Write TWO to FOUR sentences covering:
1. What type of diagram it is (circuit, block diagram, graph, waveform, flowchart, \
state machine, table, formula derivation, geometric figure, signal plot, etc.)
2. Every labelled component, variable, axis, node, or value that is visible — \
be specific (e.g. "resistor R1 = 10Ω", "x-axis: time in ms", "node labelled V_out")
3. Any mathematical expressions, equations, or formulas shown
4. What concept or relationship it illustrates

Rules:
- Be specific and technical — this description will be read by a note-generation \
AI to incorporate the figure into study notes
- Name every visible label, variable, or component
- Keep it ≤ 80 words
- Output ONLY the description — no preamble, no "This image shows", no "The figure depicts"
"""


# ── helpers ───────────────────────────────────────────────────────────────────

def is_image_file(filename: str) -> bool:
    return Path(filename.lower()).suffix in IMAGE_EXTENSIONS


def _detect_mime(data: bytes) -> str:
    if data[:4] == b'\x89PNG':          return 'image/png'
    if data[:2] == b'\xff\xd8':         return 'image/jpeg'
    if data[:4] == b'RIFF' and data[8:12] == b'WEBP': return 'image/webp'
    if data[:6] in (b'GIF87a', b'GIF89a'): return 'image/gif'
    if data[:2] == b'BM':               return 'image/bmp'
    return 'image/jpeg'


def _resize(image_bytes: bytes, max_px: int = 1024) -> tuple[bytes, str]:
    """Resize longest side to max_px and re-encode as JPEG. Falls back on error."""
    try:
        from PIL import Image
        img = Image.open(io.BytesIO(image_bytes))
        w, h = img.size
        if max(w, h) > max_px:
            scale = max_px / max(w, h)
            img = img.resize((int(w * scale), int(h * scale)), Image.LANCZOS)
        buf = io.BytesIO()
        img.convert('RGB').save(buf, format='JPEG', quality=85)
        return buf.getvalue(), 'image/jpeg'
    except Exception as e:
        logger.debug("Image resize failed (%s) — using original", e)
        return image_bytes, _detect_mime(image_bytes)


def _convert_heic(data: bytes) -> tuple[bytes, str]:
    try:
        import pillow_heif; pillow_heif.register_heif_opener()
        from PIL import Image
        img = Image.open(io.BytesIO(data))
        buf = io.BytesIO()
        img.convert('RGB').save(buf, format='JPEG', quality=95)
        return buf.getvalue(), 'image/jpeg'
    except Exception:
        return data, 'image/heic'


def _clean_ocr_text(raw_text: str, filename: str, always_clean: bool = False) -> str:
    """
    Responsible AI post-processing pass: run a fast LLM call to reconstruct
    garbled OCR output before it enters the note-generation pipeline.

    always_clean=True skips the heuristic (used for tesseract output, which
    is the most error-prone backend and should always be cleaned).
    """
    if not raw_text or len(raw_text.strip()) < 10:
        return raw_text

    if not always_clean:
        # Heuristic: detect garbled OCR words using vowel/consonant analysis.
        #
        # Signals used:
        #   1. Digit embedded in alphabetic word: resistanc3, l1near
        #   2. Zero vowels (y counts as vowel) in word >= 5 chars: hyptvnse, adjvnt
        #   3. Very low vowel ratio (< 10%) in long words (>= 8 chars)
        #   4. 5+ consecutive consonants in words >= 6 chars
        #
        # Design choices that prevent false positives on real words:
        #   - y/Y count as vowels  → rhythm, myth, sync, glyph, gym all pass
        #   - ALL-CAPS <= 8 chars treated as acronyms → LSTM, HTTP, XML pass
        #   - Consonant run threshold = 5 (not 4) → strength (ngth=4) passes
        #   - Minimum word length 6 for consonant run → sqrt, nth pass
        import re as _re
        _VOWELS = set('aeiouAEIOUyY')
        _CONSONANT_RUN = _re.compile(
            r'[bcdfghjklmnpqrstvwxzBCDFGHJKLMNPQRSTVWXZ]{5,}'
        )
        _DIGIT_IN_ALPHA = _re.compile(
            r'(?:[a-zA-Z]+[0-9]+[a-zA-Z]*|[a-zA-Z]*[0-9]+[a-zA-Z]+)'
        )

        def _is_garbled(w: str) -> bool:
            if not any(c.isalpha() for c in w):
                return False
            if len(w) < 4:
                return False
            # ALL-CAPS short words are acronyms (LSTM, HTTP, DNA, etc.)
            if w.isupper() and len(w) <= 8:
                return False
            # Digit embedded in alphabetic word
            if any(c.isdigit() for c in w) and _DIGIT_IN_ALPHA.fullmatch(w):
                return True
            alpha = ''.join(c for c in w if c.isalpha())
            if len(alpha) < 4:
                return False
            vowels = sum(1 for c in alpha if c in _VOWELS)
            # Zero vowels (y counts) in word >= 5 chars
            if vowels == 0 and len(alpha) >= 5:
                return True
            # Very low vowel ratio in long words
            if vowels / len(alpha) < 0.10 and len(alpha) >= 8:
                return True
            # 5+ consecutive consonants in words >= 6 chars
            if len(alpha) >= 6 and _CONSONANT_RUN.search(alpha):
                return True
            return False

        words = raw_text.split()
        if words:
            garble_score = sum(1 for w in words if _is_garbled(w)) / len(words)
            if garble_score < 0.05:  # fewer than 5% tokens garbled → skip
                logger.debug(
                    "image_ocr: clean pass skipped for %s (garble_score=%.3f)",
                    filename, garble_score,
                )
                return raw_text

    # Prefer Groq for speed (sub-second for this small task); fall back to Azure OpenAI
    api_key = os.environ.get("GROQ_API_KEY", "")
    if api_key and not api_key.startswith("your-"):
        try:
            from openai import OpenAI
            client = OpenAI(base_url="https://api.groq.com/openai/v1", api_key=api_key)
            resp = client.chat.completions.create(
                model=os.environ.get("GROQ_TEXT_MODEL", "llama-3.3-70b-versatile"),
                messages=[
                    {"role": "system", "content": _OCR_CLEAN_SYSTEM},
                    {"role": "user",   "content": _OCR_CLEAN_USER.format(raw_text=raw_text[:6000])},
                ],
                max_tokens=min(len(raw_text.split()) * 3, 4096),
                temperature=0,
            )
            cleaned = resp.choices[0].message.content.strip()
            if cleaned and len(cleaned) > 20:
                logger.info("image_ocr: clean pass applied to %s (%d→%d chars)", filename, len(raw_text), len(cleaned))
                return cleaned
        except Exception as exc:
            logger.warning("image_ocr: clean pass failed for %s: %s — using raw OCR", filename, exc)

    # Azure OpenAI fallback
    azure_ep  = os.environ.get("AZURE_OPENAI_ENDPOINT", "")
    azure_key = os.environ.get("AZURE_OPENAI_API_KEY", "")
    azure_dep = os.environ.get("AZURE_OPENAI_DEPLOYMENT", "gpt-4o")
    if azure_ep and azure_key and "placeholder" not in azure_ep.lower():
        try:
            from openai import AzureOpenAI
            client = AzureOpenAI(
                azure_endpoint=azure_ep,
                api_key=azure_key,
                api_version=os.environ.get("AZURE_OPENAI_API_VERSION", "2024-10-21"),
            )
            resp = client.chat.completions.create(
                model=azure_dep,
                messages=[
                    {"role": "system", "content": _OCR_CLEAN_SYSTEM},
                    {"role": "user",   "content": _OCR_CLEAN_USER.format(raw_text=raw_text[:6000])},
                ],
                max_tokens=min(len(raw_text.split()) * 3, 4096),
                temperature=0,
            )
            cleaned = resp.choices[0].message.content.strip()
            if cleaned and len(cleaned) > 20:
                logger.info("image_ocr: Azure clean pass applied to %s", filename)
                return cleaned
        except Exception as exc:
            logger.warning("image_ocr: Azure clean pass failed for %s: %s", filename, exc)

    return raw_text


def _format_section(text: str, filename: str) -> str:
    name = Path(filename).stem
    return f"--- Page: {name} ---\n{text.strip()}\n"


# ── Azure AI Vision ──────────────────────────────────────────────────────────

def _vision_configured() -> bool:
    ep  = os.environ.get("AZURE_VISION_ENDPOINT", "")
    key = os.environ.get("AZURE_VISION_KEY", "")
    return bool(ep and key
                and "placeholder" not in ep.lower()
                and "your-" not in key.lower())


def _ocr_with_azure_vision(image_bytes: bytes, filename: str) -> str:
    """
    Use Azure AI Vision Read OCR API to extract text from an image.
    Returns extracted text or empty string on failure.
    This is synchronous; callers in async context must use asyncio.to_thread().
    """
    if not _vision_configured():
        return ""
    try:
        from azure.ai.vision.imageanalysis import ImageAnalysisClient
        from azure.ai.vision.imageanalysis.models import VisualFeatures
        from azure.core.credentials import AzureKeyCredential

        endpoint = os.environ.get("AZURE_VISION_ENDPOINT", "").rstrip("/")
        key      = os.environ.get("AZURE_VISION_KEY", "")

        data, _ = _resize(image_bytes, max_px=4096)   # Vision supports up to 4096px
        client = ImageAnalysisClient(endpoint=endpoint, credential=AzureKeyCredential(key))
        result = client.analyze(
            image_data=data,
            visual_features=[VisualFeatures.READ],
        )
        if not result.read or not result.read.blocks:
            return ""
        lines = []
        for block in result.read.blocks:
            for line in block.lines:
                lines.append(line.text)
        text = "\n".join(lines).strip()
        logger.info("Azure Vision OCR: extracted %d chars from %s", len(text), filename)
        return text
    except Exception as e:
        logger.warning("Azure Vision OCR failed for %s: %s", filename, e)
        return ""


def _describe_with_azure_vision(image_bytes: bytes, source_label: str) -> str:
    """
    Use Azure AI Vision dense captioning + tag analysis to describe a slide figure.
    Returns a concise description string or empty string on failure.
    Synchronous — wrap with asyncio.to_thread() in async contexts.
    """
    if not _vision_configured():
        return ""
    try:
        from azure.ai.vision.imageanalysis import ImageAnalysisClient
        from azure.ai.vision.imageanalysis.models import VisualFeatures
        from azure.core.credentials import AzureKeyCredential

        endpoint = os.environ.get("AZURE_VISION_ENDPOINT", "").rstrip("/")
        key      = os.environ.get("AZURE_VISION_KEY", "")

        data, _ = _resize(image_bytes, max_px=1024)
        client = ImageAnalysisClient(endpoint=endpoint, credential=AzureKeyCredential(key))
        result = client.analyze(
            image_data=data,
            visual_features=[VisualFeatures.DENSE_CAPTIONS, VisualFeatures.TAGS],
        )

        parts = []
        # Primary: dense caption (highest confidence first)
        if result.dense_captions and result.dense_captions.list:
            top = max(result.dense_captions.list, key=lambda c: c.confidence or 0)
            if top.text:
                parts.append(top.text.rstrip("."))

        # Supplement with top relevant tags (skip generic ones)
        _SKIP_TAGS = {"screenshot", "text", "font", "white", "black", "line", "number",
                      "diagram", "image", "photo", "illustration"}
        if result.tags and result.tags.list:
            good_tags = [
                t.name for t in result.tags.list
                if (t.confidence or 0) > 0.7 and t.name.lower() not in _SKIP_TAGS
            ]
            if good_tags:
                parts.append("Showing: " + ", ".join(good_tags[:5]))

        desc = ". ".join(parts).strip() if parts else ""
        if desc:
            logger.info("Azure Vision describe: '%s' → %s", source_label, desc[:80])
        return desc
    except Exception as e:
        logger.warning("Azure Vision describe failed for %s: %s", source_label, e)
        return ""


# ── Groq vision fallback ─────────────────────────────────────────────────────

def _ocr_with_groq(image_bytes: bytes, filename: str) -> str:
    api_key = os.environ.get("GROQ_API_KEY", "")
    if not api_key or api_key.startswith("your-"):
        return ""
    fname_lower = filename.lower()
    if fname_lower.endswith(('.heic', '.heif')):
        image_bytes, mime = _convert_heic(image_bytes)
    else:
        image_bytes, mime = _resize(image_bytes)
    mime = _detect_mime(image_bytes)
    b64  = base64.b64encode(image_bytes).decode()
    try:
        from openai import OpenAI
        client = OpenAI(base_url="https://api.groq.com/openai/v1", api_key=api_key)
        model  = os.environ.get("GROQ_VISION_MODEL", "meta-llama/llama-4-scout-17b-16e-instruct")
        resp = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": _OCR_SYSTEM},
                {"role": "user", "content": [
                    {"type": "text", "text": _OCR_PROMPT},
                    {"type": "image_url", "image_url": {
                        "url": f"data:{mime};base64,{b64}", "detail": "high",
                    }},
                ]},
            ],
            max_tokens=4096, temperature=0.1,
        )
        text = resp.choices[0].message.content.strip()
        logger.info("Groq OCR: extracted %d chars from %s", len(text), filename)
        return text
    except Exception as e:
        logger.warning("Groq OCR failed for %s: %s", filename, e)
        return ""


def _describe_with_groq(image_bytes: bytes, source_label: str) -> str:
    api_key = os.environ.get("GROQ_API_KEY", "")
    if not api_key or api_key.startswith("your-"):
        return ""
    data, mime = _resize(image_bytes, max_px=1024)
    mime = _detect_mime(data)
    b64  = base64.b64encode(data).decode()
    try:
        from openai import OpenAI
        client = OpenAI(base_url="https://api.groq.com/openai/v1", api_key=api_key)
        model  = os.environ.get("GROQ_VISION_MODEL", "meta-llama/llama-4-scout-17b-16e-instruct")
        resp = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "user", "content": [
                    {"type": "text", "text": _DESCRIBE_PROMPT},
                    {"type": "image_url", "image_url": {
                        "url": f"data:{mime};base64,{b64}",
                        "detail": "high",   # high detail captures labels, equations, small text
                    }},
                ]},
            ],
            max_tokens=200,   # enough for 80 words + breathing room
            temperature=0.1,
        )
        desc = resp.choices[0].message.content.strip()
        # Strip common filler openers the model sometimes adds despite instructions
        for prefix in ("This image shows", "This diagram shows", "This figure shows",
                       "The image shows", "The diagram shows", "The figure depicts",
                       "The figure shows"):
            if desc.lower().startswith(prefix.lower()):
                desc = desc[len(prefix):].strip()
                if desc.startswith((",", ".", ":")):
                    desc = desc[1:].strip()
                break
        logger.info("Groq describe: '%s' → %s", source_label, desc[:100])
        return desc
    except Exception as e:
        logger.warning("Groq describe failed for %s: %s", source_label, e)
        return ""


# ── pytesseract fallback ─────────────────────────────────────────────────────

def _ocr_with_tesseract(image_bytes: bytes, filename: str) -> str:
    try:
        import pytesseract
        from PIL import Image
        img = Image.open(io.BytesIO(image_bytes))
        w, h = img.size
        if max(w, h) < 1200:
            scale = 1200 / max(w, h)
            img = img.resize((int(w * scale), int(h * scale)), Image.LANCZOS)
        text = pytesseract.image_to_string(img, config='--psm 6 --oem 3').strip()
        if text:
            logger.info("tesseract: extracted %d chars from %s", len(text), filename)
        return text
    except ImportError:
        return ""
    except Exception as e:
        logger.warning("tesseract failed for %s: %s", filename, e)
        return ""


# ── Public API ────────────────────────────────────────────────────────────────

def extract_text_from_image(image_bytes: bytes, filename: str) -> str:
    """
    Azure AI Vision OCR → Groq vision → tesseract → placeholder.
    SYNCHRONOUS — callers in async context must use asyncio.to_thread().
    """
    # 1. Azure AI Vision (preferred — highest quality OCR)
    text = _ocr_with_azure_vision(image_bytes, filename)
    if text and len(text.strip()) > 30:
        return _format_section(_clean_ocr_text(text, filename), filename)

    # 2. Groq vision
    text = _ocr_with_groq(image_bytes, filename)
    if text and len(text.strip()) > 30:
        return _format_section(_clean_ocr_text(text, filename), filename)

    # 3. pytesseract (most likely to produce garbled output — always clean regardless of heuristic)
    text = _ocr_with_tesseract(image_bytes, filename)
    if text and len(text.strip()) > 30:
        return _format_section(_clean_ocr_text(text, filename, always_clean=True), filename)

    # 4. Placeholder
    name = Path(filename).stem
    logger.warning("image_ocr: no text from %s — placeholder used", filename)
    return (
        f"--- Page: {name} ---\n"
        f"[Image '{filename}': text extraction unavailable. "
        "Configure AZURE_VISION_ENDPOINT or GROQ_API_KEY to enable OCR.]\n"
    )


def describe_slide_image(image_bytes: bytes, source_label: str = "") -> str:
    """
    Describe a slide figure for injection into study notes.

    Priority order:
      1. Groq vision (LLM — understands academic diagrams, labels, equations)
      2. Azure AI Vision dense captions (CV tags — weaker on academic content,
         but still useful when Groq is unavailable)
      3. Generic fallback

    NOTE: Groq is tried FIRST even when Azure is configured. Azure's dense
    captions API is a computer-vision tagger that produces generic output like
    "a diagram with arrows and boxes" — not useful for academic figures. Groq's
    llama-4-scout reads the actual image and produces specific descriptions
    like "block diagram of a PID controller showing proportional, integral, and
    derivative paths feeding into a summing junction". That meaningful context
    is what the note generator needs to incorporate the image correctly.

    SYNCHRONOUS — callers in async context must use asyncio.to_thread().
    """
    # 1. Groq vision (preferred for academic content — LLM understands diagrams)
    desc = _describe_with_groq(image_bytes, source_label)
    if desc:
        return desc

    # 2. Azure AI Vision dense captions (fallback when Groq unavailable)
    desc = _describe_with_azure_vision(image_bytes, source_label)
    if desc:
        return desc

    # 3. Generic fallback
    return f"Figure from {source_label}" if source_label else "Figure"
