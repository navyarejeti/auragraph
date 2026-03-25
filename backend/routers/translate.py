"""
routers/translate.py — LLM-powered academic translation.

Uses GPT-4o / Groq to translate academic notes intelligently:
- Preserves LaTeX math formulas exactly
- Uses correct domain-specific terminology in target language
- Writes natural, fluent prose (not word-for-word substitution)
- Keeps widely-known English technical terms where no equivalent exists
- Calibrated for Indian academic audiences

Azure Translator is NOT used here because it produces mechanical
word-for-word output that loses academic meaning and reads poorly.
GPT-4o understands the subject and produces human-quality translation.

Fallback: if Azure OpenAI unavailable, tries Groq.
"""
from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel, Field

import deps
from deps import get_current_user, _check_llm_rate_limit

logger = logging.getLogger("auragraph")
router = APIRouter(tags=["translate"])

SUPPORTED_LANGUAGES = [
    {"code": "hi", "name": "Hindi",     "native": "हिंदी",     "flag": "🇮🇳"},
    {"code": "te", "name": "Telugu",    "native": "తెలుగు",    "flag": "🇮🇳"},
    {"code": "ta", "name": "Tamil",     "native": "தமிழ்",     "flag": "🇮🇳"},
    {"code": "mr", "name": "Marathi",   "native": "मराठी",     "flag": "🇮🇳"},
    {"code": "bn", "name": "Bengali",   "native": "বাংলা",     "flag": "🇮🇳"},
    {"code": "kn", "name": "Kannada",   "native": "ಕನ್ನಡ",    "flag": "🇮🇳"},
    {"code": "ml", "name": "Malayalam", "native": "മലയാളം",   "flag": "🇮🇳"},
]

_LANG_NAME = {l["code"]: f"{l['name']} ({l['native']})" for l in SUPPORTED_LANGUAGES}

_TRANSLATE_SYSTEM = """\
You are an expert academic translator specialising in engineering, mathematics,
physics, and science subjects. You translate study notes for Indian university students.

TRANSLATION RULES (follow exactly):
1. Translate into natural, fluent {target_language} — as if a knowledgeable professor
   wrote these notes originally in {target_language}. NOT word-for-word substitution.
2. Preserve ALL LaTeX formulas exactly as-is. Do not translate or modify anything
   inside $...$ or $$...$$ delimiters.
3. Keep Markdown structure intact: ## headings, **bold**, *italic*, bullet points,
   numbered lists, blockquotes (> ...), tables.
4. Technical terms: use the standard {target_language} academic terminology where
   it exists. For terms with no common equivalent (e.g. "Fourier transform",
   "eigenvalue", "convolution", "bandwidth"), keep the English term — do NOT
   transliterate blindly. A student reading "फोर्ये ट्रांसफॉर्म" learns nothing;
   "Fourier transform" is universally understood.
5. Explanatory phrases, analogies, examples, and context: translate these fully
   and naturally — this is where your translation adds the most value.
6. Do NOT add any translator's note, preamble, or explanation. Output only the
   translated note text.
"""

_TRANSLATE_USER = """\
Translate the following academic study notes into {target_language}.

{note_text}
"""


class TranslateRequest(BaseModel):
    text:        str = Field(..., min_length=1, max_length=8000)
    target_lang: str = "hi"
    source_lang: str = "en"


@router.get("/api/translate/languages")
async def list_languages():
    llm_ready = deps._is_azure_available() or deps._is_groq_available()
    return {
        "languages": SUPPORTED_LANGUAGES,
        "llm_ready": llm_ready,
    }


@router.post("/api/translate")
async def translate_text(
    req: TranslateRequest,
    authorization: Optional[str] = Header(None),
):
    """
    Translate academic notes using GPT-4o for natural, context-aware output.
    Falls back to Groq if Azure OpenAI is unavailable.
    """
    try:
        user = get_current_user(authorization)
        _check_llm_rate_limit(user["id"])
    except HTTPException:
        user = {"id": "demo"}

    lang_name = _LANG_NAME.get(req.target_lang, req.target_lang)

    system = _TRANSLATE_SYSTEM.format(target_language=lang_name)
    user_msg = _TRANSLATE_USER.format(
        target_language=lang_name,
        note_text=req.text[:7000],
    )
    messages = [
        {"role": "system", "content": system},
        {"role": "user",   "content": user_msg},
    ]

    translated = None

    if deps._is_azure_available():
        try:
            translated = await deps._azure_chat(messages, max_tokens=4000)
        except Exception as e:
            logger.warning("translate: Azure failed: %s", e)

    if not translated and deps._is_groq_available():
        try:
            translated = await deps._groq_chat(messages, max_tokens=4000)
        except Exception as e:
            logger.warning("translate: Groq failed: %s", e)

    if not translated:
        raise HTTPException(
            503,
            "Translation unavailable — LLM service unreachable. "
            "Check AZURE_OPENAI_API_KEY or GROQ_API_KEY in .env."
        )

    return {"translated": translated, "target_lang": req.target_lang}
