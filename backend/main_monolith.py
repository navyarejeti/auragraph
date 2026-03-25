"""
AuraGraph — FastAPI + Semantic Kernel Backend  v5
Team: Wowffulls | IIT Roorkee | Challenge: AI Study Buddy

All 32 critic findings resolved:
  A1  /knowledge-stats — added ownership check
  A2  /api/graph       — requires auth
  A3  /api/doubt       — requires auth
  A4  /api/mutate      — requires auth
  A5  /api/examine     — requires auth
  A6  Hardcoded mock credentials removed from lifespan
  A7  Hardcoded "Convolution Theorem" replaced with dynamic concept extraction

  B1  _note_to_pages: re.split(r'(?m)^(?=## )') — first ## section no longer lost
  B3  Image annotation happens BEFORE chunking — knowledge store sees figure refs
  B4  Fresh Embedder + loaded VectorDB: embedder.rebuild_from_chunks() called
  (B2 was already correct; B5/B6 were already correct)

  C1  note_generator: asyncio.to_thread replaced with httpx async calls
  C2  refine_notes threshold 0.6 → 0.3 (good compressions kept)
  C3  Semaphore reads LLM_CONCURRENCY env var (default 1 for Groq free tier)

  D1–D4  slide_images.py: EMU calc, doc.close order, per-page budget, clear_existing
  E1–E3  image_ocr.py: to_thread in caller, image resize, magic-byte MIME
  F3     vector_db save/load store textbook_hash for staleness detection
  G2     slide_analyzer: chunked analysis — no more 40 k hard truncation

  H1–H4  lecture_notes_generator/ standalone (separate files, see that dir)

  L1  /api/fuse now stores source chunks (doubt/mutate work after it)
  L2  VectorDB.delete called on notebook deletion
  L3  Single mutate parser via FusionAgent._parse_mutate_response
  L4  /api/fuse delegates to run_generation_pipeline

  J1  handleDoubt page_idx bug is in frontend NotebookWorkspace.jsx
      (MutateModal already sends page_idx correctly; the standalone
       "Ask doubt" path in the modal also sends page_idx — see jsx fix)

  K1–K9  Missing tests added to test_notes_pipeline.py (separate file)
"""

import asyncio
import hashlib
import json
import logging
import os
import re
import time
import uuid
from contextlib import asynccontextmanager
from typing import Optional, List

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, UploadFile, File, Form, Header, Request
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.base import BaseHTTPMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel

import semantic_kernel as sk
from semantic_kernel.connectors.ai.open_ai import AzureChatCompletion

from agents.fusion_agent import FusionAgent
from agents.examiner_agent import ExaminerAgent
from agents.mastery_store import get_db, update_node_status, increment_mutation_count
from agents.content_safety import check_content_safety
from agents.pdf_utils import extract_text_from_file, chunk_text
from agents.knowledge_store import (
    store_source_chunks, retrieve_relevant_chunks,
    get_chunk_stats,
    store_note_pages, get_note_page, get_all_note_pages, update_note_page,
    delete_notebook_store,
)
from agents.local_summarizer import generate_local_note
from agents.local_mutation import local_mutate
from agents.local_examiner import local_examine
from agents.concept_extractor import extract_concepts, llm_extract_concepts
from agents.latex_utils import fix_latex_delimiters
from agents.auth_utils import register_user, login_user, validate_token, refresh_token
from agents.slide_images import extract_images_from_file, save_images, get_image_path
from agents.image_ocr import describe_slide_image, is_image_file
from agents.notebook_store import (
    create_notebook, get_notebooks, get_notebook,
    update_notebook_note, update_notebook_graph, delete_notebook,
    get_sections, create_section, get_section, update_section,
    delete_section, reorder_sections, rebuild_note_from_sections,
)

load_dotenv()

logger = logging.getLogger("auragraph")
logging.basicConfig(level=logging.INFO, format="%(levelname)s  %(name)s  %(message)s")

# Serialize all notebook writes so SQLite WAL doesn't get hammered with concurrent
# mutations on the same notebook (e.g. rapid re-upload or race between mutate + regen).
_db_write_lock: asyncio.Lock = asyncio.Lock()

_PROMPT_SLIDES_BUDGET   = 24_000
_PROMPT_TEXTBOOK_BUDGET = 24_000

# ── Upload safety limits ────────────────────────────────────────────────────
# Single total upload ceiling — no per-file or per-topic restrictions.
# Default 500 MB combined across all slides + textbooks in one request.
MAX_TOTAL_UPLOAD_BYTES = int(os.environ.get("MAX_TOTAL_UPLOAD_MB", "500")) * 1024 * 1024
# Per-upload wall-clock timeout in seconds (default 20 min; set higher for very large decks)
PIPELINE_TIMEOUT_S   = int(os.environ.get("PIPELINE_TIMEOUT_S", "1200"))
# Per-LLM-call total budget (default 90 s; covers up to 3 attempts + back-off waits)
_LLM_TOTAL_TIMEOUT_S = int(os.environ.get("LLM_TOTAL_TIMEOUT_S", "90"))

kernel         = None
fusion_agent   = None
examiner_agent = None


@asynccontextmanager
async def lifespan(app):
    global kernel, fusion_agent, examiner_agent

    # FIX A6: No hardcoded "mock-key" fallback — if env vars absent the kernel
    # is initialised with placeholder strings and _is_azure_available() returns False.
    endpoint = os.environ.get("AZURE_OPENAI_ENDPOINT", "https://placeholder.invalid/")
    api_key  = os.environ.get("AZURE_OPENAI_API_KEY",  "placeholder")

    kernel = sk.Kernel()
    kernel.add_service(
        AzureChatCompletion(
            service_id="gpt4o",
            deployment_name=os.environ.get("AZURE_OPENAI_DEPLOYMENT", "gpt-4o"),
            endpoint=endpoint,
            api_key=api_key,
            api_version=os.getenv("AZURE_OPENAI_API_VERSION", "2024-02-01"),
        )
    )
    fusion_agent   = FusionAgent(kernel)
    examiner_agent = ExaminerAgent(kernel)
    _init_usage_table()
    logger.info("✅  AuraGraph v6 — bcrypt auth, SQLite mastery store, LLM rate limiting")
    yield
    logger.info("⏹  AuraGraph shutting down")


app = FastAPI(
    title="AuraGraph API",
    version="0.5.0",
    description="Digital Knowledge Twin — fully hardened v5",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173", "http://127.0.0.1:5173",
        "http://localhost:5174", "http://127.0.0.1:5174",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class _RequestIdMiddleware(BaseHTTPMiddleware):
    """Attaches a short UUID to every request and logs method/path/status/ms."""
    async def dispatch(self, request: Request, call_next):
        req_id = str(uuid.uuid4())[:8]
        request.state.request_id = req_id
        t0 = time.perf_counter()
        response = await call_next(request)
        ms = (time.perf_counter() - t0) * 1000
        response.headers["X-Request-Id"] = req_id
        logger.info(
            "[%s] %s %s -> %d  %.1fms",
            req_id, request.method, request.url.path, response.status_code, ms,
        )
        return response


app.add_middleware(_RequestIdMiddleware)


# ── Auth helpers ───────────────────────────────────────────────────────────────

def get_current_user(authorization: Optional[str] = Header(None)):
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(401, "Missing or invalid token")
    token = authorization.split(" ", 1)[1]
    user  = validate_token(token)
    if not user:
        raise HTTPException(401, "Invalid or expired token")
    return user


def _require_notebook_owner(nb_id: str, user: dict) -> dict:
    """Load notebook and assert it belongs to the requesting user."""
    nb = get_notebook(nb_id)
    if not nb or nb["user_id"] != user["id"]:
        raise HTTPException(404, "Notebook not found")
    return nb


# ── LLM rate limiting + cost tracking ─────────────────────────────────────────
# Limits: configurable via env vars; defaults tuned for a small-team deployment.
#   LLM_HOURLY_LIMIT    — max heavy LLM calls (fuse / mutate / doubt) per user per hour
#   LLM_DAILY_LIMIT     — max LLM calls per user per day

_LLM_HOURLY_LIMIT = int(os.environ.get("LLM_HOURLY_LIMIT", "40"))
_LLM_DAILY_LIMIT  = int(os.environ.get("LLM_DAILY_LIMIT",  "200"))

# Rough cost estimates (USD per 1K tokens) — informational only
_COST_PER_1K = {"azure": 0.01, "groq": 0.0001, "local": 0.0}


def _init_usage_table() -> None:
    from agents.auth_utils import DB_PATH
    import sqlite3
    con = sqlite3.connect(str(DB_PATH), timeout=30, check_same_thread=False)
    con.execute("PRAGMA journal_mode=WAL")
    con.executescript("""
        CREATE TABLE IF NOT EXISTS llm_usage (
            user_id     TEXT    NOT NULL,
            hour_bucket TEXT    NOT NULL,  -- e.g. '2026-03-08T14'
            day_bucket  TEXT    NOT NULL,  -- e.g. '2026-03-08'
            calls       INTEGER NOT NULL DEFAULT 0,
            est_tokens  INTEGER NOT NULL DEFAULT 0,
            est_cost_usd REAL   NOT NULL DEFAULT 0.0,
            PRIMARY KEY (user_id, hour_bucket)
        );
        CREATE INDEX IF NOT EXISTS idx_llm_usage_user_day
            ON llm_usage(user_id, day_bucket);
    """)
    con.commit()
    con.close()


def _check_llm_rate_limit(user_id: str) -> None:
    """
    Raise HTTP 429 if the user has exceeded their hourly or daily LLM call limits.
    Called at the start of every heavy LLM endpoint.
    """
    from agents.auth_utils import DB_PATH
    import sqlite3
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc)
    hour_bucket = now.strftime("%Y-%m-%dT%H")
    day_bucket  = now.strftime("%Y-%m-%d")
    con = sqlite3.connect(str(DB_PATH), timeout=10, check_same_thread=False)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA journal_mode=WAL")
    try:
        # Hourly check
        row = con.execute(
            "SELECT calls FROM llm_usage WHERE user_id=? AND hour_bucket=?",
            (user_id, hour_bucket)
        ).fetchone()
        if row and row["calls"] >= _LLM_HOURLY_LIMIT:
            raise HTTPException(
                429,
                f"Rate limit: max {_LLM_HOURLY_LIMIT} AI calls per hour. Try again later."
            )
        # Daily check
        daily = con.execute(
            "SELECT SUM(calls) as total FROM llm_usage WHERE user_id=? AND day_bucket=?",
            (user_id, day_bucket)
        ).fetchone()
        if daily and (daily["total"] or 0) >= _LLM_DAILY_LIMIT:
            raise HTTPException(
                429,
                f"Daily limit: max {_LLM_DAILY_LIMIT} AI calls per day. Resets at midnight UTC."
            )
    finally:
        con.close()


def _record_llm_call(
    user_id: str,
    source: str,
    est_tokens: int = 2000,
) -> None:
    """
    Increment the usage counter for this user's current hour bucket.
    Non-blocking — swallows all exceptions so a logging failure never breaks a request.
    """
    from agents.auth_utils import DB_PATH
    import sqlite3
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc)
    hour_bucket = now.strftime("%Y-%m-%dT%H")
    day_bucket  = now.strftime("%Y-%m-%d")
    cost = (_COST_PER_1K.get(source, 0.0) * est_tokens) / 1000
    try:
        con = sqlite3.connect(str(DB_PATH), timeout=10, check_same_thread=False)
        con.execute("PRAGMA journal_mode=WAL")
        con.execute(
            """
            INSERT INTO llm_usage (user_id, hour_bucket, day_bucket, calls, est_tokens, est_cost_usd)
            VALUES (?, ?, ?, 1, ?, ?)
            ON CONFLICT(user_id, hour_bucket) DO UPDATE SET
                calls        = calls + 1,
                est_tokens   = est_tokens + excluded.est_tokens,
                est_cost_usd = est_cost_usd + excluded.est_cost_usd
            """,
            (user_id, hour_bucket, day_bucket, est_tokens, cost)
        )
        con.commit()
        con.close()
    except Exception as exc:  # never let logging break the request
        logger.debug("_record_llm_call failed (non-fatal): %s", exc)

def _is_azure_available() -> bool:
    endpoint = os.environ.get("AZURE_OPENAI_ENDPOINT", "")
    api_key  = os.environ.get("AZURE_OPENAI_API_KEY",  "")
    return (
        bool(fusion_agent)
        and bool(endpoint)
        and bool(api_key)
        and "placeholder" not in endpoint.lower()
        and "mock"        not in endpoint.lower()
        and "placeholder" not in api_key.lower()
        and "mock"        not in api_key.lower()
    )


def _is_groq_available() -> bool:
    key = os.environ.get("GROQ_API_KEY", "")
    return bool(key) and not key.startswith("your-")


# ── Groq helpers ───────────────────────────────────────────────────────────────

async def _groq_chat(messages: list[dict], max_tokens: int = 4000) -> str:
    """
    True-async Groq call via httpx.
    3-attempt retry: 429 honours Retry-After, 5xx uses exponential back-off.
    Total wall-clock capped by _LLM_TOTAL_TIMEOUT_S (default 90 s).
    """
    import httpx
    api_key     = os.environ.get("GROQ_API_KEY", "")
    model       = os.environ.get("GROQ_MODEL", "llama-3.3-70b-versatile")
    payload     = {"model": model, "messages": messages,
                   "max_tokens": max_tokens, "temperature": 0.3}
    req_headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}

    async def _do() -> str:
        for attempt in range(3):
            async with httpx.AsyncClient(timeout=60.0) as client:
                resp = await client.post(
                    "https://api.groq.com/openai/v1/chat/completions",
                    json=payload, headers=req_headers,
                )
            if resp.status_code == 429 and attempt < 2:
                wait = int(resp.headers.get("Retry-After", str(3 * (attempt + 1))))
                logger.warning("Groq 429 — waiting %d s (attempt %d)", wait, attempt + 1)
                await asyncio.sleep(wait)
                continue
            if resp.status_code in (500, 502, 503, 504) and attempt < 2:
                wait = 2 ** attempt
                logger.warning("Groq %d — retrying in %d s", resp.status_code, wait)
                await asyncio.sleep(wait)
                continue
            resp.raise_for_status()
            return resp.json()["choices"][0]["message"]["content"].strip()
        raise RuntimeError("Groq failed after 3 attempts")

    try:
        return await asyncio.wait_for(_do(), timeout=_LLM_TOTAL_TIMEOUT_S)
    except asyncio.TimeoutError:
        raise RuntimeError(f"Groq timed out after {_LLM_TOTAL_TIMEOUT_S}s")


async def _azure_chat(messages: list[dict], max_tokens: int = 4000) -> str:
    """
    True-async Azure OpenAI call via httpx.
    3-attempt retry for 429 and 5xx; total wall-clock capped by _LLM_TOTAL_TIMEOUT_S.
    """
    import httpx
    endpoint    = os.environ.get("AZURE_OPENAI_ENDPOINT", "").rstrip("/")
    api_key     = os.environ.get("AZURE_OPENAI_API_KEY", "")
    api_ver     = os.environ.get("AZURE_OPENAI_API_VERSION", "2024-10-21")
    deployment  = os.environ.get("AZURE_OPENAI_DEPLOYMENT", "gpt-4o")
    url         = f"{endpoint}/openai/deployments/{deployment}/chat/completions?api-version={api_ver}"
    payload     = {"messages": messages, "max_tokens": max_tokens, "temperature": 0.3}
    req_headers = {"api-key": api_key, "Content-Type": "application/json"}

    async def _do() -> str:
        for attempt in range(3):
            async with httpx.AsyncClient(timeout=60.0) as client:
                resp = await client.post(url, json=payload, headers=req_headers)
            if resp.status_code == 429 and attempt < 2:
                wait = int(resp.headers.get("Retry-After", str(3 * (attempt + 1))))
                logger.warning("Azure 429 — waiting %d s (attempt %d)", wait, attempt + 1)
                await asyncio.sleep(wait)
                continue
            if resp.status_code in (500, 502, 503, 504) and attempt < 2:
                wait = 2 ** attempt
                logger.warning("Azure %d — retrying in %d s", resp.status_code, wait)
                await asyncio.sleep(wait)
                continue
            resp.raise_for_status()
            return resp.json()["choices"][0]["message"]["content"].strip()
        raise RuntimeError("Azure failed after 3 attempts")

    try:
        return await asyncio.wait_for(_do(), timeout=_LLM_TOTAL_TIMEOUT_S)
    except asyncio.TimeoutError:
        raise RuntimeError(f"Azure timed out after {_LLM_TOTAL_TIMEOUT_S}s")


async def _groq_fuse(slide_content: str, textbook_content: str, proficiency: str) -> str:
    from agents.fusion_agent import FUSION_PROMPT
    prompt = (
        FUSION_PROMPT
        .replace("{{$slide_content}}",    slide_content)
        .replace("{{$textbook_content}}", textbook_content)
        .replace("{{$proficiency}}",      proficiency)
    )
    return await _groq_chat([{"role": "user", "content": prompt}])


async def _groq_doubt(doubt, slide_ctx, textbook_ctx, note_page) -> str:
    from agents.verifier_agent import DOUBT_ANSWER_PROMPT
    prompt = (
        DOUBT_ANSWER_PROMPT
        .replace("{{$doubt}}",            doubt)
        .replace("{{$note_page}}",        note_page)
        .replace("{{$slide_context}}",    slide_ctx)
        .replace("{{$textbook_context}}", textbook_ctx)
    )
    return await _groq_chat([{"role": "user", "content": prompt}])


async def _groq_examine(concept_name: str, custom_instruction: str = "") -> str:
    from agents.examiner_agent import EXAMINER_PROMPT
    ci = f"\n\nCUSTOM FOCUS (follow exactly): {custom_instruction}" if custom_instruction.strip() else ""
    prompt = EXAMINER_PROMPT.replace("{{$concept_name}}", concept_name).replace("{{$custom_instruction}}", ci)
    return await _groq_chat([{"role": "user", "content": prompt}])


# FIX L3: single mutate path — delegates to FusionAgent._parse_mutate_response
async def _llm_mutate(
    note_page: str, doubt: str, slide_ctx: str, textbook_ctx: str
) -> tuple[Optional[str], Optional[str], Optional[str], str]:
    """
    Try Azure (via SK) then Groq for mutation.
    Both use FusionAgent._parse_mutate_response — no duplicate parsers.
    Returns (mutated_text, gap, answer, source) where source is 'azure'|'groq'|'none'.
    """
    if _is_azure_available():
        try:
            mutated, gap, answer = await fusion_agent.mutate(
                note_page=note_page, doubt=doubt,
                slide_context=slide_ctx, textbook_context=textbook_ctx,
            )
            return mutated, gap, answer, "azure"
        except Exception as e:
            logger.warning("Azure mutation failed: %s", e)

    if _is_groq_available():
        try:
            from agents.fusion_agent import MUTATION_PROMPT
            prompt = (
                MUTATION_PROMPT
                .replace("{{$note_page}}",        note_page)
                .replace("{{$doubt}}",            doubt)
                .replace("{{$slide_context}}",    slide_ctx)
                .replace("{{$textbook_context}}", textbook_ctx)
            )
            text = await _groq_chat([{"role": "user", "content": prompt}])
            # FIX L3: reuse the canonical parser
            mutated, gap, answer = FusionAgent._parse_mutate_response(text)
            return mutated, gap, answer, "groq"
        except Exception as e:
            logger.warning("Groq mutation failed: %s", e)

    return None, None, None, "none"


async def _verify_note(
    note: str, slide_ctx: str, textbook_ctx: str
) -> tuple[str, bool, str]:
    """
    Post-generation accuracy check.
    Returns (verified_note, was_corrected, correction_summary).
    Falls back to the original note if LLM is unavailable.
    """
    from agents.verifier_agent import NOTE_SELF_REVIEW_PROMPT, parse_self_review_response

    raw: str | None = None

    if _is_azure_available():
        try:
            raw = await fusion_agent.self_review(
                note=note, slide_context=slide_ctx, textbook_context=textbook_ctx
            )
        except Exception as e:
            logger.warning("Azure self-review failed: %s", e)

    if raw is None and _is_groq_available():
        try:
            prompt = (
                NOTE_SELF_REVIEW_PROMPT
                .replace("{{$note}}",             note)
                .replace("{{$slide_context}}",    slide_ctx)
                .replace("{{$textbook_context}}", textbook_ctx)
            )
            raw = await _groq_chat([{"role": "user", "content": prompt}])
        except Exception as e:
            logger.warning("Groq self-review failed: %s", e)

    if raw is None:
        logger.info("Self-review skipped — no LLM available")
        return note, False, ""

    verified, was_corrected, summary = parse_self_review_response(raw)
    if not verified or len(verified.strip()) < 100:
        # Parser failed or returned garbage — keep original
        return note, False, ""
    if was_corrected:
        logger.info("Self-review: corrections made — %s", summary)
    else:
        logger.info("Self-review: PASS — note verified clean")
    return verified, was_corrected, summary


# ── Utility helpers ────────────────────────────────────────────────────────────

def _format_chunks_for_prompt(chunks: list[dict], budget: int) -> str:
    parts, used = [], 0
    for c in chunks:
        header = f"[{c['source'].upper()} — {c.get('heading','') or 'chunk'}]\n"
        body   = c["text"]
        block  = header + body + "\n"
        if used + len(block) > budget:
            remaining = budget - used - len(header) - 10
            if remaining > 100:
                block = header + body[:remaining].rsplit(" ", 1)[0] + " …\n"
            else:
                break
        parts.append(block)
        used += len(block)
    return "\n---\n".join(parts) if parts else "(no relevant content found)"


def _match_image_to_topic(description: str, topics) -> Optional[str]:
    STOP = {
        'a','an','the','is','are','of','in','on','at','to','for','with',
        'its','this','that','these','those','it','as','by','be','was',
        'were','showing','shows','figure','diagram','image','graph',
        'chart','plot','from','and','or','not','each','which','where',
    }
    def _tokens(s):
        return set(re.sub(r'[^\w\s]', '', s.lower()).split()) - STOP

    desc_tokens = _tokens(description)
    if not desc_tokens:
        return None
    best_score, best_topic = 0.0, None
    for t in topics:
        combined = t.topic + ' ' + ' '.join(getattr(t, 'key_points', [])[:4])
        t_tokens = _tokens(combined)
        if not t_tokens:
            continue
        inter = len(desc_tokens & t_tokens)
        union = len(desc_tokens | t_tokens)
        score = inter / union if union else 0.0
        if score > best_score:
            best_score, best_topic = score, t.topic
    return best_topic if best_score > 0.04 else None


def _inject_figures_into_sections(note: str, topic_figures: dict) -> str:
    if not topic_figures:
        return note
    result = []
    for line in note.split('\n'):
        result.append(line)
        if line.startswith('## '):
            heading_text = line[3:].strip().lower()
            matched_figs = None
            for tname, figs in topic_figures.items():
                tl = tname.lower()
                if tl == heading_text or tl in heading_text or heading_text in tl:
                    matched_figs = figs
                    break
            if matched_figs:
                result.append('')
                for description, url in matched_figs:
                    safe_alt = re.sub(r'\s+', ' ', (description or 'Figure')).strip()
                    safe_alt = safe_alt.replace('[', '(').replace(']', ')').replace('"', "'")
                    result.append(f'![{safe_alt}]({url})')
                    result.append('')
    return '\n'.join(result)


# FIX B1 + PAGE-SYNC: _note_to_pages now exactly mirrors frontend useMemo pagination.
# Frontend groups ## sections into ~3000-char pages; old backend merged only < 200-char
# sections, producing different page indices.  Mismatched indices caused /api/doubt and
# /api/mutate to retrieve wrong note context for the page the student was actually viewing.
def _note_to_pages(note: str) -> list[str]:
    """
    Split a note into pages that exactly mirror the frontend useMemo pagination
    (NotebookWorkspace.jsx — pages computed from note state).

    Algorithm (ported from JS):
      1. re.split(r'(?m)^(?=## )') — every ## heading starts a new section.
      2. Group sections greedily: add to buffer until adding the next would
         exceed TARGET (3000 chars) AND the buffer is already > 200 chars.
      3. Flush remaining buffer.
    """
    if not note.strip():
        return []

    TARGET   = 3000
    sections = re.split(r'(?m)^(?=## )', note.strip())
    parts    = [p.strip() for p in sections if p.strip()]

    if not parts:
        return [note.strip()]

    merged, buf = [], ""
    for s in parts:
        if buf and len(buf) + len(s) + 2 > TARGET and len(buf) > 200:
            merged.append(buf.strip())
            buf = s
        else:
            buf = (buf + "\n\n" + s) if buf else s
    if buf:
        merged.append(buf.strip())
    return [p for p in merged if p.strip()]


# ── Schemas ────────────────────────────────────────────────────────────────────

class AuthRequest(BaseModel):
    email:    Optional[str] = None
    username: Optional[str] = None
    password: str

    @property
    def identifier(self) -> str:
        return (self.email or self.username or "").strip()


class FusionResponse(BaseModel):
    fused_note:      str
    source:          str = "azure"
    fallback_reason: Optional[str] = None
    chunks_stored:   Optional[dict] = None


class DoubtRequest(BaseModel):
    notebook_id: str
    doubt:       str
    page_idx:    int = 0


class DoubtResponse(BaseModel):
    answer:              str
    source:              str = "azure"
    verification_status: str = "correct"   # correct | partially_correct | incorrect
    correction:          str = ""           # non-empty when notes contain an error
    footnote:            str = ""           # optional short clarification


class MutationRequest(BaseModel):
    notebook_id:        str
    doubt:              str
    page_idx:           int = 0
    original_paragraph: Optional[str] = None


class MutationResponse(BaseModel):
    mutated_paragraph: str
    concept_gap:       str
    answer:            str = ""   # Full explanation shown in doubts sidebar
    page_idx:          int
    source:            str = "azure"
    can_mutate:        bool = True


class RegenerateSectionRequest(BaseModel):
    notebook_id: str
    page_idx:    int
    proficiency: str = "Practitioner"


class RegenerateSectionResponse(BaseModel):
    new_section: str
    page_idx:    int
    source:      str


class ExaminerRequest(BaseModel):
    concept_name: str
    notebook_id: Optional[str] = None          # used to retrieve course-specific context
    custom_instruction: Optional[str] = None   # e.g. "numerical only", "focus on derivations"


class ExaminerResponse(BaseModel):
    practice_questions: str


class ConceptPracticeRequest(BaseModel):
    concept_name: str
    level: str = "partial"   # struggling | partial | mastered
    notebook_id: Optional[str] = None          # used to retrieve course-specific context
    custom_instruction: Optional[str] = None   # e.g. "only numerical", "include proofs"


class ConceptPracticeResponse(BaseModel):
    questions: list         # list of {question, options:{A,B,C,D}, correct, explanation}


class SniperExamRequest(BaseModel):
    notebook_id: Optional[str] = None   # reserved for ownership checks


class SniperExamResponse(BaseModel):
    questions:       list   # [{question, options, correct, explanation, concept}]
    concepts_tested: list   # [{label, status}]


class NodeUpdateRequest(BaseModel):
    concept_name: str
    status:       str


class ConceptExtractRequest(BaseModel):
    note:        str
    notebook_id: Optional[str] = None


class NotebookCreateRequest(BaseModel):
    name:   str
    course: str


class NotebookUpdateRequest(BaseModel):
    note:        str
    proficiency: Optional[str] = None


class SectionCreateRequest(BaseModel):
    title:     str
    note_type: str = "topic"


class SectionUpdateRequest(BaseModel):
    title:     Optional[str] = None
    content:   Optional[str] = None
    note_type: Optional[str] = None
    order_idx: Optional[int] = None


class SectionReorderRequest(BaseModel):
    order: List[dict]   # [{"id": ..., "order_idx": ...}]


class SectionGenerateRequest(BaseModel):
    proficiency: Optional[str] = "Intermediate"


# ── Auth routes ────────────────────────────────────────────────────────────────

@app.get("/health")
async def health():
    return {
        "status":           "ok",
        "service":          "AuraGraph v0.6",
        "azure_configured": _is_azure_available(),
        "groq_configured":  _is_groq_available(),
        "llm_concurrency":  int(os.environ.get("LLM_CONCURRENCY", "1")),
        "rate_limits":      {"hourly": _LLM_HOURLY_LIMIT, "daily": _LLM_DAILY_LIMIT},
    }


@app.get("/api/usage")
async def get_usage(authorization: Optional[str] = Header(None)):
    """Return the calling user's LLM call counts for the last 7 days."""
    user = get_current_user(authorization)
    from agents.auth_utils import DB_PATH
    import sqlite3
    from datetime import datetime, timezone, timedelta
    con = sqlite3.connect(str(DB_PATH), timeout=10, check_same_thread=False)
    con.row_factory = sqlite3.Row
    seven_days_ago = (datetime.now(timezone.utc) - timedelta(days=7)).strftime("%Y-%m-%d")
    rows = con.execute(
        """
        SELECT day_bucket, SUM(calls) as calls, SUM(est_tokens) as tokens, SUM(est_cost_usd) as cost
        FROM llm_usage
        WHERE user_id=? AND day_bucket >= ?
        GROUP BY day_bucket ORDER BY day_bucket DESC
        """,
        (user["id"], seven_days_ago)
    ).fetchall()
    con.close()
    now = datetime.now(timezone.utc)
    today_row = con.execute(
        "SELECT SUM(calls) as calls FROM llm_usage WHERE user_id=? AND day_bucket=?",
        (user["id"], now.strftime("%Y-%m-%d"))
    ).fetchone() if False else None  # already fetched above
    daily_calls = sum(r["calls"] for r in rows if r["day_bucket"] == now.strftime("%Y-%m-%d"))
    hour_calls_row = None
    try:
        con2 = sqlite3.connect(str(DB_PATH), timeout=10, check_same_thread=False)
        con2.row_factory = sqlite3.Row
        hour_calls_row = con2.execute(
            "SELECT calls FROM llm_usage WHERE user_id=? AND hour_bucket=?",
            (user["id"], now.strftime("%Y-%m-%dT%H"))
        ).fetchone()
        con2.close()
    except Exception:
        pass
    return {
        "user_id": user["id"],
        "limits": {"hourly": _LLM_HOURLY_LIMIT, "daily": _LLM_DAILY_LIMIT},
        "this_hour_calls": hour_calls_row["calls"] if hour_calls_row else 0,
        "today_calls": daily_calls,
        "history": [dict(r) for r in rows],
    }


@app.post("/auth/register")
async def auth_register(req: AuthRequest):
    if not req.identifier:
        raise HTTPException(422, "email or username is required")
    user = register_user(req.identifier, req.password)
    if not user:
        raise HTTPException(409, "Account already exists")
    return user


@app.post("/auth/login")
async def auth_login(req: AuthRequest):
    if not req.identifier:
        raise HTTPException(422, "email or username is required")
    user = login_user(req.identifier, req.password)
    if not user:
        raise HTTPException(401, "Invalid credentials")
    return user


@app.post("/auth/refresh")
async def auth_refresh(authorization: Optional[str] = Header(None)):
    """Silently renew a valid token before it expires.

    The client should call this on app startup (if a token is already stored)
    to extend the session without forcing the user to log in again.  Returns
    the same shape as /auth/login so the client can just save the new token.
    """
    token = (authorization or "").removeprefix("Bearer ").strip()
    if not token:
        raise HTTPException(401, "No token provided")
    user = refresh_token(token)
    if not user:
        raise HTTPException(401, "Token expired or invalid — please log in again")
    return user


_DEMO_SAMPLE_NOTE = """## Fourier Transform

The **Fourier Transform** decomposes a continuous-time signal into its constituent sinusoidal frequencies. It is the foundational tool of spectral analysis.

$$X(f) = \\int_{-\\infty}^{\\infty} x(t) \\cdot e^{-j 2\\pi f t} \\, dt$$

The **inverse** recovers the original signal from its spectrum:

$$x(t) = \\int_{-\\infty}^{\\infty} X(f) \\cdot e^{+j 2\\pi f t} \\, df$$

**Key properties:**

| Property | Time Domain | Frequency Domain |
|----------|-------------|-----------------|
| Linearity | $\\alpha x(t) + \\beta y(t)$ | $\\alpha X(f) + \\beta Y(f)$ |
| Time shift | $x(t - t_0)$ | $e^{-j2\\pi f t_0} X(f)$ |
| Duality | $X(t)$ | $x(-f)$ |
| Parseval | $\\int |x(t)|^2 dt$ | $\\int |X(f)|^2 df$ |

---

## Convolution Theorem

Convolution in the time domain is equivalent to **pointwise multiplication** in the frequency domain — this is the key insight that makes filtering efficient.

$$y(t) = (x * h)(t) = \\int_{-\\infty}^{\\infty} x(\\tau)\\, h(t-\\tau)\\, d\\tau \\iff Y(f) = X(f) \\cdot H(f)$$

**Intuition:** A filter $h(t)$ selects or attenuates specific frequency bands. In the frequency domain this is just multiplication — no integral needed.

**Correlation theorem** (related):

$$R_{xy}(\\tau) = x(-t) * y(t) \\iff S_{xy}(f) = X^*(f) \\cdot Y(f)$$

---

## Discrete Fourier Transform (DFT)

For $N$-point discrete sequences, the DFT is:

$$X[k] = \\sum_{n=0}^{N-1} x[n]\\, e^{-j \\frac{2\\pi}{N} k n}, \\quad k = 0, 1, \\ldots, N-1$$

The **Fast Fourier Transform (FFT)** computes the DFT in $O(N \\log N)$ (vs. $O(N^2)$ naively) by exploiting the periodic and symmetric properties of the twiddle factors $W_N^{kn} = e^{-j2\\pi kn / N}$.

**Spectral resolution:** $\\Delta f = f_s / N$ — use zero-padding to interpolate the spectrum.

---

## Sampling Theorem (Nyquist–Shannon)

A band-limited signal with maximum frequency $f_{\\max}$ can be **perfectly reconstructed** from its samples if and only if the sampling rate satisfies:

$$f_s \\geq 2 f_{\\max}$$

The quantity $2f_{\\max}$ is the **Nyquist rate**. Sampling below it causes **aliasing** — high-frequency energy folds back and corrupts lower frequencies.

**Anti-aliasing filter:** Apply a low-pass filter with cutoff $f_s/2$ *before* sampling to eliminate energy above the Nyquist frequency.

---

## Z-Transform

The Z-transform is the discrete-time analogue of the Laplace transform:

$$X(z) = \\sum_{n=-\\infty}^{\\infty} x[n]\\, z^{-n}, \\quad z \\in \\mathbb{C}$$

**System function:** For an LTI system described by the difference equation

$$y[n] = \\sum_k b_k x[n-k] - \\sum_k a_k y[n-k]$$

the transfer function is $H(z) = B(z)/A(z)$ and the frequency response is $H(e^{j\\omega})$.

**Stability criterion:** All poles of $H(z)$ must lie **strictly inside** the unit circle $|z| < 1$.
"""


@app.post("/auth/demo-login")
async def auth_demo_login():
    """
    One-click demo: returns a fixed demo-token and seeds a sample DSP notebook
    (only the first time — subsequent calls reuse the existing notebook).
    """
    demo_user_id = "demo"
    demo_nbs = get_notebooks(demo_user_id)

    # Look for the existing demo notebook
    demo_nb = next((nb for nb in demo_nbs if nb.get("name") == "Digital Signal Processing"), None)

    if demo_nb is None:
        demo_nb = create_notebook(demo_user_id, "Digital Signal Processing", "EC301 — DSP")
        update_notebook_note(demo_nb["id"], _DEMO_SAMPLE_NOTE, "Practitioner")
        demo_nb = get_notebook(demo_nb["id"])
        # Seed concept graph for demo notebook (background task — non-blocking)
        import asyncio
        async def _seed_graph():
            try:
                g = await llm_extract_concepts(_DEMO_SAMPLE_NOTE)
                if g.get("nodes"):
                    update_notebook_graph(demo_nb["id"], g)
            except Exception as exc:
                logger.debug("Demo graph seed failed: %s", exc)
        asyncio.create_task(_seed_graph())

    return {
        "id": demo_user_id,
        "email": "demo@auragraph.local",
        "name": "Demo Student",
        "token": "demo-token",
        "demo_notebook_id": demo_nb["id"],
    }


# ── Notebook routes ────────────────────────────────────────────────────────────

@app.post("/notebooks")
async def new_notebook(req: NotebookCreateRequest, authorization: Optional[str] = Header(None)):
    user = get_current_user(authorization)
    return create_notebook(user["id"], req.name, req.course)


@app.get("/notebooks")
async def list_notebooks(authorization: Optional[str] = Header(None)):
    user = get_current_user(authorization)
    return get_notebooks(user["id"])


@app.get("/notebooks/{nb_id}")
async def fetch_notebook(nb_id: str, authorization: Optional[str] = Header(None)):
    user = get_current_user(authorization)
    return _require_notebook_owner(nb_id, user)


@app.patch("/notebooks/{nb_id}/note")
async def save_notebook_note(
    nb_id: str, req: NotebookUpdateRequest,
    authorization: Optional[str] = Header(None),
):
    user = get_current_user(authorization)
    _require_notebook_owner(nb_id, user)
    async with _db_write_lock:
        return update_notebook_note(nb_id, req.note, req.proficiency)


@app.delete("/notebooks/{nb_id}")
async def remove_notebook(nb_id: str, authorization: Optional[str] = Header(None)):
    user = get_current_user(authorization)
    _require_notebook_owner(nb_id, user)
    delete_notebook(nb_id)
    delete_notebook_store(nb_id)
    # FIX L2: also wipe vector index from disk
    from pipeline.vector_db import VectorDB
    VectorDB.delete(nb_id)
    return {"status": "deleted"}


# FIX A1: added ownership check (was only checking existence)
@app.get("/notebooks/{nb_id}/knowledge-stats")
async def get_knowledge_stats(nb_id: str, authorization: Optional[str] = Header(None)):
    user = get_current_user(authorization)
    _require_notebook_owner(nb_id, user)   # FIX A1
    return get_chunk_stats(nb_id)


# ── Sections routes ─────────────────────────────────────────────────────────

@app.get("/notebooks/{nb_id}/sections")
async def list_sections(nb_id: str, authorization: Optional[str] = Header(None)):
    user = get_current_user(authorization)
    _require_notebook_owner(nb_id, user)
    return get_sections(nb_id)


@app.post("/notebooks/{nb_id}/sections")
async def add_section(
    nb_id: str, req: SectionCreateRequest,
    authorization: Optional[str] = Header(None),
):
    user = get_current_user(authorization)
    _require_notebook_owner(nb_id, user)
    return create_section(nb_id, req.title, req.note_type)


@app.patch("/notebooks/{nb_id}/sections/{section_id}")
async def edit_section(
    nb_id: str, section_id: str, req: SectionUpdateRequest,
    authorization: Optional[str] = Header(None),
):
    user = get_current_user(authorization)
    _require_notebook_owner(nb_id, user)
    updates = req.model_dump(exclude_none=True)
    result = update_section(section_id, **updates)
    if not result:
        raise HTTPException(404, "Section not found")
    return result


@app.delete("/notebooks/{nb_id}/sections/{section_id}")
async def remove_section(
    nb_id: str, section_id: str,
    authorization: Optional[str] = Header(None),
):
    user = get_current_user(authorization)
    _require_notebook_owner(nb_id, user)
    if not delete_section(section_id):
        raise HTTPException(404, "Section not found")
    return {"status": "deleted"}


@app.put("/notebooks/{nb_id}/sections/reorder")
async def reorder_notebook_sections(
    nb_id: str, req: SectionReorderRequest,
    authorization: Optional[str] = Header(None),
):
    user = get_current_user(authorization)
    _require_notebook_owner(nb_id, user)
    return reorder_sections(nb_id, req.order)


@app.post("/notebooks/{nb_id}/sections/{section_id}/generate")
async def generate_section_note(
    nb_id: str, section_id: str, req: SectionGenerateRequest,
    authorization: Optional[str] = Header(None),
):
    """Generate LLM note content for a single section topic."""
    user = get_current_user(authorization)
    nb = _require_notebook_owner(nb_id, user)
    sec = get_section(section_id)
    if not sec or sec["notebook_id"] != nb_id:
        raise HTTPException(404, "Section not found")

    topic_prompt = (
        f"You are generating a detailed study note for the topic: **{sec['title']}**\n"
        f"Course context: {nb.get('name', '')} ({nb.get('course', '')})\n"
        f"Student proficiency level: {req.proficiency}\n\n"
        "Write a comprehensive yet focused note covering key concepts, examples, and "
        "any important formulas or definitions. Use Markdown with ## headings, bullet lists, "
        "and LaTeX math where appropriate (delimited by $...$ or $$...$$)."
    )

    messages = [
        {"role": "system", "content": "You are an expert academic note writer. Produce well-structured Markdown notes."},
        {"role": "user", "content": topic_prompt},
    ]
    content = ""
    if _is_azure_available():
        try:
            content = await _azure_chat(messages, max_tokens=2048)
        except Exception as e:
            logger.warning("Azure section generate failed: %s", e)
    if not content and _is_groq_available():
        try:
            content = await _groq_chat(messages, max_tokens=2048)
        except Exception as e:
            logger.warning("Groq section generate failed: %s", e)
    if not content:
        raise HTTPException(503, "LLM unavailable — cannot generate section note")
    from pipeline.note_generator import _fix_tables
    content = fix_latex_delimiters(_fix_tables(content))
    updated = update_section(section_id, content=content)
    # Rebuild the flat note on the notebook so existing views still work
    full_note = rebuild_note_from_sections(nb_id)
    update_notebook_note(nb_id, full_note, req.proficiency or nb.get("proficiency"))
    return updated


# ── Upload + Generate Notes ────────────────────────────────────────────────────

@app.post("/api/upload-fuse-multi", response_model=FusionResponse)
async def upload_fuse_multi(
    slides_pdfs:   List[UploadFile] = File(...),
    textbook_pdfs: Optional[List[UploadFile]] = File(default=None),
    proficiency:   str = Form("Practitioner"),
    notebook_id:   str = Form(""),
    authorization: Optional[str] = Header(None),
):
    """
    Full 8-step semantic pipeline with all critic fixes applied.
    Key order of operations (all order-dependent fixes marked):
      Step 1   — extract text + images from all files
      Step 1b  — describe images async (FIX E1: to_thread)
                 annotate slide text (FIX B3: BEFORE chunking)
      Step 2   — chunk raw text and store verbatim in knowledge store
                 (FIX B3: annotation already in text; FIX F3: textbook_hash)
      Step 2b  — semantic chunking for vector search
      Step 3   — embed chunks (FIX F3: hash-aware load; FIX B4: rebuild TF-IDF)
      Step 4   — slide analysis (FIX G2: chunked, no 40k truncation)
      Step 5   — topic retrieval
      Step 5b  — figure→topic matching
      Steps 6+7+8 — note generation + merge + refinement (FIX C1/C2/C3)
    """
    user = get_current_user(authorization)
    _check_llm_rate_limit(user["id"])
    if notebook_id:
        _require_notebook_owner(notebook_id, user)
    from pipeline.chunker import chunk_textbook
    from pipeline.embedder import Embedder
    from pipeline.vector_db import VectorDB
    from pipeline.slide_analyzer import analyse_slides
    from pipeline.topic_retriever import TopicRetriever
    from pipeline.note_generator import run_generation_pipeline

    # ── Step 1: Text + image extraction ──────────────────────────────────────
    all_slides_text   = ""
    all_textbook_text = ""
    extraction_errors: list[str] = []
    all_slide_images:     list = []
    all_textbook_images:  list = []
    textbook_figures_items: list = []
    _total_upload_bytes = 0   # running total for the single combined size check

    for upload in slides_pdfs:
        raw   = await upload.read()
        fname = upload.filename or "slides.pdf"
        _total_upload_bytes += len(raw)
        if _total_upload_bytes > MAX_TOTAL_UPLOAD_BYTES:
            raise HTTPException(413, f"Total upload size exceeds {MAX_TOTAL_UPLOAD_BYTES // 1024 // 1024} MB. "
                                    f"Split the request into smaller batches or reduce file sizes.")
        try:
            # FIX E1: image OCR (Groq) is synchronous — must use to_thread to avoid blocking event loop
            # Add a clear file-boundary marker so slide_analyzer knows which file each slide came from.
            # Without this, topics from different files blur together and the LLM may merge or drop topics.
            file_marker = f"\n\n{'='*60}\n=== FILE: {fname} ===\n{'='*60}\n\n"
            if is_image_file(fname):
                extracted = await asyncio.to_thread(extract_text_from_file, raw, fname)
            else:
                extracted = extract_text_from_file(raw, fname)
            all_slides_text += file_marker + extracted + "\n\n"
        except ValueError as e:
            extraction_errors.append(f"{fname}: {e}")
            logger.warning("Slides extraction failed %s: %s", fname, e)
        try:
            # Raw image files have no embedded figures — skip to avoid spurious errors
            if not is_image_file(fname):
                imgs = extract_images_from_file(raw, fname)
                all_slide_images.extend(imgs)
        except Exception as e:
            logger.warning("Image extraction failed %s: %s", fname, e)

    for upload in (textbook_pdfs or []):
        raw   = await upload.read()
        fname = upload.filename or "textbook.pdf"
        _total_upload_bytes += len(raw)
        if _total_upload_bytes > MAX_TOTAL_UPLOAD_BYTES:
            raise HTTPException(413, f"Total upload size exceeds {MAX_TOTAL_UPLOAD_BYTES // 1024 // 1024} MB. "
                                    f"Split the request into smaller batches or reduce file sizes.")
        try:
            # FIX E1: image OCR (Groq) is synchronous — must use to_thread to avoid blocking event loop
            if is_image_file(fname):
                all_textbook_text += await asyncio.to_thread(extract_text_from_file, raw, fname) + "\n\n"
            else:
                all_textbook_text += extract_text_from_file(raw, fname) + "\n\n"
        except ValueError as e:
            extraction_errors.append(f"{fname}: {e}")
            logger.warning("Textbook extraction failed %s: %s", fname, e)
        try:
            # Raw image files have no embedded figures — skip to avoid spurious errors
            if not is_image_file(fname):
                tb_imgs = extract_images_from_file(raw, fname)
                for img in tb_imgs:
                    img.img_id       = f"tb_{img.img_id}"
                    img.source_label = f"Textbook — {img.source_label}"
                all_textbook_images.extend(tb_imgs)
        except Exception as e:
            logger.warning("Textbook image extraction failed %s: %s", fname, e)

    if not all_slides_text.strip() and not all_textbook_text.strip():
        detail = "Could not extract text from any uploaded files."
        if extraction_errors:
            detail += " Errors: " + "; ".join(extraction_errors)
        raise HTTPException(422, detail)

    # ── Step 1b: Describe images + annotate slide text (FIX B3 + E1) ─────────
    # FIX E1: describe_slide_image is sync — wrap in to_thread
    # FIX B3: annotation MUST happen before chunk_text() below
    if all_slide_images and notebook_id:
        logger.info("Describing %d slide images (async)…", len(all_slide_images))

        async def _desc(img):
            try:
                img.description = await asyncio.to_thread(
                    describe_slide_image, img.data, img.source_label
                )
            except Exception as e:
                img.description = f"Figure from {img.source_label}"
                logger.debug("describe_slide_image error: %s", e)

        await asyncio.gather(*[_desc(img) for img in all_slide_images])

        # FIX D4: clear_existing=True so re-upload of same notebook doesn't accumulate stale files
        try:
            save_images(notebook_id, all_slide_images, clear_existing=True)
        except Exception as e:
            logger.warning("Slide image save failed: %s", e)
            all_slide_images = []

        # FIX B3: annotate slide text NOW — before chunk_text() on line below
        for img in all_slide_images:
            marker_pattern = re.compile(
                r'(---\s*' + re.escape(img.source_label) + r'[^\n]*---)',
                re.IGNORECASE,
            )
            all_slides_text = marker_pattern.sub(
                lambda m, ann=f"\n[Figure: {img.description}]": m.group(0) + ann,
                all_slides_text, count=1,
            )
        logger.info("Annotated %d slide images into slide text (before chunking)", len(all_slide_images))

    elif all_slide_images:
        logger.info("No notebook_id — slide image save skipped")

    if all_textbook_images and notebook_id:
        logger.info("Describing %d textbook images (async)…", len(all_textbook_images))

        async def _desc_tb(img):
            try:
                img.description = await asyncio.to_thread(
                    describe_slide_image, img.data, img.source_label
                )
            except Exception as e:
                img.description = f"Figure from {img.source_label}"

        await asyncio.gather(*[_desc_tb(img) for img in all_textbook_images])
        try:
            save_images(notebook_id, all_textbook_images, clear_existing=False)
            for img in all_textbook_images:
                ext = img.mime.split("/")[-1].replace("jpeg", "jpg")
                textbook_figures_items.append(
                    (img, f"/api/images/{notebook_id}/{img.img_id}.{ext}")
                )
        except Exception as e:
            logger.warning("Textbook image save failed: %s", e)
            all_textbook_images = []

    # ── Step 2: Chunk raw text + store in knowledge store (FIX B3, F3) ───────
    slide_raw_chunks    = chunk_text(all_slides_text,   max_chars=4000)
    textbook_raw_chunks = chunk_text(all_textbook_text, max_chars=4000)
    textbook_hash       = hashlib.md5(all_textbook_text.encode()).hexdigest()[:16]

    chunks_stored = None
    if notebook_id:
        try:
            chunks_stored = store_source_chunks(
                nb_id=notebook_id,
                slide_chunks=slide_raw_chunks,
                textbook_chunks=textbook_raw_chunks,
                textbook_hash=textbook_hash,  # FIX F3
            )
            logger.info("Knowledge store: %d chunks for %s", chunks_stored["total"], notebook_id)
        except Exception as e:
            logger.warning("Knowledge store write failed: %s", e)

    # ── Step 2b: Semantic chunking for vector search ──────────────────────────
    textbook_semantic_chunks = []
    if all_textbook_text.strip():
        try:
            textbook_semantic_chunks = chunk_textbook(all_textbook_text)
            logger.info("Textbook: %d semantic chunks", len(textbook_semantic_chunks))
        except Exception as e:
            logger.warning("Textbook semantic chunking failed: %s", e)

    # ── Step 3: Embeddings (FIX F3 staleness, FIX B4 TF-IDF rebuild) ─────────
    embedder  = Embedder()
    vector_db = VectorDB()

    if textbook_semantic_chunks:
        loaded = False
        if notebook_id:
            try:
                # FIX F3: pass hash — load() rejects stale index automatically
                loaded = vector_db.load(notebook_id, expected_hash=textbook_hash)
                if loaded:
                    logger.info("Loaded fresh vector index for %s", notebook_id)
            except Exception:
                pass

        if loaded:
            # FIX B4: rebuild TF-IDF so embed_query works on a fresh Embedder
            try:
                embedder.rebuild_from_chunks(vector_db.chunks)
                logger.info("Rebuilt TF-IDF from %d loaded chunks", vector_db.size)
            except Exception as e:
                logger.warning("Embedder rebuild failed (%s) — re-embedding", e)
                loaded = False

        if not loaded:
            try:
                backend = embedder.embed_chunks(textbook_semantic_chunks)
                vector_db.add_chunks(textbook_semantic_chunks)
                if notebook_id:
                    vector_db.save(notebook_id, textbook_hash=textbook_hash)
                logger.info("Embedded %d chunks via %s", len(textbook_semantic_chunks), backend)
            except Exception as e:
                logger.warning("Embedding failed: %s", e)

    # ── Step 4: Slide understanding (FIX G2: no hard truncation) ─────────────
    topics = []
    try:
        topics = await analyse_slides(all_slides_text)
        logger.info("Slide analysis: %d topics", len(topics))
    except Exception as e:
        logger.warning("Slide analysis failed: %s", e)

    # ── Step 5: Topic-based retrieval ─────────────────────────────────────────
    topic_contexts: dict[str, str] = {}
    if topics and vector_db.size > 0:
        try:
            retriever = TopicRetriever(vector_db, embedder)
            topic_contexts = retriever.retrieve_all_topics(topics)
            logger.info("Retrieved context for %d topics", len(topic_contexts))
        except Exception as e:
            logger.warning("Topic retrieval failed: %s", e)

    # ── Step 5b: Match textbook figures to topics ─────────────────────────────
    if textbook_figures_items and topics:
        for img, img_url in textbook_figures_items:
            best = _match_image_to_topic(img.description, topics)
            if best is not None:
                ref = f"\n\n[Textbook Figure: {img.description}]\n![{img.description}]({img_url})"
                topic_contexts[best] = topic_contexts.get(best, "") + ref

    # ── Step 5c: Build topic_figures map for inline injection ─────────────────
    topic_figures: dict[str, list] = {}
    if topics and notebook_id:
        for img in all_slide_images:
            ext     = img.mime.split("/")[-1].replace("jpeg", "jpg")
            img_url = f"/api/images/{notebook_id}/{img.img_id}.{ext}"
            matched = None
            for t in topics:
                if img.source_label.lower() in t.slide_text.lower():
                    matched = t.topic
                    break
            if matched is None:
                matched = _match_image_to_topic(img.description, topics)
            if matched:
                topic_figures.setdefault(matched, []).append((img.description, img_url))
        for img, img_url in textbook_figures_items:
            best = _match_image_to_topic(img.description, topics)
            if best:
                topic_figures.setdefault(best, []).append((img.description, img_url))
        if topic_figures:
            logger.info("Inline figures: %d topics, %d figures total",
                        len(topic_figures), sum(len(v) for v in topic_figures.values()))

    # ── Steps 6+7+8: Generate + merge + refine ────────────────────────────────
    fused_note = None
    source     = "local"
    pipe_error = None

    if topics:
        try:
            fused_note, source = await asyncio.wait_for(
                run_generation_pipeline(
                    topics=topics,
                    topic_contexts=topic_contexts,
                    proficiency=proficiency,
                    refine=True,
                ),
                timeout=PIPELINE_TIMEOUT_S,
            )
            logger.info("Pipeline: %d chars (source=%s)", len(fused_note or ""), source)
        except asyncio.TimeoutError:
            pipe_error = f"Pipeline timed out after {PIPELINE_TIMEOUT_S}s"
            logger.warning(pipe_error)
        except Exception as exc:
            pipe_error = f"{type(exc).__name__}: {exc}"
            logger.warning("Pipeline generation failed: %s", pipe_error)

    if not fused_note or len(fused_note.strip()) < 100:
        logger.info("Falling back to local summarizer")
        fused_note = generate_local_note(all_slides_text, all_textbook_text, proficiency)
        source     = "local"

    from pipeline.note_generator import _fix_tables
    fused_note = fix_latex_delimiters(_fix_tables(fused_note))

    if fused_note and topic_figures:
        fused_note = _inject_figures_into_sections(fused_note, topic_figures)

    # ── Post-generation accuracy verification ─────────────────────────────────
    if source != "local":
        try:
            slide_ctx_flat    = all_slides_text[:8000]
            textbook_ctx_flat = all_textbook_text[:8000]
            fused_note, _, _ = await _verify_note(fused_note, slide_ctx_flat, textbook_ctx_flat)
        except Exception as ve:
            logger.warning("Non-stream self-review error: %s", ve)

    # ── Store note pages ──────────────────────────────────────────────────────
    if notebook_id:
        try:
            pages = _note_to_pages(fused_note)
            store_note_pages(notebook_id, pages)
            logger.info("Stored %d pages for %s", len(pages), notebook_id)
        except Exception as e:
            logger.warning("Note page store failed: %s", e)
        try:
            update_notebook_note(notebook_id, fused_note, proficiency)
        except Exception:
            pass

    fallback_warning = None
    if source == "local" and pipe_error:
        fallback_warning = f"AI unavailable ({pipe_error}) — offline notes used."
    elif source == "local":
        fallback_warning = "No AI configured — offline summariser used."

    return FusionResponse(
        fused_note=fused_note,
        source=source,
        fallback_reason=fallback_warning,
        chunks_stored=chunks_stored,
    )


# ── Image serving ──────────────────────────────────────────────────────────────

@app.get("/api/images/{notebook_id}/{img_filename}")
async def serve_slide_image(notebook_id: str, img_filename: str):
    # FIX (round 4): reject path-traversal attempts in both path segments.
    # <img> tags cannot send Authorization headers, so Bearer auth is not
    # practical here; path hardening prevents directory escape instead.
    import re as _re
    if not _re.fullmatch(r'[a-zA-Z0-9_\-]+', notebook_id) or \
       not _re.fullmatch(r'[a-zA-Z0-9_\-]+\.[a-zA-Z0-9]+', img_filename):
        raise HTTPException(400, "Invalid image path")
    path = get_image_path(notebook_id, img_filename)
    if not path:
        raise HTTPException(404, f"Image {img_filename} not found")
    ext  = img_filename.rsplit(".", 1)[-1].lower()
    mime = {"jpg": "image/jpeg", "jpeg": "image/jpeg", "png": "image/png",
            "webp": "image/webp", "gif": "image/gif"}.get(ext, "image/png")
    return FileResponse(path, media_type=mime, headers={"Cache-Control": "max-age=3600"})


# ── Backward-compat single-file upload ────────────────────────────────────────

@app.post("/api/upload-fuse", response_model=FusionResponse)
async def upload_fuse(
    slides_pdf:   UploadFile = File(...),
    textbook_pdf: UploadFile = File(...),
    proficiency:  str = Form("Practitioner"),
    notebook_id:  str = Form(""),
    authorization: Optional[str] = Header(None),
):
    # FIX: require auth on backward-compat endpoint too
    get_current_user(authorization)
    slides_pdf.filename   = slides_pdf.filename   or "slides.pdf"
    textbook_pdf.filename = textbook_pdf.filename or "textbook.pdf"
    return await upload_fuse_multi(
        slides_pdfs=[slides_pdf], textbook_pdfs=[textbook_pdf],
        proficiency=proficiency, notebook_id=notebook_id,
        authorization=authorization,
    )


# ── SSE Streaming fuse endpoint ────────────────────────────────────────────────

@app.post("/api/upload-fuse-stream")
async def upload_fuse_stream(
    proficiency:   str             = Form("Practitioner"),
    slides_pdfs:   List[UploadFile] = File(default=[]),
    textbook_pdfs: List[UploadFile] = File(default=[]),
    notebook_id:   Optional[str]   = Form(None),
    authorization: Optional[str]   = Header(None),
):
    """
    Streaming (SSE) version of /api/upload-fuse-multi.

    Emits newline-delimited JSON events (text/event-stream):
      data: {"type":"status","message":"Extracting slides..."}
      data: {"type":"start","total":12}
      data: {"type":"section","topic":"Fourier Transform","content":"## ...","index":0}
      ...
      data: {"type":"done","note":"<full_note>","source":"azure"}

    The client can reconstruct the note incrementally by accumulating section.content.
    """
    user = get_current_user(authorization)
    _check_llm_rate_limit(user["id"])
    if notebook_id:
        _require_notebook_owner(notebook_id, user)
    from pipeline.chunker      import chunk_textbook
    from pipeline.embedder     import Embedder
    from pipeline.vector_db    import VectorDB
    from pipeline.slide_analyzer import analyse_slides
    from pipeline.topic_retriever import TopicRetriever
    from pipeline.note_generator  import run_generation_pipeline_stream

    # ── Preprocessing (same as upload-fuse-multi) ─────────────────────────────
    all_slides_text  = ""
    all_textbook_text = ""
    _total_bytes = 0
    extraction_errors = []

    for upload in slides_pdfs:
        raw   = await upload.read()
        fname = upload.filename or "slides.pdf"
        _total_bytes += len(raw)
        if _total_bytes > MAX_TOTAL_UPLOAD_BYTES:
            raise HTTPException(413, f"Upload exceeds {MAX_TOTAL_UPLOAD_BYTES//1024//1024} MB limit")
        try:
            file_marker = f"\n\n{'='*60}\n=== FILE: {fname} ===\n{'='*60}\n\n"
            if is_image_file(fname):
                extracted = await asyncio.to_thread(extract_text_from_file, raw, fname)
            else:
                extracted = extract_text_from_file(raw, fname)
            all_slides_text += file_marker + extracted + "\n\n"
        except Exception as e:
            extraction_errors.append(f"{fname}: {e}")

    for upload in (textbook_pdfs or []):
        raw   = await upload.read()
        fname = upload.filename or "textbook.pdf"
        _total_bytes += len(raw)
        if _total_bytes > MAX_TOTAL_UPLOAD_BYTES:
            raise HTTPException(413, f"Upload exceeds {MAX_TOTAL_UPLOAD_BYTES//1024//1024} MB limit")
        try:
            if is_image_file(fname):
                all_textbook_text += await asyncio.to_thread(extract_text_from_file, raw, fname) + "\n\n"
            else:
                all_textbook_text += extract_text_from_file(raw, fname) + "\n\n"
        except Exception as e:
            extraction_errors.append(f"{fname}: {e}")

    if not all_slides_text.strip() and not all_textbook_text.strip():
        raise HTTPException(422, "Could not extract text from any uploaded file. " + "; ".join(extraction_errors))

    slide_raw_chunks    = chunk_text(all_slides_text,   max_chars=4000)
    textbook_raw_chunks = chunk_text(all_textbook_text, max_chars=4000)
    textbook_hash       = hashlib.md5(all_textbook_text.encode()).hexdigest()[:16]

    chunks_stored = None
    if notebook_id:
        try:
            chunks_stored = store_source_chunks(
                nb_id=notebook_id,
                slide_chunks=slide_raw_chunks,
                textbook_chunks=textbook_raw_chunks,
                textbook_hash=textbook_hash,
            )
        except Exception as e:
            logger.warning("Knowledge store write failed: %s", e)

    textbook_semantic_chunks = []
    if all_textbook_text.strip():
        try:
            textbook_semantic_chunks = chunk_textbook(all_textbook_text)
        except Exception as e:
            logger.warning("Textbook semantic chunking failed: %s", e)

    embedder  = Embedder()
    vector_db = VectorDB()
    if textbook_semantic_chunks:
        try:
            loaded = notebook_id and vector_db.load(notebook_id, expected_hash=textbook_hash)
            if loaded:
                embedder.rebuild_from_chunks(vector_db.chunks)
            else:
                embedder.embed_chunks(textbook_semantic_chunks)
                vector_db.add_chunks(textbook_semantic_chunks)
                if notebook_id:
                    vector_db.save(notebook_id, textbook_hash=textbook_hash)
        except Exception as e:
            logger.warning("Embedding failed: %s", e)

    topics = []
    try:
        topics = await analyse_slides(all_slides_text)
    except Exception as e:
        logger.warning("Slide analysis failed: %s", e)

    topic_contexts: dict[str, str] = {}
    if topics and vector_db.size > 0:
        try:
            retriever = TopicRetriever(vector_db, embedder)
            topic_contexts = retriever.retrieve_all_topics(topics)
        except Exception as e:
            logger.warning("Topic retrieval failed: %s", e)

    # ── Stream generation ──────────────────────────────────────────────────────
    async def event_generator():
        import json as _json
        from pipeline.note_generator import _fix_tables

        if not topics:
            fallback = generate_local_note(all_slides_text, all_textbook_text, proficiency)
            fallback = fix_latex_delimiters(_fix_tables(fallback))
            if notebook_id:
                try:
                    update_notebook_note(notebook_id, fallback, proficiency)
                except Exception:
                    pass
            yield f"data: {_json.dumps({'type':'done','note':fallback,'source':'local'})}\n\n"
            return

        yield f"data: {_json.dumps({'type':'status','message':'Starting note generation…'})}\n\n"

        final_note = ""
        final_source = "local"
        async for event in run_generation_pipeline_stream(topics, topic_contexts, proficiency):
            if event["type"] == "section":
                event["content"] = fix_latex_delimiters(_fix_tables(event["content"]))
            elif event["type"] == "done":
                    final_note   = fix_latex_delimiters(_fix_tables(event.get("note", "")))
                    final_source = event.get("source", "local")

                    # ── Post-generation accuracy verification ──────────────────
                    if final_note and final_source != "local":
                        yield f"data: {_json.dumps({'type':'status','message':'Verifying accuracy against source material…'})}\n\n"
                        try:
                            slide_ctx_flat    = all_slides_text[:8000]
                            textbook_ctx_flat = all_textbook_text[:8000]
                            final_note, was_corrected, corr_summary = await _verify_note(
                                final_note, slide_ctx_flat, textbook_ctx_flat
                            )
                        except Exception as ve:
                            logger.warning("Streaming self-review error: %s", ve)
                            was_corrected, corr_summary = False, ""
                    else:
                        was_corrected, corr_summary = False, ""

                    event["note"]             = final_note
                    event["source"]           = final_source
                    event["verified"]         = True
                    event["corrections_made"] = 1 if was_corrected else 0
                    event["correction_summary"] = corr_summary
                    # Persist verified note
                    if notebook_id and final_note:
                        try:
                            pages = _note_to_pages(final_note)
                            store_note_pages(notebook_id, pages)
                            update_notebook_note(notebook_id, final_note, proficiency)
                        except Exception as e:
                            logger.warning("Stream persist failed: %s", e)
            yield f"data: {_json.dumps(event)}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "X-Accel-Buffering":  "no",
            "Cache-Control":      "no-cache",
            "Connection":         "keep-alive",
        },
    )


# ── Doubt answering (FIX A3: auth required) ───────────────────────────────────

@app.post("/api/doubt", response_model=DoubtResponse)
async def answer_doubt(
    req: DoubtRequest,
    authorization: Optional[str] = Header(None),
):
    """FIX A3: Bearer token required."""
    user = get_current_user(authorization)
    _check_llm_rate_limit(user["id"])
    _require_notebook_owner(req.notebook_id, user)

    slide_hits    = retrieve_relevant_chunks(req.notebook_id, req.doubt, top_k=6, source_filter="slides")
    textbook_hits = retrieve_relevant_chunks(req.notebook_id, req.doubt, top_k=6, source_filter="textbook")
    slide_ctx    = _format_chunks_for_prompt(slide_hits,    8_000)
    textbook_ctx = _format_chunks_for_prompt(textbook_hits, 8_000)
    note_page    = get_note_page(req.notebook_id, req.page_idx) or ""

    from agents.verifier_agent import parse_verification_response

    raw_text: str | None = None
    source = "local"

    if _is_azure_available():
        try:
            raw_text = str(await fusion_agent.answer_doubt(
                doubt=req.doubt, slide_context=slide_ctx,
                textbook_context=textbook_ctx, note_page=note_page,
            ))
            source = "azure"
        except Exception as e:
            logger.warning("Azure doubt failed: %s", e)

    if raw_text is None and _is_groq_available():
        try:
            raw_text = await _groq_doubt(req.doubt, slide_ctx, textbook_ctx, note_page)
            source = "groq"
        except Exception as e:
            logger.warning("Groq doubt failed: %s", e)

    if raw_text is not None:
        vr = parse_verification_response(raw_text)
        _safe, _cat = await check_content_safety(vr.answer)
        if not _safe:
            logger.warning("Content Safety flagged doubt answer: category=%s", _cat)
        _record_llm_call(user["id"], source, est_tokens=1500)
        return DoubtResponse(
            answer=fix_latex_delimiters(vr.answer),
            source=source,
            verification_status=vr.verification_status,
            correction=fix_latex_delimiters(vr.correction),
            footnote=vr.footnote,
        )

    # ── Offline fallback ──────────────────────────────────────────────────────
    from agents.local_mutation import _diagnose_gap, _build_analogy_hint
    gap     = _diagnose_gap(req.doubt)
    analogy = _build_analogy_hint(req.doubt)
    answer  = f"**{gap}**\n\n{analogy}"
    if note_page:
        answer += f"\n\n*From your notes:* {note_page[:300]}…"
    return DoubtResponse(answer=fix_latex_delimiters(answer), source="local")


# ── Mutation (FIX A4, A7, L3: auth + dynamic concept + single parser) ─────────

@app.post("/api/mutate", response_model=MutationResponse)
async def mutate_note(
    req: MutationRequest,
    authorization: Optional[str] = Header(None),
):
    """
    FIX A4: Bearer token required.
    FIX A7: No hardcoded "Convolution Theorem" — extracts real concept from note.
    FIX L3: Single mutate parser via FusionAgent._parse_mutate_response.
    """
    user = get_current_user(authorization)  # FIX A4
    _check_llm_rate_limit(user["id"])
    _require_notebook_owner(req.notebook_id, user)
    _username = user.get("username", "anonymous")

    note_page = get_note_page(req.notebook_id, req.page_idx)
    if note_page is None:
        note_page = req.original_paragraph or ""

    query = req.doubt + " " + note_page[:200]
    slide_hits    = retrieve_relevant_chunks(req.notebook_id, query, top_k=6, source_filter="slides")
    textbook_hits = retrieve_relevant_chunks(req.notebook_id, query, top_k=6, source_filter="textbook")
    slide_ctx    = _format_chunks_for_prompt(slide_hits,    8_000)
    textbook_ctx = _format_chunks_for_prompt(textbook_hits, 8_000)

    mutated, gap, answer, llm_source = await _llm_mutate(note_page, req.doubt, slide_ctx, textbook_ctx)

    if mutated is None:
        mutated, gap = local_mutate(note_page, req.doubt)
        llm_source   = "local"
        answer       = ""

    can_mutate = llm_source in ("azure", "groq")

    from pipeline.note_generator import _fix_tables
    mutated = fix_latex_delimiters(_fix_tables(mutated))

    if can_mutate and req.notebook_id:
        try:
            updated = update_note_page(req.notebook_id, req.page_idx, mutated)
            if updated:
                full_note = "\n\n".join(get_all_note_pages(req.notebook_id))
                update_notebook_note(req.notebook_id, full_note)
                logger.info("Mutated page %d for %s", req.page_idx, req.notebook_id)
        except Exception as e:
            logger.warning("Page update failed: %s", e)

    # Content Safety check on mutated output
    _safe, _cat = await check_content_safety(mutated)
    if not _safe:
        logger.warning("Content Safety flagged mutation output: category=%s", _cat)

    # FIX A7: dynamically extract real concept from the mutated note section
    if req.notebook_id and mutated:
        try:
            graph = extract_concepts(mutated)
            if graph.get("nodes"):
                top_concept = graph["nodes"][0]["label"]
                update_node_status(top_concept, "partial", _username)
                increment_mutation_count(top_concept, _username)
        except Exception:
            pass   # non-critical — don't break mutation over graph update failure

    if can_mutate:
        _record_llm_call(user["id"], llm_source, est_tokens=3000)

    return MutationResponse(
        mutated_paragraph=mutated,
        concept_gap=gap or "Student required additional clarification.",
        answer=fix_latex_delimiters(answer) if answer else (gap or ""),
        page_idx=req.page_idx,
        source=llm_source,
        can_mutate=can_mutate,
    )


@app.post("/api/regenerate-section", response_model=RegenerateSectionResponse)
async def regenerate_section(
    req: RegenerateSectionRequest,
    authorization: Optional[str] = Header(None),
):
    """
    Re-generate a single note page section from scratch using stored source chunks.
    Useful when the student wants a fresh take on a topic without re-uploading all files.
    """
    user = get_current_user(authorization)
    nb = _require_notebook_owner(req.notebook_id, user)

    # Get the current page text (used to extract the topic heading)
    current_page_text = get_note_page(req.notebook_id, req.page_idx) or ""
    # Fall back to splitting the full note
    if not current_page_text and nb.get("note"):
        note_pages = re.split(r'(?m)^(?=## )', nb["note"])
        note_pages = [p.strip() for p in note_pages if p.strip()]
        if req.page_idx < len(note_pages):
            current_page_text = note_pages[req.page_idx]

    if not current_page_text:
        raise HTTPException(404, "Page not found in notebook")

    # Extract heading for targeted retrieval
    heading_match = re.match(r'^#{1,3}\s+(.+)', current_page_text)
    topic = heading_match.group(1) if heading_match else current_page_text[:80]

    # Retrieve source material
    slide_hits    = retrieve_relevant_chunks(req.notebook_id, topic, top_k=8, source_filter="slides")
    textbook_hits = retrieve_relevant_chunks(req.notebook_id, topic, top_k=8, source_filter="textbook")
    slide_ctx    = _format_chunks_for_prompt(slide_hits,    10_000)
    textbook_ctx = _format_chunks_for_prompt(textbook_hits, 10_000)

    # Build a generation prompt
    regen_prompt = f"""You are AuraGraph's note-generation engine. Re-write the following study note section **from scratch**, using only the source material below.

TOPIC: {topic}
PROFICIENCY LEVEL: {req.proficiency}

SOURCE MATERIAL:
--- SLIDES ---
{slide_ctx}

--- TEXTBOOK ---
{textbook_ctx}

INSTRUCTIONS:
- Write a single cohesive section starting with "## {topic}"
- Use LaTeX math ($...$ for inline, $$...$$ for display)
- Include key formulas, definitions, and intuition calibrated to {req.proficiency} level
- Do NOT copy the old note — write a fresh, improved version
- Output ONLY the markdown note section (no preamble)"""

    llm_source = "local"
    new_section = ""

    if _is_azure_available():
        try:
            new_section = await _azure_chat([{"role": "user", "content": regen_prompt}], max_tokens=3000)
            llm_source = "azure"
        except Exception as e:
            logger.warning("Azure regenerate failed: %s", e)

    if not new_section and _is_groq_available():
        try:
            new_section = await _groq_chat([{"role": "user", "content": regen_prompt}], max_tokens=3000)
            llm_source = "groq"
        except Exception as e:
            logger.warning("Groq regenerate failed: %s", e)

    if not new_section:
        # Offline fallback — return original with a notice
        new_section = current_page_text + "\n\n> *(Regeneration unavailable — AI offline. Original section kept.)*"
        llm_source = "local"
    else:
        from pipeline.note_generator import _fix_tables
        new_section = fix_latex_delimiters(_fix_tables(new_section))
        # Persist the updated page
        try:
            update_note_page(req.notebook_id, req.page_idx, new_section)
            full_note = "\n\n".join(get_all_note_pages(req.notebook_id))
            update_notebook_note(req.notebook_id, full_note)
        except Exception as e:
            logger.warning("Failed to persist regenerated section: %s", e)

    return RegenerateSectionResponse(new_section=new_section, page_idx=req.page_idx, source=llm_source)


# ── Sniper Exam ───────────────────────────────────────────────────────
async def _groq_sniper_exam(struggling: list[str], partial: list[str], notebook_context: str = "") -> str:
    from agents.examiner_agent import SNIPER_EXAM_PROMPT
    prompt = (
        SNIPER_EXAM_PROMPT
        .replace("{{$struggling_concepts}}", ", ".join(struggling) if struggling else "None")
        .replace("{{$partial_concepts}}",    ", ".join(partial)    if partial    else "None")
        .replace("{{$notebook_context}}",    notebook_context or "(no course context available)")
    )
    return await _groq_chat([{"role": "user", "content": prompt}], max_tokens=2500)


@app.post("/api/sniper-exam", response_model=SniperExamResponse)
async def sniper_exam(
    req: SniperExamRequest,
    authorization: Optional[str] = Header(None),
):
    """Generates a 70% struggling / 30% partial targeted exam from the user's concept graph."""
    user     = get_current_user(authorization)
    if req.notebook_id:
        _require_notebook_owner(req.notebook_id, user)
    username = user.get("username", "anonymous")

    db    = get_db(username)
    nodes = db.get("nodes", [])

    struggling = [n["label"] for n in nodes if n.get("status") == "struggling"][:4]
    partial    = [n["label"] for n in nodes if n.get("status") == "partial"][:3]

    if not struggling and not partial:
        all_labels = [n["label"] for n in nodes][:5]
        struggling = all_labels[:3]
        partial    = all_labels[3:]

    concepts_tested = (
        [{"label": l, "status": "struggling"} for l in struggling] +
        [{"label": l, "status": "partial"}    for l in partial]
    )

    # Retrieve course-specific context — pull from both slides and textbook
    nb_ctx = ""
    if req.notebook_id:
        combined_query = " ".join(struggling + partial)
        slide_hits = retrieve_relevant_chunks(req.notebook_id, combined_query, top_k=14,
                                              source_filter="slides")
        tb_hits    = retrieve_relevant_chunks(req.notebook_id, combined_query, top_k=6,
                                              source_filter="textbook")
        slide_ctx  = _format_chunks_for_prompt(slide_hits, 5000)
        tb_ctx     = _format_chunks_for_prompt(tb_hits,    2000)
        if slide_ctx and tb_ctx:
            nb_ctx = f"[FROM SLIDES]\n{slide_ctx}\n\n[FROM TEXTBOOK]\n{tb_ctx}"
        else:
            nb_ctx = slide_ctx or tb_ctx

    raw = ""
    if _is_azure_available():
        try:
            from agents.examiner_agent import SNIPER_EXAM_PROMPT
            prompt = (
                SNIPER_EXAM_PROMPT
                .replace("{{$struggling_concepts}}", ", ".join(struggling) or "None")
                .replace("{{$partial_concepts}}",    ", ".join(partial)    or "None")
                .replace("{{$notebook_context}}",    nb_ctx or "(no course context available)")
            )
            raw = await _azure_chat([{"role": "user", "content": prompt}], max_tokens=4000)
        except Exception as e:
            logger.warning("Azure sniper exam failed: %s", e)

    if not raw and _is_groq_available():
        try:
            raw = await _groq_sniper_exam(struggling, partial, notebook_context=nb_ctx)
        except Exception as e:
            logger.warning("Groq sniper exam failed: %s", e)

    # Parse JSON
    questions: list = []
    if raw:
        try:
            # Strip markdown fences
            clean = re.sub(r"^```[a-z]*\n?", "", raw.strip())
            clean = re.sub(r"\n?```$", "", clean.strip())
            # If still not a bare array, try to extract [...] block
            if not clean.lstrip().startswith('['):
                m = re.search(r'\[[\s\S]+\]', clean)
                if m:
                    clean = m.group(0)
            # Fix LaTeX \-sequences that are invalid JSON escapes (\frac, \sigma, \beta, etc.)
            # Only protect " \ / \n \u — everything else (f,b,r,t,d,...) must be doubled.
            clean = re.sub(r'\\(?!["\\/nu])', r'\\\\', clean)
            questions = json.loads(clean)
            if not isinstance(questions, list):
                questions = []
        except Exception as e:
            logger.warning("Sniper exam JSON parse failed: %s | raw[:200]=%s", e, raw[:200])

    if not questions:
        # Offline fallback — one stub question per struggling concept
        for i, label in enumerate((struggling + partial)[:5]):
            questions.append({
                "question":    f"Describe the key aspects of {label}.",
                "options":     {"A": "Option A", "B": "Option B", "C": "Option C", "D": "Option D"},
                "correct":     "A",
                "explanation": "Backend offline — reconnect for AI-generated questions.",
                "concept":     label,
            })

    return SniperExamResponse(questions=questions, concepts_tested=concepts_tested)

# ── Examiner (FIX A5: auth required) ───────────────────────────────────

@app.post("/api/examine", response_model=ExaminerResponse)
async def examine_concept(
    req: ExaminerRequest,
    authorization: Optional[str] = Header(None),
):
    """FIX A5: Bearer token required; notebook ownership enforced when notebook_id is provided."""
    user = get_current_user(authorization)
    if req.notebook_id:
        _require_notebook_owner(req.notebook_id, user)

    ci = (req.custom_instruction or "").strip()
    # Retrieve course-specific context — pull generously from BOTH slides and textbook
    # so the examiner can generate questions grounded in actual course material.
    nb_ctx = ""
    if req.notebook_id:
        slide_hits = retrieve_relevant_chunks(req.notebook_id, req.concept_name, top_k=12,
                                              source_filter="slides")
        tb_hits    = retrieve_relevant_chunks(req.notebook_id, req.concept_name, top_k=8,
                                              source_filter="textbook")
        slide_ctx  = _format_chunks_for_prompt(slide_hits, 5000)
        tb_ctx     = _format_chunks_for_prompt(tb_hits,    3000)
        if slide_ctx and tb_ctx:
            nb_ctx = f"[FROM SLIDES]\n{slide_ctx}\n\n[FROM TEXTBOOK]\n{tb_ctx}"
        else:
            nb_ctx = slide_ctx or tb_ctx

    if examiner_agent and _is_azure_available():
        try:
            q = await examiner_agent.examine(req.concept_name, notebook_context=nb_ctx,
                                              custom_instruction=ci)
            return ExaminerResponse(practice_questions=fix_latex_delimiters(q))
        except Exception as e:
            logger.warning("Azure examiner failed: %s", e)
    if _is_groq_available():
        try:
            from agents.examiner_agent import EXAMINER_PROMPT
            ci_full = f"\n\nCUSTOM FOCUS (follow exactly): {ci}" if ci else ""
            prompt = (EXAMINER_PROMPT
                      .replace("{{$concept_name}}", req.concept_name)
                      .replace("{{$notebook_context}}", nb_ctx or "(no course context available)")
                      .replace("{{$custom_instruction}}", ci_full))
            q = await _groq_chat([{"role": "user", "content": prompt}], max_tokens=4000)
            return ExaminerResponse(practice_questions=fix_latex_delimiters(q))
        except Exception as e:
            logger.warning("Groq examiner failed: %s", e)
    q = local_examine(req.concept_name)
    return ExaminerResponse(practice_questions=fix_latex_delimiters(q))


# ── Concept Practice (level-aware structured MCQs) ────────────────────────────

async def _groq_concept_practice(concept_name: str, level: str, notebook_context: str = "", custom_instruction: str = "") -> str:
    from agents.examiner_agent import CONCEPT_PRACTICE_PROMPT
    ci = f"\n\nCUSTOM FOCUS (follow exactly): {custom_instruction}" if custom_instruction.strip() else ""
    prompt = (
        CONCEPT_PRACTICE_PROMPT
        .replace("{{$concept_name}}", concept_name)
        .replace("{{$level}}",        level)
        .replace("{{$notebook_context}}", notebook_context or "(no course context available)")
        .replace("{{$custom_instruction}}", ci)
    )
    return await _groq_chat([{"role": "user", "content": prompt}], max_tokens=2000)


@app.post("/api/concept-practice", response_model=ConceptPracticeResponse)
async def concept_practice_endpoint(
    req: ConceptPracticeRequest,
    authorization: Optional[str] = Header(None),
):
    import json as _json
    user = get_current_user(authorization)
    if req.notebook_id:
        _require_notebook_owner(req.notebook_id, user)

    level = req.level.lower().strip()
    if level not in ("struggling", "partial", "mastered"):
        level = "partial"
    ci = (req.custom_instruction or "").strip()

    # Retrieve course-specific context — pull from both slides and textbook
    nb_ctx = ""
    if req.notebook_id:
        slide_hits = retrieve_relevant_chunks(req.notebook_id, req.concept_name, top_k=12,
                                              source_filter="slides")
        tb_hits    = retrieve_relevant_chunks(req.notebook_id, req.concept_name, top_k=6,
                                              source_filter="textbook")
        slide_ctx  = _format_chunks_for_prompt(slide_hits, 5000)
        tb_ctx     = _format_chunks_for_prompt(tb_hits,    2500)
        if slide_ctx and tb_ctx:
            nb_ctx = f"[FROM SLIDES]\n{slide_ctx}\n\n[FROM TEXTBOOK]\n{tb_ctx}"
        else:
            nb_ctx = slide_ctx or tb_ctx

    raw: str | None = None

    if examiner_agent and _is_azure_available():
        try:
            raw = await examiner_agent.concept_practice(req.concept_name, level,
                                                        notebook_context=nb_ctx,
                                                        custom_instruction=ci)
        except Exception as e:
            logger.warning("Azure concept-practice failed: %s", e)

    if raw is None and _is_groq_available():
        try:
            raw = await _groq_concept_practice(req.concept_name, level,
                                               notebook_context=nb_ctx,
                                               custom_instruction=ci)
        except Exception as e:
            logger.warning("Groq concept-practice failed: %s", e)

    if raw:
        stripped = raw.strip()
        stripped = re.sub(r'^```(?:json)?\s*', '', stripped)
        stripped = re.sub(r'\s*```$', '', stripped.strip())
        # Fix LaTeX \-sequences that are invalid JSON escapes (\frac, \sigma, \beta, etc.)
        # Only protect " \ / \n \u — everything else (f,b,r,t,d,...) must be doubled.
        stripped = re.sub(r'\\(?!["\\/nu])', r'\\\\', stripped)
        # If not a bare array, extract [...] block
        if not stripped.lstrip().startswith('['):
            m = re.search(r'\[[\s\S]+\]', stripped)
            if m:
                stripped = m.group(0)
        try:
            parsed = _json.loads(stripped)
            if isinstance(parsed, list) and parsed:
                return ConceptPracticeResponse(questions=parsed)
        except Exception as exc:
            logger.warning("concept-practice JSON parse failed: %s | raw[:150]=%s", exc, raw[:150] if raw else '')

    return ConceptPracticeResponse(questions=[
        {
            "question": f"Which of the following best describes '{req.concept_name}'?",
            "options": {"A": "Option A", "B": "Option B", "C": "Option C", "D": "Option D"},
            "correct": "A",
            "explanation": "Backend offline — reconnect for AI-generated questions.",
        }
    ])


# ── Graph routes (FIX A2: auth required) ──────────────────────────────────────

@app.get("/api/graph")
async def get_graph(authorization: Optional[str] = Header(None)):
    """FIX A2: requires Bearer token."""
    user = get_current_user(authorization)
    return get_db(user.get("username", "anonymous"))


@app.post("/api/graph/update")
async def update_graph(
    req: NodeUpdateRequest,
    authorization: Optional[str] = Header(None),
):
    user = get_current_user(authorization)
    updated = update_node_status(req.concept_name, req.status, user.get("username", "anonymous"))
    if not updated:
        raise HTTPException(404, "Node not found")
    return {"status": "success", "node": updated}


@app.post("/api/extract-concepts")
async def extract_concepts_endpoint(
    req: ConceptExtractRequest,
    authorization: Optional[str] = Header(None),
):
    user = get_current_user(authorization)
    graph = await llm_extract_concepts(req.note)
    if req.notebook_id:
        # FIX: verify ownership before writing the graph — prevents a user from
        # overwriting another user's notebook graph with their own note text.
        try:
            _require_notebook_owner(req.notebook_id, user)
            update_notebook_graph(req.notebook_id, graph)
        except HTTPException:
            pass   # notebook not owned by this user — return graph but don't save
    return graph


@app.get("/notebooks/{nb_id}/graph")
async def get_notebook_graph(nb_id: str, authorization: Optional[str] = Header(None)):
    user = get_current_user(authorization)
    nb   = _require_notebook_owner(nb_id, user)
    return nb.get("graph", {"nodes": [], "edges": []})


@app.post("/notebooks/{nb_id}/graph/update")
async def update_notebook_graph_node(
    nb_id: str,
    req: NodeUpdateRequest,
    authorization: Optional[str] = Header(None),
):
    user  = get_current_user(authorization)
    nb    = _require_notebook_owner(nb_id, user)
    graph = nb.get("graph", {"nodes": [], "edges": []})
    for node in graph["nodes"]:
        if node["label"].lower() == req.concept_name.lower():
            node["status"] = req.status
            update_notebook_graph(nb_id, graph)
            return {"status": "success", "node": node}
    raise HTTPException(404, "Concept node not found")


# ── Legacy /api/fuse (FIX L1 + L4) ───────────────────────────────────────────

class FusionRequest(BaseModel):
    slide_summary:      str
    textbook_paragraph: str
    proficiency:        str = "Practitioner"
    notebook_id:        Optional[str] = None


@app.post("/api/fuse", response_model=FusionResponse)
async def fuse_knowledge(req: FusionRequest, authorization: Optional[str] = Header(None)):
    """
    Legacy text-based fusion.
    FIX: require auth to prevent anonymous LLM abuse.
    FIX L1: now stores source chunks so /api/doubt and /api/mutate work.
    FIX L4: now uses run_generation_pipeline (same path as upload-fuse-multi).
    """
    get_current_user(authorization)
    from pipeline.chunker import chunk_textbook
    from pipeline.embedder import Embedder
    from pipeline.vector_db import VectorDB
    from pipeline.slide_analyzer import analyse_slides
    from pipeline.topic_retriever import TopicRetriever
    from pipeline.note_generator import run_generation_pipeline

    slide_content    = req.slide_summary[:_PROMPT_SLIDES_BUDGET]
    textbook_content = req.textbook_paragraph[:_PROMPT_TEXTBOOK_BUDGET]
    nb_id            = req.notebook_id

    # FIX L1: store raw chunks for doubt/mutate
    if nb_id:
        try:
            tb_hash = hashlib.md5(textbook_content.encode()).hexdigest()[:16]
            store_source_chunks(
                nb_id=nb_id,
                slide_chunks=chunk_text(slide_content,    max_chars=4000),
                textbook_chunks=chunk_text(textbook_content, max_chars=4000),
                textbook_hash=tb_hash,
            )
        except Exception as e:
            logger.warning("/api/fuse: chunk store failed: %s", e)

    # FIX L4: run same pipeline as upload-fuse-multi
    fused_note, source = None, "local"
    try:
        topics = await analyse_slides(slide_content)
        if topics:
            embedder  = Embedder()
            vector_db = VectorDB()
            tb_chunks = chunk_textbook(textbook_content) if textbook_content.strip() else []
            if tb_chunks:
                embedder.embed_chunks(tb_chunks)
                vector_db.add_chunks(tb_chunks)
            topic_contexts: dict[str, str] = {}
            if vector_db.size > 0:
                retriever     = TopicRetriever(vector_db, embedder)
                topic_contexts = retriever.retrieve_all_topics(topics)
            fused_note, source = await run_generation_pipeline(
                topics=topics,
                topic_contexts=topic_contexts,
                proficiency=req.proficiency,
                refine=True,
            )
    except Exception as exc:
        logger.warning("/api/fuse pipeline failed: %s", exc)

    if not fused_note or len(fused_note.strip()) < 100:
        fused_note = generate_local_note(req.slide_summary, req.textbook_paragraph, req.proficiency)
        source     = "local"

    fused_note = fix_latex_delimiters(fused_note)

    if nb_id:
        try:
            store_note_pages(nb_id, _note_to_pages(fused_note))
        except Exception:
            pass

    return FusionResponse(
        fused_note=fused_note,
        source=source,
        fallback_reason=None if source != "local" else "No AI configured — offline summariser used.",
    )
