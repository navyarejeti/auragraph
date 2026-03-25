"""
deps.py  — shared application state and utility helpers
All routers import from here so they never touch main.py internals.
"""
from __future__ import annotations

import asyncio
import logging
import os
import re
from typing import Optional

from fastapi import Header, HTTPException

logger = logging.getLogger("auragraph")

# ── Mutable globals — set by main.py lifespan before first request ─────────────
fusion_agent   = None
examiner_agent = None
kernel         = None
_db_write_lock: asyncio.Lock | None = None   # serialises SQLite notebook writes

# ── Env-driven constants ────────────────────────────────────────────────────────
MAX_TOTAL_UPLOAD_BYTES = int(os.environ.get("MAX_TOTAL_UPLOAD_MB", "500")) * 1024 * 1024
PIPELINE_TIMEOUT_S    = int(os.environ.get("PIPELINE_TIMEOUT_S",  "600"))   # 10 min — sufficient for large notes
_LLM_TOTAL_TIMEOUT_S  = int(os.environ.get("LLM_TOTAL_TIMEOUT_S", "120"))  # 120 s per LLM call — large outputs need this
_LLM_HOURLY_LIMIT     = int(os.environ.get("LLM_HOURLY_LIMIT",    "99999"))  # no rate limit
_LLM_DAILY_LIMIT      = int(os.environ.get("LLM_DAILY_LIMIT",     "99999"))  # no rate limit
_COST_PER_1K          = {"azure": 0.01, "groq": 0.0001, "local": 0.0}
_PROMPT_SLIDES_BUDGET   = 24_000
_PROMPT_TEXTBOOK_BUDGET = 24_000


# ── Auth helpers ───────────────────────────────────────────────────────────────

def get_current_user(authorization: Optional[str] = Header(None)):
    from agents.auth_utils import validate_token
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(401, "Missing or invalid token")
    token = authorization.split(" ", 1)[1]
    user  = validate_token(token)
    if not user:
        raise HTTPException(401, "Invalid or expired token")
    return user


def _require_notebook_owner(nb_id: str, user: dict) -> dict:
    from agents.notebook_store import get_notebook
    nb = get_notebook(nb_id)
    if not nb or nb["user_id"] != user["id"]:
        raise HTTPException(404, "Notebook not found")
    return nb


# ── LLM availability ───────────────────────────────────────────────────────────

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


# ── Rate limiting ──────────────────────────────────────────────────────────────

def _init_usage_table() -> None:
    from agents.auth_utils import DB_PATH
    import sqlite3
    con = sqlite3.connect(str(DB_PATH), timeout=30, check_same_thread=False)
    con.execute("PRAGMA journal_mode=WAL")
    con.executescript("""
        CREATE TABLE IF NOT EXISTS llm_usage (
            user_id      TEXT    NOT NULL,
            hour_bucket  TEXT    NOT NULL,
            day_bucket   TEXT    NOT NULL,
            calls        INTEGER NOT NULL DEFAULT 0,
            est_tokens   INTEGER NOT NULL DEFAULT 0,
            est_cost_usd REAL    NOT NULL DEFAULT 0.0,
            PRIMARY KEY (user_id, hour_bucket)
        );
        CREATE INDEX IF NOT EXISTS idx_llm_usage_user_day
            ON llm_usage(user_id, day_bucket);
    """)
    con.commit()
    con.close()


def _check_llm_rate_limit(user_id: str) -> None:
    from agents.auth_utils import DB_PATH
    import sqlite3
    from datetime import datetime, timezone
    now         = datetime.now(timezone.utc)
    hour_bucket = now.strftime("%Y-%m-%dT%H")
    day_bucket  = now.strftime("%Y-%m-%d")
    con = sqlite3.connect(str(DB_PATH), timeout=10, check_same_thread=False)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA journal_mode=WAL")
    try:
        row = con.execute(
            "SELECT calls FROM llm_usage WHERE user_id=? AND hour_bucket=?",
            (user_id, hour_bucket)
        ).fetchone()
        if row and row["calls"] >= _LLM_HOURLY_LIMIT:
            raise HTTPException(429, f"Rate limit: max {_LLM_HOURLY_LIMIT} AI calls per hour.")
        daily = con.execute(
            "SELECT SUM(calls) as total FROM llm_usage WHERE user_id=? AND day_bucket=?",
            (user_id, day_bucket)
        ).fetchone()
        if daily and (daily["total"] or 0) >= _LLM_DAILY_LIMIT:
            raise HTTPException(429, f"Daily limit: max {_LLM_DAILY_LIMIT} AI calls. Resets at midnight UTC.")
    finally:
        con.close()


def _record_llm_call(user_id: str, source: str, est_tokens: int = 2000) -> None:
    from agents.auth_utils import DB_PATH
    import sqlite3
    from datetime import datetime, timezone
    now         = datetime.now(timezone.utc)
    hour_bucket = now.strftime("%Y-%m-%dT%H")
    day_bucket  = now.strftime("%Y-%m-%d")
    cost        = (_COST_PER_1K.get(source, 0.0) * est_tokens) / 1000
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
    except Exception as exc:
        logger.debug("_record_llm_call failed (non-fatal): %s", exc)


# ── Async LLM call wrappers ────────────────────────────────────────────────────

async def _groq_chat(messages: list[dict], max_tokens: int = 16000) -> str:
    import httpx
    api_key     = os.environ.get("GROQ_API_KEY", "")
    model       = os.environ.get("GROQ_MODEL", "llama-3.3-70b-versatile")
    payload     = {"model": model, "messages": messages,
                   "max_tokens": max_tokens, "temperature": 0.3}
    req_headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}

    async def _do() -> str:
        for attempt in range(3):
            async with httpx.AsyncClient(timeout=45.0) as client:
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
                await asyncio.sleep(2 ** attempt)
                continue
            resp.raise_for_status()
            return resp.json()["choices"][0]["message"]["content"].strip()
        raise RuntimeError("Groq failed after 3 attempts")

    try:
        return await asyncio.wait_for(_do(), timeout=_LLM_TOTAL_TIMEOUT_S)
    except asyncio.TimeoutError:
        raise RuntimeError(f"Groq timed out after {_LLM_TOTAL_TIMEOUT_S}s")


async def _azure_chat(messages: list[dict], max_tokens: int = 16000) -> str:
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
            async with httpx.AsyncClient(timeout=45.0) as client:
                resp = await client.post(url, json=payload, headers=req_headers)
            if resp.status_code == 429 and attempt < 2:
                wait = int(resp.headers.get("Retry-After", str(3 * (attempt + 1))))
                await asyncio.sleep(wait)
                continue
            if resp.status_code in (500, 502, 503, 504) and attempt < 2:
                await asyncio.sleep(2 ** attempt)
                continue
            resp.raise_for_status()
            return resp.json()["choices"][0]["message"]["content"].strip()
        raise RuntimeError("Azure failed after 3 attempts")

    try:
        return await asyncio.wait_for(_do(), timeout=_LLM_TOTAL_TIMEOUT_S)
    except asyncio.TimeoutError:
        raise RuntimeError(f"Azure timed out after {_LLM_TOTAL_TIMEOUT_S}s")


async def _groq_doubt(doubt: str, slide_ctx: str, textbook_ctx: str, note_page: str,
                      student_context: str = "") -> str:
    from agents.verifier_agent import DOUBT_ANSWER_PROMPT
    prompt = (
        DOUBT_ANSWER_PROMPT
        .replace("{{$doubt}}",            doubt)
        .replace("{{$note_page}}",        note_page)
        .replace("{{$slide_context}}",    slide_ctx)
        .replace("{{$textbook_context}}", textbook_ctx)
        .replace("{{$student_context}}",  student_context)
    )
    return await _groq_chat([{"role": "user", "content": prompt}])


async def _llm_mutate(
    note_page: str, doubt: str, slide_ctx: str, textbook_ctx: str
) -> tuple[Optional[str], Optional[str], Optional[str], str]:
    from agents.fusion_agent import FusionAgent
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
            text    = await _groq_chat([{"role": "user", "content": prompt}])
            mutated, gap, answer = FusionAgent._parse_mutate_response(text)
            return mutated, gap, answer, "groq"
        except Exception as e:
            logger.warning("Groq mutation failed: %s", e)
    return None, None, None, "none"


async def _verify_note(note: str, slide_ctx: str, textbook_ctx: str) -> tuple[str, bool, str]:
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
        return note, False, ""
    verified, was_corrected, summary = parse_self_review_response(raw)
    if not verified or len(verified.strip()) < 100:
        return note, False, ""
    # Shrink guard: if the LLM returned less than 60% of the original note it
    # almost certainly hit a token cap and truncated.  Discard the truncated
    # output rather than overwriting a long, correct note with a short one.
    if len(verified.strip()) < 0.60 * len(note.strip()):
        logger.warning(
            "_verify_note: verified note shrank from %d → %d chars (>40%% loss) — "
            "discarding and keeping original",
            len(note), len(verified),
        )
        return note, False, ""
    return verified, was_corrected, summary


# ── Note utilities ─────────────────────────────────────────────────────────────

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
    """
    Inject each figure exactly ONCE into the best-matching ## section.

    Strategy (two-pass):

    Pass 1 — Assign each topic_figures entry to the single best ## heading:
        Score every topic_figures key against every ## heading using Jaccard.
        Each topic_figures entry is claimed by the heading that scores highest.
        Once claimed, it cannot match any other heading — preventing the same
        image from appearing under "Function of a Random Variable" AND under
        "Discrete Case of Function of a Random Variable" (which shares the same
        words and would also score above the threshold).

    Pass 2 — Inject:
        Walk the note. For each ## heading, check if it was assigned figures.
        If so, either inject immediately (no ### present) or hold pending until
        the best-matching ### subheading is found (Jaccard > 0.08 on description).
        Any still-pending figures flush at the next ## or at end of note.
    """
    if not topic_figures:
        return note

    STOP = {
        'a','an','the','is','are','of','in','on','at','to','for','with',
        'its','this','that','these','those','it','as','by','be','was','were',
        'showing','shows','figure','diagram','image','graph','chart','plot',
        'from','and','or','not','each','which','where',
    }

    def _words(s: str) -> set:
        s = s.replace('-', ' ').replace('_', ' ')
        return set(re.sub(r'[^\w\s]', '', s.lower()).split()) - STOP

    def _jaccard(a: str, b: str) -> float:
        wa, wb = _words(a), _words(b)
        if not wa or not wb:
            return 0.0
        return len(wa & wb) / len(wa | wb)

    def _figure_block(figs: list) -> list[str]:
        out = ['']
        for description, url in figs:
            safe_alt = re.sub(r'\s+', ' ', (description or 'Figure')).strip()
            safe_alt = safe_alt.replace('[', '(').replace(']', ')').replace('"', "'")
            out.append(f'![{safe_alt}]({url})')
            out.append('')
        return out

    def _section_has_subsections(lines: list[str], from_idx: int) -> bool:
        for j in range(from_idx + 1, len(lines)):
            if lines[j].startswith('## '): return False
            if lines[j].startswith('### '): return True
        return False

    # ── Pass 1: assign each topic_figures entry to its best ## heading ──────
    # Extract all ## headings from the note in order
    lines = note.split('\n')
    headings = [(i, line[3:].strip()) for i, line in enumerate(lines) if line.startswith('## ')]

    # For each topic_figures key, find the heading with the highest Jaccard score.
    # heading_figures maps line-index → list of (desc, url) figures assigned to it.
    heading_figures: dict[int, list] = {}
    for tname, figs in topic_figures.items():
        best_score, best_idx = 0.0, None
        for line_idx, heading_text in headings:
            score = _jaccard(tname, heading_text)
            if score > best_score:
                best_score, best_idx = score, line_idx
        # Only claim if there is meaningful overlap (threshold 0.15 — tighter than
        # before to avoid "Function of a Random Variable" matching "Discrete Case of
        # Function of a Random Variable" just because they share the same words)
        if best_idx is not None and best_score >= 0.15:
            heading_figures.setdefault(best_idx, []).extend(figs)

    if not heading_figures:
        return note

    # ── Pass 2: walk note and inject figures at the assigned headings ────────
    result: list[str] = []
    pending_figs_by_desc: list[tuple[list, str]] = []

    i = 0
    while i < len(lines):
        line = lines[i]

        if line.startswith('## '):
            # Flush pending from the outgoing section
            for figs, _ in pending_figs_by_desc:
                result.extend(_figure_block(figs))
            pending_figs_by_desc = []

            result.append(line)

            assigned = heading_figures.get(i, [])
            if assigned:
                for desc, url in assigned:
                    pending_figs_by_desc.append(([(desc, url)], desc))
                if not _section_has_subsections(lines, i):
                    for figs, _ in pending_figs_by_desc:
                        result.extend(_figure_block(figs))
                    pending_figs_by_desc = []

            i += 1
            continue

        if line.startswith('### ') and pending_figs_by_desc:
            subheading = line[4:].strip()
            result.append(line)
            still_pending = []
            for figs, img_desc in pending_figs_by_desc:
                if _jaccard(subheading, img_desc) > 0.08:
                    result.extend(_figure_block(figs))
                else:
                    still_pending.append((figs, img_desc))
            pending_figs_by_desc = still_pending
            i += 1
            continue

        result.append(line)
        i += 1

    for figs, _ in pending_figs_by_desc:
        result.extend(_figure_block(figs))

    return '\n'.join(result)


def _note_to_pages(note: str) -> list[str]:
    """Split note into pages mirroring the frontend useMemo pagination.
    Each ## section is its own page — no merging across topic sections.
    This ensures page count equals topic count, matching what the user sees.
    """
    if not note.strip():
        return []
    sections = re.split(r'(?m)^(?=## )', note.strip())
    pages = [p.strip() for p in sections if p.strip()]
    return pages if pages else [note.strip()]
