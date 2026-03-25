"""
agents/media_ingest.py — Media Ingestion: Video/Audio/Transcript → Slide Text
═══════════════════════════════════════════════════════════════════════════════

Converts class recordings, video links, audio files, and raw transcripts into
a text format that the existing fuse pipeline treats as lecture slide content.

Supported input types:
  1. YouTube / video URL   → extract auto-captions via yt-dlp; if unavailable,
                             download audio and transcribe via Azure Whisper
  2. Audio file upload     → transcribe via Azure OpenAI Whisper
  3. Raw transcript text   → clean and structure directly

Output: a list of text "slides" (chunks ≤ 800 words each) ready to pass into
        store_source_chunks() as slide_chunks.
"""
from __future__ import annotations

import logging
import os
import re
import tempfile
import textwrap
from pathlib import Path
from typing import Optional

logger = logging.getLogger("auragraph")

_WHISPER_AVAILABLE = bool(
    os.environ.get("AZURE_OPENAI_ENDPOINT") and
    os.environ.get("AZURE_OPENAI_API_KEY")
)

# ── YouTube / video URL ───────────────────────────────────────────────────────

def extract_youtube_transcript(url: str) -> Optional[str]:
    """
    Try to get auto-generated captions from a YouTube / video URL via yt-dlp.
    Returns the raw transcript text, or None if unavailable.
    Falls back gracefully — never raises.
    """
    try:
        import yt_dlp  # type: ignore
    except ImportError:
        logger.warning("yt-dlp not installed — cannot extract YouTube transcript")
        return None

    with tempfile.TemporaryDirectory() as tmpdir:
        ydl_opts = {
            "writeautomaticsub": True,
            "writesubtitles": True,
            "subtitleslangs": ["en", "en-orig"],
            "subtitlesformat": "vtt",
            "skip_download": True,
            "outtmpl": str(Path(tmpdir) / "%(id)s.%(ext)s"),
            "quiet": True,
            "no_warnings": True,
        }
        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=True)
                video_id = info.get("id", "video")

            # Look for any .vtt subtitle file written
            vtt_files = list(Path(tmpdir).glob("*.vtt"))
            if not vtt_files:
                logger.info("No subtitles found for URL: %s", url)
                return None

            raw_vtt = vtt_files[0].read_text(encoding="utf-8", errors="ignore")
            return _clean_vtt(raw_vtt)

        except Exception as e:
            logger.warning("yt-dlp extraction failed for %s: %s", url, e)
            return None


def _clean_vtt(vtt: str) -> str:
    """Strip VTT metadata and timing, deduplicate overlapping captions."""
    lines = vtt.splitlines()
    text_lines: list[str] = []
    seen: set[str] = set()

    for line in lines:
        line = line.strip()
        # Skip header, timing lines, empty lines, NOTE blocks
        if not line or line.startswith("WEBVTT") or "-->" in line or line.startswith("NOTE"):
            continue
        # Strip inline formatting tags like <00:00:00.000><c>...</c>
        line = re.sub(r"<[^>]+>", "", line).strip()
        if line and line not in seen:
            seen.add(line)
            text_lines.append(line)

    return " ".join(text_lines)


async def transcribe_audio_azure(audio_bytes: bytes, filename: str) -> Optional[str]:
    """
    Transcribe audio using Azure OpenAI Whisper endpoint.
    Falls back gracefully if not configured.
    """
    endpoint = os.environ.get("AZURE_OPENAI_ENDPOINT", "").rstrip("/")
    api_key  = os.environ.get("AZURE_OPENAI_API_KEY", "")
    whisper_deployment = os.environ.get("AZURE_WHISPER_DEPLOYMENT", "whisper")

    if not endpoint or not api_key:
        logger.warning("Azure OpenAI not configured — cannot transcribe audio")
        return None

    try:
        import httpx
        url = f"{endpoint}/openai/deployments/{whisper_deployment}/audio/transcriptions?api-version=2024-02-01"
        async with httpx.AsyncClient(timeout=300.0) as client:
            resp = await client.post(
                url,
                headers={"api-key": api_key},
                files={"file": (filename, audio_bytes, "audio/mpeg")},
                data={"response_format": "text"},
            )
        if resp.status_code == 200:
            return resp.text.strip()
        logger.warning("Whisper transcription failed: HTTP %d — %s", resp.status_code, resp.text[:200])
        return None
    except Exception as e:
        logger.warning("Whisper transcription error: %s", e)
        return None


# ── Text cleaning & chunking ──────────────────────────────────────────────────

def clean_transcript(text: str) -> str:
    """
    Light cleaning of raw transcript text:
    - Collapse repeated whitespace
    - Remove timestamps like [00:12:34] or (00:12)
    - Normalise unicode quotation marks
    """
    # Remove common timestamp patterns
    text = re.sub(r'\[?\d{1,2}:\d{2}(?::\d{2})?\]?', '', text)
    text = re.sub(r'\(\d{1,2}:\d{2}(?::\d{2})?\)', '', text)
    # Remove speaker labels like "PROF:" or "Student:" at line start
    text = re.sub(r'^[A-Z][A-Z\s]{1,20}:\s*', '', text, flags=re.MULTILINE)
    # Normalise whitespace
    text = re.sub(r'\s+', ' ', text).strip()
    # Normalise quotes
    text = text.replace('\u2018', "'").replace('\u2019', "'").replace('\u201c', '"').replace('\u201d', '"')
    return text


def chunk_transcript(text: str, words_per_chunk: int = 600) -> list[str]:
    """
    Split transcript into chunks of ~600 words, breaking at sentence boundaries.
    Each chunk is formatted as a "slide" for the fuse pipeline.
    """
    if not text.strip():
        return []

    # Split into sentences
    sentences = re.split(r'(?<=[.!?])\s+', text)
    chunks: list[str] = []
    current: list[str] = []
    current_words = 0

    for sent in sentences:
        words = len(sent.split())
        if current_words + words > words_per_chunk and current:
            chunks.append(" ".join(current))
            current = [sent]
            current_words = words
        else:
            current.append(sent)
            current_words += words

    if current:
        chunks.append(" ".join(current))

    # Format each chunk as a labelled "slide"
    formatted = []
    for i, chunk in enumerate(chunks, 1):
        formatted.append(f"--- Lecture Recording Segment {i} ---\n{chunk}")

    return formatted


# ── Public API ────────────────────────────────────────────────────────────────

async def ingest_url(url: str) -> tuple[list[str], str]:
    """
    Ingest a video/audio URL.
    Returns (slide_chunks, source_description).
    """
    url = url.strip()
    if not url:
        return [], ""

    # Try transcript extraction first (fast, no audio download needed)
    transcript = extract_youtube_transcript(url)

    if transcript:
        cleaned = clean_transcript(transcript)
        chunks = chunk_transcript(cleaned)
        logger.info("URL ingested via captions: %d chunks from %s", len(chunks), url)
        return chunks, f"YouTube captions: {url}"

    # If no captions, return empty with a hint — audio download/transcription
    # requires significant compute; user should provide the transcript manually
    logger.info("No captions available for %s — transcript required", url)
    return [], "no_captions"


async def ingest_audio(audio_bytes: bytes, filename: str) -> tuple[list[str], str]:
    """
    Ingest an audio file by transcribing it via Azure Whisper.
    Returns (slide_chunks, source_description).
    """
    transcript = await transcribe_audio_azure(audio_bytes, filename)
    if not transcript:
        return [], ""
    cleaned = clean_transcript(transcript)
    chunks = chunk_transcript(cleaned)
    logger.info("Audio ingested: %d chunks from %s", len(chunks), filename)
    return chunks, f"Audio transcription: {filename}"


def ingest_transcript_text(text: str) -> tuple[list[str], str]:
    """
    Ingest raw transcript text (pasted or uploaded .txt).
    Returns (slide_chunks, source_description).
    """
    cleaned = clean_transcript(text)
    chunks = chunk_transcript(cleaned)
    logger.info("Transcript text ingested: %d chunks", len(chunks))
    return chunks, "Pasted transcript"
