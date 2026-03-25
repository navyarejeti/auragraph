"""Quick end-to-end test for note generation."""
import json
import sys
import requests

BASE = "http://localhost:8000"
TIMEOUT = 150  # seconds — LLM calls can take a while

# ── Auth ──────────────────────────────────────────────────────────────────────
r = requests.post(f"{BASE}/auth/register", json={"email": "gentest3@t.com", "password": "password123"})
if r.status_code not in (200, 409):
    print("register failed:", r.status_code, r.text); sys.exit(1)
token = r.json().get("token") or ""
if not token:
    r = requests.post(f"{BASE}/auth/login", json={"email": "gentest3@t.com", "password": "password123"})
    token = r.json().get("token", "")
print(f"auth OK – token: {token[:20]}…")

HEADERS = {"Authorization": f"Bearer {token}"}

# ── [0] Direct local summarizer test (always works, no LLM) ──────────────────
print("\n[0] Testing local fallback summarizer directly…")
import sys, os
sys.path.insert(0, os.path.dirname(__file__))
from agents.local_summarizer import generate_local_note
local_note = generate_local_note(
    "Slide 1: Fourier Transform maps time domain to frequency domain. F(w)=integral x(t)e^{-jwt}dt.",
    "The Fourier Transform converts a time-domain signal into its frequency components.",
    "Beginner"
)
print(f"  local note length: {len(local_note)} chars")
print(f"  preview: {local_note[:200]}")
assert len(local_note) > 50, "local_note too short!"
print("  ✅ local summarizer OK")
r = requests.post(
    f"{BASE}/api/fuse",
    headers={**HEADERS, "Content-Type": "application/json"},
    json={
        "slide_summary": (
            "Slide 1: Convolution definition y(t) = x(t)*h(t).\n"
            "Slide 2: Fourier Transform H(jw) = integral h(t)e^{-jwt}dt.\n"
            "Slide 3: Convolution in time = multiplication in frequency domain."
        ),
        "textbook_paragraph": (
            "Convolution is a mathematical operation used to express the "
            "relationship between input, output and impulse response of an LTI system. "
            "The convolution integral: y(t) = integral x(tau)*h(t-tau) dtau."
        ),
        "proficiency": "Intermediate",
        "notebook_id": "",
    },
    timeout=120,
)
print(f"  status: {r.status_code}")
if r.status_code == 200:
    d = r.json()
    note = d.get("fused_note", "")
    print(f"  source : {d.get('source','?')}")
    print(f"  length : {len(note)} chars")
    print(f"  preview: {note[:300]}")
else:
    try:
        err = r.json()
    except Exception:
        err = r.text
    print(f"  ERROR  : {json.dumps(err, indent=2)[:600]}")

# ── /api/upload-fuse-stream (SSE endpoint, minimal synthetic PDF bytes) ───────
print("\n[2] Testing /api/upload-fuse-stream SSE endpoint…")
# Create a minimal valid-looking PDF text file (will trigger text extraction fallback)
fake_pdf = b"%PDF-1.4 1 0 obj<</Type/Catalog>>endobj xref 0 2 trailer<</Size 2>>%%EOF"
form_data = {
    "proficiency": (None, "Beginner"),
    "notebook_id": (None, ""),
}
files = {
    "slides_pdfs": ("test_slides.pdf", fake_pdf, "application/pdf"),
}
r2 = requests.post(
    f"{BASE}/api/upload-fuse-stream",
    headers=HEADERS,
    data={"proficiency": "Beginner", "notebook_id": ""},
    files=files,
    stream=True,
    timeout=120,
)
print(f"  status: {r2.status_code}")
if r2.status_code == 200:
    events = []
    for raw_line in r2.iter_lines():
        line = raw_line.decode() if isinstance(raw_line, bytes) else raw_line
        if line.startswith("data: "):
            try:
                ev = json.loads(line[6:])
                events.append(ev)
                print(f"  SSE event [{ev.get('type','?')}]: {str(ev)[:120]}")
                if ev.get("type") == "done":
                    break
            except Exception:
                pass
    print(f"  Total SSE events: {len(events)}")
else:
    try:
        err = r2.json()
    except Exception:
        err = r2.text[:400]
    print(f"  ERROR: {json.dumps(err) if isinstance(err, dict) else err}")
