"""Tests for auth_utils — run: cd backend && python -m pytest tests/test_auth.py -v"""
import sys, os, pytest
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

def _patch_db(monkeypatch, tmp_path):
    import agents.auth_utils as au
    db = tmp_path / "test_auth.db"
    monkeypatch.setattr(au, "DB_PATH", db)
    au._init_users()

def test_hash_not_plaintext():
    from agents.auth_utils import _hash_password
    h = _hash_password("hunter2")
    assert h != "hunter2" and len(h) > 20

def test_verify_correct():
    from agents.auth_utils import _hash_password, _verify_password
    h = _hash_password("correct-horse")
    assert _verify_password("correct-horse", h) is True

def test_verify_wrong():
    from agents.auth_utils import _hash_password, _verify_password
    h = _hash_password("right")
    assert _verify_password("wrong", h) is False

def test_verify_legacy_sha256():
    import hashlib
    from agents.auth_utils import _verify_password
    pw = "legacy-pw"
    legacy = hashlib.sha256(pw.encode()).hexdigest()
    assert _verify_password(pw, legacy) is True

def test_register_ok(monkeypatch, tmp_path):
    _patch_db(monkeypatch, tmp_path)
    from agents.auth_utils import register_user
    r = register_user("alice@t.com", "pass")
    assert r is not None and "token" in r and r["email"] == "alice@t.com"

def test_register_duplicate(monkeypatch, tmp_path):
    _patch_db(monkeypatch, tmp_path)
    from agents.auth_utils import register_user
    register_user("bob@t.com", "p1")
    assert register_user("bob@t.com", "p2") is None

def test_login_ok(monkeypatch, tmp_path):
    _patch_db(monkeypatch, tmp_path)
    from agents.auth_utils import register_user, login_user
    register_user("carol@t.com", "mysecret")
    r = login_user("carol@t.com", "mysecret")
    assert r is not None and "token" in r

def test_login_wrong_pw(monkeypatch, tmp_path):
    _patch_db(monkeypatch, tmp_path)
    from agents.auth_utils import register_user, login_user
    register_user("dave@t.com", "correct")
    assert login_user("dave@t.com", "wrong") is None

def test_login_unknown_user(monkeypatch, tmp_path):
    _patch_db(monkeypatch, tmp_path)
    from agents.auth_utils import login_user
    assert login_user("ghost@t.com", "any") is None

def test_login_fresh_token(monkeypatch, tmp_path):
    _patch_db(monkeypatch, tmp_path)
    from agents.auth_utils import register_user, login_user
    register_user("eve@t.com", "px")
    t1 = login_user("eve@t.com", "px")["token"]
    t2 = login_user("eve@t.com", "px")["token"]
    assert t1 != t2

def test_validate_token(monkeypatch, tmp_path):
    _patch_db(monkeypatch, tmp_path)
    from agents.auth_utils import register_user, validate_token
    reg = register_user("frank@t.com", "qwerty")
    u = validate_token(reg["token"])
    assert u is not None and u["email"] == "frank@t.com"

def test_validate_bad_token(monkeypatch, tmp_path):
    _patch_db(monkeypatch, tmp_path)
    from agents.auth_utils import validate_token
    assert validate_token("garbage") is None

def test_demo_token(monkeypatch, tmp_path):
    _patch_db(monkeypatch, tmp_path)
    import agents.auth_utils as au
    monkeypatch.setattr(au, "_DEMO_ENABLED", True)
    from agents.auth_utils import validate_token
    u = validate_token("demo-token")
    assert u is not None and u["id"] == "demo"
