"""
HTTP integration tests — spin up the real FastAPI app with TestClient.

These tests hit actual HTTP endpoints with a real (tmp) SQLite database.
They verify auth flows, notebook ownership isolation, and that unauthenticated
callers are rejected with 401 — not just that handler functions return the
right values in unit isolation.

Run: cd backend && python -m pytest tests/test_http.py -v --tb=short
"""
import sys, os, json, pytest
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)) + "/..")

# ── Patch DB paths before importing the app ───────────────────────────────────

@pytest.fixture(scope="module")
def tmp_db(tmp_path_factory):
    """Return a temporary SQLite path used for the whole test module."""
    return str(tmp_path_factory.mktemp("db") / "test_auragraph.db")


@pytest.fixture(scope="module")
def client(tmp_db):
    """Spin up the real FastAPI app with a throw-away database."""
    import agents.auth_utils as au
    import agents.notebook_store as ns
    import agents.mastery_store as ms
    from pathlib import Path

    db = Path(tmp_db)
    au.DB_PATH = db
    ns.DB_PATH = db
    ms.DB_PATH = db
    # Reinitialise tables against the tmp DB
    au._init_users()
    ns._init_db()
    ms._init_tables()

    from fastapi.testclient import TestClient
    from main import app
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c


# ── Helpers ───────────────────────────────────────────────────────────────────

def _register(client, email, password="Test1234!"):
    return client.post("/auth/register", json={"email": email, "password": password})


def _login(client, email, password="Test1234!"):
    r = client.post("/auth/login", json={"email": email, "password": password})
    return r.json().get("token")


def _auth(token):
    return {"Authorization": f"Bearer {token}"}


# ── Health ────────────────────────────────────────────────────────────────────

def test_health(client):
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json().get("status") == "ok"


def test_health_has_request_id_header(client):
    r = client.get("/health")
    assert "x-request-id" in {k.lower() for k in r.headers}


# ── Auth flows ─────────────────────────────────────────────────────────────────

def test_register_new_user(client):
    r = _register(client, "alice@example.com")
    assert r.status_code == 200
    body = r.json()
    assert body.get("token")
    assert body.get("email") == "alice@example.com"


def test_register_duplicate_email(client):
    _register(client, "dup@example.com")
    r = _register(client, "dup@example.com")
    assert r.status_code == 409


def test_login_correct_credentials(client):
    _register(client, "bob@example.com")
    r = client.post("/auth/login", json={"email": "bob@example.com", "password": "Test1234!"})
    assert r.status_code == 200
    assert r.json().get("token")


def test_login_wrong_password(client):
    _register(client, "carol@example.com")
    r = client.post("/auth/login", json={"email": "carol@example.com", "password": "WrongPass"})
    assert r.status_code == 401


def test_login_unknown_email(client):
    # Password must meet min_length=8 so we get 401 (wrong user) not 422 (validation)
    r = client.post("/auth/login", json={"email": "nobody@example.com", "password": "x" * 8})
    assert r.status_code == 401


# ── Protected routes reject unauthenticated callers ───────────────────────────

def test_get_notebooks_requires_auth(client):
    r = client.get("/notebooks")
    assert r.status_code == 401


def test_create_notebook_requires_auth(client):
    r = client.post("/notebooks", json={"name": "No Auth NB", "course": "Test"})
    assert r.status_code == 401


def test_doubt_requires_auth(client):
    r = client.post("/api/doubt",
                    json={"notebook_id": "nb-fake", "doubt": "what is x?"})
    assert r.status_code == 401


def test_mutate_requires_auth(client):
    r = client.post("/api/mutate",
                    json={"notebook_id": "nb-fake", "doubt": "explain"})
    assert r.status_code == 401


# ── Notebook CRUD flow ────────────────────────────────────────────────────────

def test_create_and_list_notebook(client):
    _register(client, "dave@example.com")
    token = _login(client, "dave@example.com")

    r = client.post("/notebooks",
                    json={"name": "DSP Notes", "course": "EEL501"},
                    headers=_auth(token))
    assert r.status_code == 200
    nb = r.json()
    assert nb["name"] == "DSP Notes"
    nb_id = nb["id"]

    r2 = client.get("/notebooks", headers=_auth(token))
    assert r2.status_code == 200
    payload = r2.json()
    # Response is now paginated: {total, offset, limit, notebooks: [...]}
    assert "notebooks" in payload, "Expected paginated response with 'notebooks' key"
    assert "total" in payload
    ids = [n["id"] for n in payload["notebooks"]]
    assert nb_id in ids


def test_get_notebook_not_found_for_wrong_user(client):
    """User B cannot retrieve User A's notebook — should get 404."""
    _register(client, "eve@example.com")
    _register(client, "frank@example.com")
    token_e = _login(client, "eve@example.com")
    token_f = _login(client, "frank@example.com")

    r = client.post("/notebooks",
                    json={"name": "Eve's Private NB", "course": "CS101"},
                    headers=_auth(token_e))
    nb_id = r.json()["id"]

    # Frank tries to fetch Eve's notebook
    r2 = client.get(f"/notebooks/{nb_id}", headers=_auth(token_f))
    assert r2.status_code == 404


def test_patch_note_ownership(client):
    """User B cannot patch User A's note."""
    _register(client, "grace@example.com")
    _register(client, "heidi@example.com")
    token_g = _login(client, "grace@example.com")
    token_h = _login(client, "heidi@example.com")

    r = client.post("/notebooks",
                    json={"name": "Grace NB", "course": "Math"},
                    headers=_auth(token_g))
    nb_id = r.json()["id"]

    r2 = client.patch(f"/notebooks/{nb_id}/note",
                      json={"note": "Hacked!"},
                      headers=_auth(token_h))
    assert r2.status_code == 404


def test_delete_notebook(client):
    _register(client, "ivan@example.com")
    token = _login(client, "ivan@example.com")

    r = client.post("/notebooks",
                    json={"name": "To Delete", "course": "X"},
                    headers=_auth(token))
    nb_id = r.json()["id"]

    rd = client.delete(f"/notebooks/{nb_id}", headers=_auth(token))
    assert rd.status_code == 200

    r2 = client.get(f"/notebooks/{nb_id}", headers=_auth(token))
    assert r2.status_code == 404


# ── Sections ──────────────────────────────────────────────────────────────────

def test_sections_crud(client):
    _register(client, "judy@example.com")
    token = _login(client, "judy@example.com")

    nb_id = client.post("/notebooks",
                        json={"name": "Sections NB", "course": "Phys"},
                        headers=_auth(token)).json()["id"]

    # Create
    r = client.post(f"/notebooks/{nb_id}/sections",
                    json={"title": "Fourier Basics", "note_type": "topic"},
                    headers=_auth(token))
    assert r.status_code == 200
    sec_id = r.json()["id"]

    # List
    r2 = client.get(f"/notebooks/{nb_id}/sections", headers=_auth(token))
    assert r2.status_code == 200
    assert any(s["id"] == sec_id for s in r2.json())

    # Delete
    rd = client.delete(f"/notebooks/{nb_id}/sections/{sec_id}", headers=_auth(token))
    assert rd.status_code == 200
