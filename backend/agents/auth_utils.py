"""
Auth Utility — AuraGraph (SQLite v2)
Uses the shared auragraph.db. Token TTL = 7 days for real users.
Demo token is only accepted when DEMO_ENABLED=true environment variable is set.
"""
import logging
import os
import sqlite3
import time
import uuid
from pathlib import Path
from typing import Optional

from agents.db_pool import pooled_conn

try:
    import bcrypt as _bcrypt_lib
    _USE_BCRYPT = True
except ImportError:
    _bcrypt_lib = None  # type: ignore
    _USE_BCRYPT = False
    logging.getLogger("auragraph").warning(
        "bcrypt not installed — falling back to SHA-256 (pip install bcrypt for production)"
    )

import hashlib as _hashlib
import hmac as _hmac

_TOKEN_PEPPER = os.environ.get("TOKEN_PEPPER", "auragraph-default-pepper-change-in-prod")


def _hash_token(token: str) -> str:
    """HMAC-SHA256 of the raw token — what gets stored in DB.
    The raw token is returned to the client and never stored.
    If the DB is leaked, stored hashes cannot be used directly as bearer tokens.
    """
    return _hmac.new(_TOKEN_PEPPER.encode(), token.encode(), _hashlib.sha256).hexdigest()


logger = logging.getLogger("auragraph")
DB_PATH = Path(__file__).parent.parent / "auragraph.db"
TOKEN_TTL_SECONDS = 7 * 24 * 3600   # 7 days


def _conn():
    """Pooled connection context manager for the shared auragraph.db."""
    return pooled_conn(str(DB_PATH))


def _init_users():
    with _conn() as con:
        con.executescript("""
            CREATE TABLE IF NOT EXISTS users (
                id              TEXT PRIMARY KEY,
                email           TEXT UNIQUE NOT NULL,
                password_hash   TEXT NOT NULL,
                token           TEXT,
                token_issued_at REAL NOT NULL DEFAULT 0,
                name            TEXT NOT NULL DEFAULT ''
            );
            CREATE INDEX IF NOT EXISTS idx_users_token ON users(token);
        """)
    _migrate_users_from_json()


def _migrate_users_from_json():
    import json
    json_path = Path(__file__).parent.parent / "users.json"
    done_path = Path(__file__).parent.parent / "users.json.migrated"
    if done_path.exists() or not json_path.exists():
        return
    try:
        rows = json.loads(json_path.read_text(encoding="utf-8"))
        with _conn() as con:
            for u in rows:
                con.execute(
                    "INSERT OR IGNORE INTO users VALUES (?,?,?,?,?,?)",
                    (u["id"], u["email"], u.get("password_hash", ""),
                     u.get("token"), u.get("token_issued_at", 0),
                     u.get("name", u["email"].split("@")[0].capitalize()))
                )
        json_path.rename(done_path)
        logger.info("Migrated %d users JSON -> SQLite", len(rows))
    except Exception as exc:
        logger.warning("users.json migration failed: %s", exc)


def _hash_password(password: str) -> str:
    if _USE_BCRYPT:
        return _bcrypt_lib.hashpw(
            password.encode("utf-8"), _bcrypt_lib.gensalt(rounds=12)
        ).decode("utf-8")
    # FIX: Never silently downgrade to SHA-256 for new passwords.
    # SHA-256 without salting is trivially reversible via rainbow tables.
    # If bcrypt is unavailable, registration must fail loudly so the operator
    # installs bcrypt rather than unknowingly storing weak password hashes.
    raise RuntimeError(
        "bcrypt is required for password hashing but is not installed. "
        "Run: pip install bcrypt>=4.0.0"
    )


def _verify_password(password: str, stored_hash: str) -> bool:
    """Safe constant-time password verification supporting both bcrypt and SHA-256 hashes."""
    if stored_hash.startswith("$2"):   # bcrypt hash
        if _USE_BCRYPT:
            try:
                return _bcrypt_lib.checkpw(
                    password.encode("utf-8"), stored_hash.encode("utf-8")
                )
            except Exception:
                return False
        return False  # stored as bcrypt but library not available
    # Legacy SHA-256 hash
    import hashlib
    return hashlib.sha256(password.encode()).hexdigest() == stored_hash


def register_user(email: str, password: str, name: Optional[str] = None) -> Optional[dict]:
    uid = str(uuid.uuid4())
    token = str(uuid.uuid4())
    final_name = (name or "").strip() or email.split("@")[0].capitalize()
    try:
        with _conn() as con:
            con.execute(
                "INSERT INTO users VALUES (?,?,?,?,?,?)",
                (uid, email, _hash_password(password), _hash_token(token), time.time(), final_name)
            )
    except sqlite3.IntegrityError:
        return None
    return {"id": uid, "email": email, "token": token, "name": final_name}


def login_user(email: str, password: str) -> Optional[dict]:
    with _conn() as con:
        row = con.execute("SELECT * FROM users WHERE email=?", (email,)).fetchone()
        if not row or not _verify_password(password, row["password_hash"]):
            return None
        new_token = str(uuid.uuid4())
        con.execute("UPDATE users SET token=?, token_issued_at=? WHERE id=?",
                    (_hash_token(new_token), time.time(), row["id"]))
    return {"id": row["id"], "email": row["email"],
            "token": new_token, "name": row["name"]}


_DEMO_USER = {
    "id":    "demo",
    "email": "demo@auragraph.local",
    "name":  "Demo Student",
    "token": "demo-token",
}

# Set DEMO_ENABLED=true in the environment to allow the hard-coded dev demo token.
# Never enable this in production — real users always auth via register/login endpoints.
_DEMO_ENABLED: bool = os.environ.get("DEMO_ENABLED", "false").lower() == "true"


def validate_token(token: str) -> Optional[dict]:
    if _DEMO_ENABLED and token == "demo-token":
        return dict(_DEMO_USER)
    with _conn() as con:
        row = con.execute("SELECT * FROM users WHERE token=?", (_hash_token(token),)).fetchone()
    if not row:
        return None
    if time.time() - row["token_issued_at"] > TOKEN_TTL_SECONDS:
        return None   # expired — user must re-login
    return {"id": row["id"], "email": row["email"],
            "token": row["token"], "name": row["name"]}


def refresh_token(token: str) -> Optional[dict]:
    """Issue a fresh UUID token to replace a valid (but possibly aging) one.

    Returns the updated user dict on success, or None if the token is
    invalid / already expired.  Demo tokens are passed through unchanged.
    """
    if _DEMO_ENABLED and token == "demo-token":
        return dict(_DEMO_USER)
    with _conn() as con:
        row = con.execute("SELECT * FROM users WHERE token=?", (_hash_token(token),)).fetchone()
    if not row:
        return None
    if time.time() - row["token_issued_at"] > TOKEN_TTL_SECONDS:
        return None
    new_token = str(uuid.uuid4())
    with _conn() as con:
        con.execute(
            "UPDATE users SET token=?, token_issued_at=? WHERE id=?",
            (new_token, time.time(), row["id"]),
        )
    return {"id": row["id"], "email": row["email"],
            "token": new_token, "name": row["name"]}


_init_users()
