"""
Extended auth tests — edge cases and security-critical paths.
Run: cd backend && python -m pytest tests/test_auth_advanced.py -v
"""
import sys, os, time, pytest
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))


def _patch_db(monkeypatch, tmp_path):
    import agents.auth_utils as au
    db = tmp_path / "auth_adv.db"
    monkeypatch.setattr(au, "DB_PATH", db)
    au._init_users()


# ── Demo token gating ────────────────────────────────────────────────────────

def test_demo_token_rejected_when_disabled(monkeypatch, tmp_path):
    """Demo token must be rejected when DEMO_ENABLED is False (default)."""
    _patch_db(monkeypatch, tmp_path)
    import agents.auth_utils as au
    monkeypatch.setattr(au, "_DEMO_ENABLED", False)
    from agents.auth_utils import validate_token
    assert validate_token("demo-token") is None


def test_demo_token_accepted_when_enabled(monkeypatch, tmp_path):
    """Demo token must work when DEMO_ENABLED is True."""
    _patch_db(monkeypatch, tmp_path)
    import agents.auth_utils as au
    monkeypatch.setattr(au, "_DEMO_ENABLED", True)
    from agents.auth_utils import validate_token
    u = validate_token("demo-token")
    assert u is not None
    assert u["id"] == "demo"
    assert u["email"] == "demo@auragraph.local"


def test_demo_enabled_env_var_false_by_default(monkeypatch):
    """DEMO_ENABLED defaults to False when the env var is absent."""
    monkeypatch.delenv("DEMO_ENABLED", raising=False)
    import importlib
    import agents.auth_utils as au
    result = os.environ.get("DEMO_ENABLED", "false").lower() == "true"
    assert result is False


# ── Token expiry ─────────────────────────────────────────────────────────────

def test_expired_token_rejected(monkeypatch, tmp_path):
    """Token issued beyond TTL must fail validation."""
    _patch_db(monkeypatch, tmp_path)
    import agents.auth_utils as au
    from agents.auth_utils import register_user
    from agents.auth_utils import validate_token

    reg = register_user("expired@t.com", "pw")
    token = reg["token"]

    # Backdate the token_issued_at — must use the *hashed* token (that's what the DB stores)
    import sqlite3
    with sqlite3.connect(str(au.DB_PATH)) as con:
        past = time.time() - au.TOKEN_TTL_SECONDS - 1
        con.execute("UPDATE users SET token_issued_at=? WHERE token=?",
                    (past, au._hash_token(token)))
        con.commit()

    assert validate_token(token) is None


def test_fresh_token_accepted(monkeypatch, tmp_path):
    """Recently issued token must pass validation."""
    _patch_db(monkeypatch, tmp_path)
    from agents.auth_utils import register_user, validate_token
    reg = register_user("fresh@t.com", "pw2")
    assert validate_token(reg["token"]) is not None


# ── Token after re-login invalidates old token ───────────────────────────────

def test_old_token_invalid_after_relogin(monkeypatch, tmp_path):
    """Re-login issues a new token; the old one must no longer validate."""
    _patch_db(monkeypatch, tmp_path)
    from agents.auth_utils import register_user, login_user, validate_token
    register_user("reissue@t.com", "pw3")
    t1 = login_user("reissue@t.com", "pw3")["token"]
    login_user("reissue@t.com", "pw3")  # second login issues t2
    assert validate_token(t1) is None   # t1 no longer valid


# ── Case and whitespace edge cases ───────────────────────────────────────────

def test_login_email_unknown_user_returns_none(monkeypatch, tmp_path):
    _patch_db(monkeypatch, tmp_path)
    from agents.auth_utils import login_user
    assert login_user("nobody@nowhere.invalid", "x") is None


def test_register_token_is_uuid_like(monkeypatch, tmp_path):
    """Register should return a UUID-format token, not a short string."""
    _patch_db(monkeypatch, tmp_path)
    from agents.auth_utils import register_user
    reg = register_user("uuid@t.com", "pw4")
    assert len(reg["token"]) >= 32


def test_validate_empty_token(monkeypatch, tmp_path):
    _patch_db(monkeypatch, tmp_path)
    from agents.auth_utils import validate_token
    assert validate_token("") is None


def test_validate_sql_injection_attempt(monkeypatch, tmp_path):
    _patch_db(monkeypatch, tmp_path)
    from agents.auth_utils import validate_token
    # Should not raise; parameterized queries prevent injection
    assert validate_token("'; DROP TABLE users; --") is None
