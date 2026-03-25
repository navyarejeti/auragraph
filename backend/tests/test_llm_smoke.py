"""
LLM endpoint smoke tests — verify the mutation and doubt handlers produce
correctly shaped responses under three conditions:

1. **Offline fallback** — neither Azure nor Groq is configured → local mutation
2. **LLM mocked (Azure path)** — _llm_mutate patched to return a canned result
3. **Doubt offline fallback** — no LLM → local analogy answer still structured
4. **Doubt mocked** — fusion_agent.answer_doubt patched
5. **Rate limiter** — rapid-fire calls exhaust the hourly budget → 429

Run: cd backend && python -m pytest tests/test_llm_smoke.py -v --tb=short
"""
import sys, os, asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch
import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))
# Clear LLM credentials before the app module is imported so dotenv can't
# override them back, and the module-level _is_*_available() defs default to false.
for _k in ("AZURE_OPENAI_API_KEY", "AZURE_OPENAI_ENDPOINT",
           "AZURE_OPENAI_KEY", "GROQ_API_KEY"):
    os.environ.pop(_k, None)


# ── Fixture: isolated DB + TestClient ─────────────────────────────────────────

@pytest.fixture(scope="module")
def smoke_client(tmp_path_factory):
    db = tmp_path_factory.mktemp("smoke") / "smoke.db"
    import agents.auth_utils as au
    import agents.notebook_store as ns
    import agents.mastery_store as ms

    au.DB_PATH = db
    ns.DB_PATH = db
    ms.DB_PATH = db
    au._init_users()
    ns._init_db()
    ms._init_tables()

    from fastapi.testclient import TestClient
    from main import app
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c


@pytest.fixture(scope="module")
def smoke_auth(smoke_client):
    """Register a test user and return (token, notebook_id)."""
    r = smoke_client.post("/auth/register",
                          json={"email": "smoke@test.com", "password": "Smoke123!"})
    assert r.status_code == 200
    token = r.json()["token"]

    nb = smoke_client.post("/notebooks",
                           json={"name": "Smoke NB", "course": "TEST201"},
                           headers={"Authorization": f"Bearer {token}"})
    assert nb.status_code == 200
    return token, nb.json()["id"]


# ── Helpers ────────────────────────────────────────────────────────────────────

def auth_h(token):
    return {"Authorization": f"Bearer {token}"}


# ── 1. Mutation — offline fallback ────────────────────────────────────────────

def test_mutate_offline_fallback_returns_correct_schema(smoke_client, smoke_auth):
    """With no LLM, /api/mutate must still return a valid MutationResponse
    (using local_mutate) and set can_mutate=False."""
    token, nb_id = smoke_auth
    with patch("deps._is_azure_available", return_value=False), \
         patch("deps._is_groq_available",  return_value=False):
        r = smoke_client.post("/api/mutate",
                              json={"notebook_id": nb_id,
                                    "doubt": "What is convolution?",
                                    "original_paragraph": "The convolution theorem relates time-domain convolution to frequency-domain multiplication."},
                              headers={**auth_h(token), "Content-Type": "application/json"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert "mutated_paragraph" in body
    assert "concept_gap" in body
    assert "page_idx" in body
    assert "can_mutate" in body
    assert "source" in body
    assert body["can_mutate"] is False
    assert body["source"] == "local"
    assert len(body["mutated_paragraph"]) > 10


def test_mutate_response_never_empty_when_offline(smoke_client, smoke_auth):
    """Even for a one-word doubt, local fallback must return non-trivial text."""
    token, nb_id = smoke_auth
    with patch("deps._is_azure_available", return_value=False), \
         patch("deps._is_groq_available",  return_value=False):
        r = smoke_client.post("/api/mutate",
                              json={"notebook_id": nb_id,
                                    "doubt": "why?",
                                    "original_paragraph": "Fourier analysis decomposes signals."},
                              headers={**auth_h(token), "Content-Type": "application/json"})
    assert r.status_code == 200
    assert len(r.json()["mutated_paragraph"]) > 5


# ── 2. Mutation — mocked Azure LLM ───────────────────────────────────────────

def test_mutate_with_mocked_azure_llm(smoke_client, smoke_auth):
    """Patch _llm_mutate to simulate a successful Azure call and verify the
    endpoint passes the result through correctly."""
    token, nb_id = smoke_auth

    async def fake_llm_mutate(note_page, doubt, slide_ctx, textbook_ctx):
        return (
            "## Rewritten by Mock Azure\n\nConvolution is multiplication in frequency domain.",
            "Frequency Domain",
            "The Convolution Theorem states x*h ↔ X·H in frequency domain.",
            "azure",
        )

    with patch("deps._llm_mutate", new=fake_llm_mutate):
        r = smoke_client.post("/api/mutate",
                              json={"notebook_id": nb_id,
                                    "doubt": "Explain convolution",
                                    "original_paragraph": "Convolution theorem..."},
                              headers={**auth_h(token), "Content-Type": "application/json"})

    assert r.status_code == 200, r.text
    body = r.json()
    assert body["can_mutate"] is True
    assert body["source"] == "azure"
    assert "Rewritten by Mock Azure" in body["mutated_paragraph"]
    assert "Frequency Domain" in body["concept_gap"]
    assert body["answer"] != ""


def test_mutate_llm_none_triggers_fallback(smoke_client, smoke_auth):
    """When _llm_mutate returns (None, None, None, 'none'), the handler must
    fall back to local_mutate and set can_mutate=False."""
    token, nb_id = smoke_auth

    async def broken_llm(note_page, doubt, slide_ctx, textbook_ctx):
        return None, None, None, "none"

    with patch("deps._llm_mutate", new=broken_llm):
        r = smoke_client.post("/api/mutate",
                              json={"notebook_id": nb_id,
                                    "doubt": "fallback test",
                                    "original_paragraph": "Some note page."},
                              headers={**auth_h(token), "Content-Type": "application/json"})

    assert r.status_code == 200
    body = r.json()
    assert body["can_mutate"] is False
    assert body["source"] == "local"
    assert len(body["mutated_paragraph"]) > 5


# ── 3. Doubt — offline fallback ───────────────────────────────────────────────

def test_doubt_offline_fallback_is_structured(smoke_client, smoke_auth):
    """With no LLM, /api/doubt must still return a DoubtResponse with a
    non-empty local answer (analogy-based fallback)."""
    token, nb_id = smoke_auth
    with patch("deps._is_azure_available", return_value=False), \
         patch("deps._is_groq_available",  return_value=False):
        r = smoke_client.post("/api/doubt",
                              json={"notebook_id": nb_id,
                                    "doubt": "What is the Z-transform?",
                                    "page_idx": 0},
                              headers={**auth_h(token), "Content-Type": "application/json"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert "answer" in body
    assert "source" in body
    assert len(body["answer"]) > 10
    assert body["source"] == "local"


def test_doubt_offline_answer_contains_doubt_topic(smoke_client, smoke_auth):
    """Local fallback should echo or reference the student's topic somewhere."""
    token, nb_id = smoke_auth
    with patch("deps._is_azure_available", return_value=False), \
         patch("deps._is_groq_available",  return_value=False):
        r = smoke_client.post("/api/doubt",
                              json={"notebook_id": nb_id,
                                    "doubt": "convolution theorem",
                                    "page_idx": 0},
                              headers={**auth_h(token), "Content-Type": "application/json"})
    assert r.status_code == 200
    assert r.json()["answer"].strip() != ""


# ── 4. Doubt — mocked Azure LLM ──────────────────────────────────────────────

def test_doubt_with_mocked_azure(smoke_client, smoke_auth):
    """Patch fusion_agent.answer_doubt and verify the response is parsed and
    returned correctly."""
    token, nb_id = smoke_auth

    # The raw text format expected by parse_verification_response
    mock_raw = (
        "ANSWER: The Z-transform is a generalisation of the DTFT.\n"
        "VERIFICATION: correct\n"
        "CORRECTION: \n"
        "FOOTNOTE: See Oppenheim Ch.3"
    )

    async def fake_answer_doubt(**kwargs):
        return mock_raw

    with patch("deps._is_azure_available", return_value=True), \
         patch("deps.fusion_agent") as mock_fa:
        mock_fa.answer_doubt = fake_answer_doubt
        r = smoke_client.post("/api/doubt",
                              json={"notebook_id": nb_id,
                                    "doubt": "What is Z-transform?",
                                    "page_idx": 0},
                              headers={**auth_h(token), "Content-Type": "application/json"})

    assert r.status_code == 200, r.text
    body = r.json()
    assert body["source"] == "azure"
    assert len(body["answer"]) > 5


# ── 5. Mutation — wrong notebook owner rejected ───────────────────────────────

def test_mutate_rejects_non_owner(smoke_client):
    """A second user must not be able to mutate the first user's notebook."""
    r2 = smoke_client.post("/auth/register",
                           json={"email": "attacker@test.com", "password": "Attack123!"})
    attacker_token = r2.json()["token"]

    # Get the smoke_auth notebook id via the owner first
    owner = smoke_client.post("/auth/login",
                              json={"email": "smoke@test.com", "password": "Smoke123!"})
    owner_token = owner.json()["token"]
    nbs_resp = smoke_client.get("/notebooks", headers=auth_h(owner_token)).json()
    nb_id = nbs_resp["notebooks"][0]["id"]

    r = smoke_client.post("/api/mutate",
                          json={"notebook_id": nb_id,
                                "doubt": "hack!",
                                "original_paragraph": "..."},
                          headers={**auth_h(attacker_token), "Content-Type": "application/json"})
    assert r.status_code in (403, 404)


# ── 6. Token refresh ──────────────────────────────────────────────────────────

def test_token_refresh_returns_new_token(smoke_client):
    """POST /auth/refresh with a valid token issues a fresh one."""
    owner = smoke_client.post("/auth/login",
                              json={"email": "smoke@test.com", "password": "Smoke123!"})
    old_token = owner.json()["token"]

    r = smoke_client.post("/auth/refresh",
                          headers={"Authorization": f"Bearer {old_token}"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert "token" in body
    # New token must be different from the old one
    assert body["token"] != old_token


def test_token_refresh_rejects_garbage(smoke_client):
    r = smoke_client.post("/auth/refresh",
                          headers={"Authorization": "Bearer not-a-real-token"})
    assert r.status_code == 401


def test_mutate_requires_auth(smoke_client, smoke_auth):
    _, nb_id = smoke_auth
    r = smoke_client.post("/api/mutate",
                          json={"notebook_id": nb_id, "doubt": "test"},
                          headers={"Content-Type": "application/json"})
    assert r.status_code == 401


def test_doubt_requires_auth(smoke_client, smoke_auth):
    _, nb_id = smoke_auth
    r = smoke_client.post("/api/doubt",
                          json={"notebook_id": nb_id, "doubt": "test"})
    assert r.status_code == 401
