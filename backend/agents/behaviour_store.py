"""
agents/behaviour_store.py — User Behaviour Tracking & Personalisation
═══════════════════════════════════════════════════════════════════════

Tracks student learning behaviour and derives a personalisation profile
used to adapt note generation, doubt answering, and exam targeting.

Priority:
  1. Azure Cosmos DB (NoSQL)  — COSMOS_DB_URL + COSMOS_DB_KEY
     Container: "behaviour"  (separate from "mastery" container)
  2. SQLite fallback          — always available locally

Document schema (one document per user):
{
  "id": "<user_id>",
  "type": "behaviour",

  "doubts": [
    { "ts": "ISO", "notebook_id": "...", "topic": "...", "question": "...",
      "page_idx": 0, "resolved": true }
  ],

  "quiz_answers": [
    { "ts": "ISO", "notebook_id": "...", "concept": "...",
      "correct": true, "question": "..." }
  ],

  "highlights": [
    { "ts": "ISO", "notebook_id": "...", "text": "...", "page_idx": 0 }
  ],

  "sessions": [
    { "ts": "ISO", "notebook_id": "...", "duration_s": 120 }
  ],

  "profile": {
    "learning_style": "conceptual|visual|practice",
    "weak_concepts": ["...", ...],
    "strong_concepts": ["...", ...],
    "preferred_proficiency": "Foundations|Practitioner|Expert",
    "total_doubts": 0,
    "total_correct": 0,
    "total_questions": 0,
    "accuracy": 0.0,
    "last_updated": "ISO"
  }
}
"""
from __future__ import annotations

import json
import logging
import os
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

logger = logging.getLogger("auragraph")

STORE_DIR = Path(__file__).parent.parent / "behaviour_store"
STORE_DIR.mkdir(exist_ok=True)

_LOCKS: dict[str, threading.Lock] = {}
_LOCKS_LOCK = threading.Lock()


def _get_lock(user_id: str) -> threading.Lock:
    with _LOCKS_LOCK:
        if user_id not in _LOCKS:
            _LOCKS[user_id] = threading.Lock()
        return _LOCKS[user_id]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


# ── Cosmos DB backend ─────────────────────────────────────────────────────────

def _cosmos_configured() -> bool:
    url = os.environ.get("COSMOS_DB_URL", "")
    key = os.environ.get("COSMOS_DB_KEY", "")
    return bool(url and key
                and "placeholder" not in url.lower()
                and "your-" not in key.lower())


class _CosmosBackend:
    def __init__(self):
        from azure.cosmos import CosmosClient, PartitionKey
        url     = os.environ.get("COSMOS_DB_URL", "").rstrip("/")
        key     = os.environ.get("COSMOS_DB_KEY", "")
        db_name = os.environ.get("COSMOS_DB_DATABASE", "auragraph")
        ctr     = os.environ.get("COSMOS_DB_BEHAVIOUR_CONTAINER", "behaviour")

        client = CosmosClient(url, credential=key)
        db = client.create_database_if_not_exists(id=db_name)
        self._container = db.create_container_if_not_exists(
            id=ctr,
            partition_key=PartitionKey(path="/id"),
            offer_throughput=400,
        )
        logger.info("BehaviourStore: Cosmos DB connected (container=%s)", ctr)

    def load(self, user_id: str) -> dict:
        try:
            item = self._container.read_item(item=user_id, partition_key=user_id)
            return item
        except Exception:
            return _empty(user_id)

    def save(self, doc: dict):
        try:
            self._container.upsert_item(doc)
        except Exception as e:
            logger.warning("BehaviourStore Cosmos upsert failed: %s", e)


# ── SQLite fallback ──────────────────────────────────────────────────────────

class _SQLiteBackend:
    """Stores behaviour as a flat JSON file per user (simple, portable)."""

    def _path(self, user_id: str) -> Path:
        safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in user_id)
        return STORE_DIR / f"{safe}.json"

    def load(self, user_id: str) -> dict:
        p = self._path(user_id)
        if not p.exists():
            return _empty(user_id)
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            return _empty(user_id)

    def save(self, doc: dict):
        user_id = doc["id"]
        p = self._path(user_id)
        p.write_text(json.dumps(doc, indent=2, ensure_ascii=False), encoding="utf-8")


def _empty(user_id: str) -> dict:
    return {
        "id": user_id,
        "type": "behaviour",
        "doubts": [],
        "quiz_answers": [],
        "highlights": [],
        "sessions": [],
        "profile": {
            "learning_style": "balanced",
            "weak_concepts": [],
            "strong_concepts": [],
            "preferred_proficiency": "Practitioner",
            "total_doubts": 0,
            "total_correct": 0,
            "total_questions": 0,
            "accuracy": 0.0,
            "last_updated": _now(),
        },
    }


# ── Backend selection ─────────────────────────────────────────────────────────

_backend: Optional[_CosmosBackend | _SQLiteBackend] = None
_backend_lock = threading.Lock()


def _get_backend() -> _CosmosBackend | _SQLiteBackend:
    global _backend
    if _backend is not None:
        return _backend
    with _backend_lock:
        if _backend is not None:
            return _backend
        if _cosmos_configured():
            try:
                _backend = _CosmosBackend()
                return _backend
            except Exception as e:
                logger.warning("BehaviourStore: Cosmos init failed (%s) — using file fallback", e)
        _backend = _SQLiteBackend()
        logger.info("BehaviourStore: using file-based fallback")
        return _backend


# ── Profile derivation ────────────────────────────────────────────────────────

def _derive_profile(doc: dict) -> dict:
    """
    Compute a fresh personalisation profile from raw events.

    Learning style:
      conceptual — asks many doubts relative to quiz attempts
      visual     — highlights a lot relative to session time
      practice   — high quiz attempt volume, low doubt rate
      balanced   — default

    Weak/strong concepts come from quiz wrong/correct streaks and
    doubt frequency per topic.
    """
    doubts      = doc.get("doubts", [])
    answers     = doc.get("quiz_answers", [])
    highlights  = doc.get("highlights", [])

    total_doubts    = len(doubts)
    total_questions = len(answers)
    total_correct   = sum(1 for a in answers if a.get("correct"))
    accuracy        = round(total_correct / total_questions, 3) if total_questions else 0.0

    # Learning style heuristic
    if total_questions > 0:
        doubt_ratio = total_doubts / total_questions
        highlight_ratio = len(highlights) / max(total_questions, 1)
        if doubt_ratio > 0.5:
            style = "conceptual"    # asks lots of doubts → needs deep explanations
        elif highlight_ratio > 1.0:
            style = "visual"        # highlights a lot → visual/structured learner
        elif accuracy > 0.75:
            style = "practice"      # high accuracy → focus on harder challenges
        else:
            style = "balanced"
    else:
        style = "balanced"

    # Weak concepts: topics where wrong answers cluster, or doubts are repeated
    concept_wrong: dict[str, int] = {}
    concept_total: dict[str, int] = {}
    for a in answers:
        concept = a.get("concept", "").strip()
        if not concept:
            continue
        concept_total[concept] = concept_total.get(concept, 0) + 1
        if not a.get("correct"):
            concept_wrong[concept] = concept_wrong.get(concept, 0) + 1

    doubt_topics: dict[str, int] = {}
    for d in doubts:
        topic = d.get("topic", "").strip()
        if topic:
            doubt_topics[topic] = doubt_topics.get(topic, 0) + 1

    weak: list[str] = []
    strong: list[str] = []
    for concept, total in concept_total.items():
        wrong = concept_wrong.get(concept, 0)
        wrong_rate = wrong / total if total else 0
        if wrong_rate > 0.5 or doubt_topics.get(concept, 0) >= 2:
            weak.append(concept)
        elif wrong_rate < 0.2 and total >= 2:
            strong.append(concept)

    # Also add high-frequency doubt topics not already in weak
    for topic, count in doubt_topics.items():
        if count >= 2 and topic not in weak:
            weak.append(topic)

    # Preferred proficiency: infer from accuracy
    if accuracy >= 0.80 and total_questions >= 10:
        preferred_prof = "Expert"
    elif accuracy >= 0.60 and total_questions >= 5:
        preferred_prof = "Practitioner"
    else:
        preferred_prof = "Foundations"

    return {
        "learning_style": style,
        "weak_concepts": weak[:12],
        "strong_concepts": strong[:12],
        "preferred_proficiency": preferred_prof,
        "total_doubts": total_doubts,
        "total_correct": total_correct,
        "total_questions": total_questions,
        "accuracy": accuracy,
        "last_updated": _now(),
    }


# ── Public API ────────────────────────────────────────────────────────────────

def _load(user_id: str) -> dict:
    return _get_backend().load(user_id)


def _save(doc: dict):
    _get_backend().save(doc)


def track_doubt(user_id: str, notebook_id: str, topic: str,
                question: str, page_idx: int = 0):
    """Record that a student asked a doubt about a topic."""
    with _get_lock(user_id):
        doc = _load(user_id)
        doc["doubts"].append({
            "ts": _now(), "notebook_id": notebook_id,
            "topic": topic, "question": question, "page_idx": page_idx,
        })
        # Keep only last 200 doubts to bound document size
        doc["doubts"] = doc["doubts"][-200:]
        doc["profile"] = _derive_profile(doc)
        _save(doc)


def track_quiz_answer(user_id: str, notebook_id: str, concept: str,
                      question: str, correct: bool):
    """Record a single quiz answer (called per question, not per quiz)."""
    with _get_lock(user_id):
        doc = _load(user_id)
        doc["quiz_answers"].append({
            "ts": _now(), "notebook_id": notebook_id,
            "concept": concept, "question": question[:200], "correct": correct,
        })
        doc["quiz_answers"] = doc["quiz_answers"][-500:]
        doc["profile"] = _derive_profile(doc)
        _save(doc)


def track_highlight(user_id: str, notebook_id: str,
                    text: str, page_idx: int = 0):
    """Record that a student highlighted a piece of text."""
    with _get_lock(user_id):
        doc = _load(user_id)
        doc["highlights"].append({
            "ts": _now(), "notebook_id": notebook_id,
            "text": text[:300], "page_idx": page_idx,
        })
        doc["highlights"] = doc["highlights"][-300:]
        doc["profile"] = _derive_profile(doc)
        _save(doc)


def get_profile(user_id: str) -> dict:
    """Return the derived personalisation profile for a user."""
    doc = _load(user_id)
    profile = doc.get("profile")
    if not profile or not profile.get("last_updated"):
        # Derive fresh if missing
        profile = _derive_profile(doc)
    return profile


def get_personalisation_context(user_id: str) -> str:
    """
    Returns a formatted string to inject into LLM prompts.
    Empty string if no meaningful data exists yet.
    """
    profile = get_profile(user_id)

    # Only inject context if we have meaningful data
    if profile["total_questions"] < 3 and profile["total_doubts"] < 2:
        return ""

    lines = ["════ STUDENT LEARNING PROFILE (personalise to this) ════"]

    style = profile["learning_style"]
    style_desc = {
        "conceptual": "Prefers deep explanations and intuition over formulas. Use more analogies and step-by-step reasoning.",
        "visual":     "Benefits from structured layouts, tables, and visual organisation. Use more formatting and structured examples.",
        "practice":   "Strong test-taker. Prioritise challenging applications, edge cases, and harder worked examples.",
        "balanced":   "Mixed learning style. Balance theory, intuition, and practice examples.",
    }.get(style, "")
    lines.append(f"Learning style: {style.upper()} — {style_desc}")

    if profile["accuracy"] > 0 and profile["total_questions"] >= 3:
        pct = round(profile["accuracy"] * 100)
        lines.append(f"Quiz accuracy: {pct}% across {profile['total_questions']} questions")

    if profile["weak_concepts"]:
        lines.append(f"Weak areas (student struggles here — give extra depth): {', '.join(profile['weak_concepts'][:6])}")

    if profile["strong_concepts"]:
        lines.append(f"Strong areas (student knows these well — be concise): {', '.join(profile['strong_concepts'][:4])}")

    if profile["total_doubts"] >= 3:
        lines.append(f"This student asks many doubts ({profile['total_doubts']} total) — proactively address likely misconceptions.")

    lines.append("════════════════════════════════════════════════════════")
    return "\n".join(lines)
