"""
Aura XP storage (server-side) using SQLite.
Persists per-user gamification stats so Aura is available across logins/devices.
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from agents.db_pool import pooled_conn

DB_PATH = Path(__file__).parent.parent / "auragraph.db"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _conn():
    return pooled_conn(str(DB_PATH))


def _default() -> dict:
    return {
        "xp": 0,
        "quizzesCompleted": 0,
        "correctAnswers": 0,
        "totalAnswers": 0,
        "doubtsAsked": 0,
        "highlightsAdded": 0,
        "activeTheme": "default",
    }


def _sanitize(data: dict) -> dict:
    base = _default()
    out = dict(base)
    if not isinstance(data, dict):
        return out

    for key in [
        "xp", "quizzesCompleted", "correctAnswers", "totalAnswers", "doubtsAsked", "highlightsAdded",
    ]:
        try:
            out[key] = max(0, int(data.get(key, base[key])))
        except Exception:
            out[key] = base[key]

    theme = str(data.get("activeTheme", base["activeTheme"]) or "default").strip()
    out["activeTheme"] = theme if theme else "default"
    return out


def _init_tables() -> None:
    with _conn() as con:
        con.executescript(
            """
            CREATE TABLE IF NOT EXISTS aura_state (
                user_id            TEXT PRIMARY KEY,
                xp                 INTEGER NOT NULL DEFAULT 0,
                quizzes_completed  INTEGER NOT NULL DEFAULT 0,
                correct_answers    INTEGER NOT NULL DEFAULT 0,
                total_answers      INTEGER NOT NULL DEFAULT 0,
                doubts_asked       INTEGER NOT NULL DEFAULT 0,
                highlights_added   INTEGER NOT NULL DEFAULT 0,
                active_theme       TEXT NOT NULL DEFAULT 'default',
                updated_at         TEXT NOT NULL
            );
            """
        )


def get_aura(user_id: str) -> dict:
    with _conn() as con:
        row = con.execute(
            "SELECT * FROM aura_state WHERE user_id=?",
            (user_id,),
        ).fetchone()

    if not row:
        return _default()

    return {
        "xp": int(row["xp"] or 0),
        "quizzesCompleted": int(row["quizzes_completed"] or 0),
        "correctAnswers": int(row["correct_answers"] or 0),
        "totalAnswers": int(row["total_answers"] or 0),
        "doubtsAsked": int(row["doubts_asked"] or 0),
        "highlightsAdded": int(row["highlights_added"] or 0),
        "activeTheme": row["active_theme"] or "default",
    }


def save_aura(user_id: str, data: dict) -> dict:
    aura = _sanitize(data)
    with _conn() as con:
        con.execute(
            """
            INSERT INTO aura_state (
                user_id, xp, quizzes_completed, correct_answers, total_answers,
                doubts_asked, highlights_added, active_theme, updated_at
            ) VALUES (?,?,?,?,?,?,?,?,?)
            ON CONFLICT(user_id) DO UPDATE SET
                xp                = excluded.xp,
                quizzes_completed = excluded.quizzes_completed,
                correct_answers   = excluded.correct_answers,
                total_answers     = excluded.total_answers,
                doubts_asked      = excluded.doubts_asked,
                highlights_added  = excluded.highlights_added,
                active_theme      = excluded.active_theme,
                updated_at        = excluded.updated_at
            """,
            (
                user_id,
                aura["xp"],
                aura["quizzesCompleted"],
                aura["correctAnswers"],
                aura["totalAnswers"],
                aura["doubtsAsked"],
                aura["highlightsAdded"],
                aura["activeTheme"],
                _now(),
            ),
        )
    return aura


_init_tables()
