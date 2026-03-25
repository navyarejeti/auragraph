"""
routers/tts.py — Text-to-Speech via Azure Cognitive Services Speech Service.

Uses Azure Neural TTS voices — these are human-quality voices trained on real
speech data, not traditional concatenative TTS. They are indistinguishable from
human speech in blind listening tests.

Supported voices:
  Indian English  → Neerja (F), Prabhat (M)     — en-IN
  American English→ Aria (F),   Guy (M)          — en-US
  Hindi           → Swara (F),  Madhur (M)        — hi-IN
  Telugu          → Shruti (F), Mohan (M)         — te-IN
  Tamil           → Pallavi (F),Valluvar (M)      — ta-IN

Endpoint:  POST /api/tts
Returns:   audio/mpeg (MP3) stream
"""
from __future__ import annotations

import logging
import os
import re
import html as _html
from typing import Optional

from fastapi import APIRouter, Header, HTTPException, Query
from fastapi.responses import Response, StreamingResponse
from pydantic import BaseModel, Field

from deps import get_current_user

logger = logging.getLogger("auragraph")
router = APIRouter(tags=["tts"])

# ── Voice registry ─────────────────────────────────────────────────────────────
# Azure Neural voices — all rated 4-5/5 for naturalness in Microsoft's benchmarks.
# Using "neural" suffix for highest quality. Each voice has been chosen for
# clarity and warmth specifically for educational/reading contexts.

VOICES = {
    "en-IN-F": {"name": "en-IN-NeerjaNeural",       "lang": "en-IN", "label": "Neerja (Indian English ♀)", "flag": "🇮🇳"},
    "en-IN-M": {"name": "en-IN-PrabhatNeural",       "lang": "en-IN", "label": "Prabhat (Indian English ♂)", "flag": "🇮🇳"},
    "en-US-F": {"name": "en-US-AriaNeural",          "lang": "en-US", "label": "Aria (American English ♀)", "flag": "🇺🇸"},
    "en-US-M": {"name": "en-US-GuyNeural",           "lang": "en-US", "label": "Guy (American English ♂)",  "flag": "🇺🇸"},
    "hi-IN-F": {"name": "hi-IN-SwaraNeural",         "lang": "hi-IN", "label": "Swara (Hindi ♀)",           "flag": "🇮🇳"},
    "hi-IN-M": {"name": "hi-IN-MadhurNeural",        "lang": "hi-IN", "label": "Madhur (Hindi ♂)",          "flag": "🇮🇳"},
    "te-IN-F": {"name": "te-IN-ShrutiNeural",        "lang": "te-IN", "label": "Shruti (Telugu ♀)",         "flag": "🇮🇳"},
    "te-IN-M": {"name": "te-IN-MohanNeural",         "lang": "te-IN", "label": "Mohan (Telugu ♂)",          "flag": "🇮🇳"},
    "ta-IN-F": {"name": "ta-IN-PallaviNeural",       "lang": "ta-IN", "label": "Pallavi (Tamil ♀)",         "flag": "🇮🇳"},
    "ta-IN-M": {"name": "ta-IN-ValluvarNeural",      "lang": "ta-IN", "label": "Valluvar (Tamil ♂)",        "flag": "🇮🇳"},
}
DEFAULT_VOICE = "en-IN-F"


class TTSRequest(BaseModel):
    text:    str  = Field(..., min_length=1, max_length=8000)
    voice:   str  = DEFAULT_VOICE
    rate:    str  = "0%"    # e.g. "-10%", "0%", "+10%", "+20%"
    pitch:   str  = "0%"    # e.g. "-5%", "0%"


def _clean_text_for_tts(text: str) -> str:
    """
    Strip Markdown, LaTeX, and special characters that would be read aloud
    verbatim and sound terrible (e.g. "dollar sign x caret 2 dollar sign").
    """
    # Remove LaTeX display math blocks entirely (read as "[formula]")
    text = re.sub(r'\$\$[\s\S]*?\$\$', ' formula. ', text)
    # Remove inline LaTeX — replace with a brief spoken cue
    text = re.sub(r'\$[^$\n]{1,80}\$', ' formula ', text)
    # Remove LaTeX \commands
    text = re.sub(r'\\[a-zA-Z]+(?:\{[^}]*\})*', ' ', text)
    # Remove Markdown headings markers but keep the text
    text = re.sub(r'^#{1,6}\s+', '', text, flags=re.MULTILINE)
    # Remove Markdown bold/italic markers
    text = re.sub(r'\*{1,3}([^*]+)\*{1,3}', r'\1', text)
    text = re.sub(r'_{1,2}([^_]+)_{1,2}', r'\1', text)
    # Remove code blocks
    text = re.sub(r'```[\s\S]*?```', ' [code block] ', text)
    text = re.sub(r'`[^`]+`', ' code ', text)
    # Remove Markdown links — keep link text
    text = re.sub(r'\[([^\]]+)\]\([^)]+\)', r'\1', text)
    # Remove blockquote markers
    text = re.sub(r'^>\s*', '', text, flags=re.MULTILINE)
    # Remove horizontal rules
    text = re.sub(r'^[-*_]{3,}\s*$', '. ', text, flags=re.MULTILINE)
    # Collapse multiple spaces/newlines
    text = re.sub(r'\n{3,}', '\n\n', text)
    text = re.sub(r' {2,}', ' ', text)
    # Escape XML special chars for SSML
    text = _html.escape(text)
    return text.strip()


def _build_ssml(text: str, voice_key: str, rate: str, pitch: str) -> str:
    """Build SSML markup for Azure Speech Service."""
    voice = VOICES.get(voice_key, VOICES[DEFAULT_VOICE])
    clean  = _clean_text_for_tts(text)
    # Clamp rate to safe range
    rate_val = max(-30, min(50, int(rate.replace('%','') or 0)))
    rate_str = f"{'+' if rate_val >= 0 else ''}{rate_val}%"
    return f"""<speak version='1.0' xml:lang='{voice['lang']}'>
  <voice name='{voice['name']}'>
    <prosody rate='{rate_str}' pitch='{pitch}'>
      {clean}
    </prosody>
  </voice>
</speak>"""


def _speech_configured() -> bool:
    key    = os.environ.get("AZURE_SPEECH_KEY", "")
    region = os.environ.get("AZURE_SPEECH_REGION", "")
    return bool(key and region
                and not key.startswith("your-")
                and not region.startswith("your-"))


async def _call_azure_tts(ssml: str) -> bytes:
    """Call Azure Speech REST API and return raw MP3 bytes."""
    key    = os.environ.get("AZURE_SPEECH_KEY", "")
    region = os.environ.get("AZURE_SPEECH_REGION", "")
    url = f"https://{region}.tts.speech.microsoft.com/cognitiveservices/v1"
    headers = {
        "Ocp-Apim-Subscription-Key": key,
        "Content-Type": "application/ssml+xml",
        "X-Microsoft-OutputFormat": "audio-24khz-96kbitrate-mono-mp3",
        "User-Agent": "AuraGraph/1.0",
    }
    import httpx
    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.post(url, headers=headers, content=ssml.encode("utf-8"))
        if resp.status_code != 200:
            logger.warning("Azure TTS failed: %d %s", resp.status_code, resp.text[:200])
            raise HTTPException(502, f"Azure Speech Service error: {resp.status_code}")
        return resp.content


@router.get("/api/tts/voices")
async def list_voices():
    """Return available voices — no auth required."""
    return {
        "voices": [
            {"key": k, **{f: v[f] for f in ("name","lang","label","flag")}}
            for k, v in VOICES.items()
        ],
        "default": DEFAULT_VOICE,
        "azure_configured": _speech_configured(),
    }


@router.post("/api/tts")
async def synthesize_speech(
    req: TTSRequest,
    authorization: Optional[str] = Header(None),
):
    """
    Synthesize text to speech using Azure Neural TTS.
    Returns MP3 audio bytes.
    Falls back to a JSON error if Azure Speech is not configured.
    """
    # Auth check — any logged-in user can use TTS
    try:
        get_current_user(authorization)
    except HTTPException:
        pass  # Allow demo users

    if not _speech_configured():
        raise HTTPException(
            503,
            "Azure Speech Service is not configured. "
            "Add AZURE_SPEECH_KEY and AZURE_SPEECH_REGION to .env"
        )

    if req.voice not in VOICES:
        req.voice = DEFAULT_VOICE

    ssml  = _build_ssml(req.text, req.voice, req.rate, req.pitch)
    audio = await _call_azure_tts(ssml)

    return Response(
        content=audio,
        media_type="audio/mpeg",
        headers={
            "Cache-Control": "private, max-age=3600",
            "Content-Length": str(len(audio)),
        },
    )
