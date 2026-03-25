"""routers/auth.py — /auth/* endpoints."""
from __future__ import annotations

import asyncio
import logging
from typing import Optional

from fastapi import APIRouter, Header, HTTPException

from schemas import AuthRequest
from deps import get_current_user

logger = logging.getLogger("auragraph")
router = APIRouter(tags=["auth"])

# ── Demo sample note (only used for demo-login seed) ──────────────────────────
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

---

## Discrete Fourier Transform (DFT)

For $N$-point discrete sequences, the DFT is:

$$X[k] = \\sum_{n=0}^{N-1} x[n]\\, e^{-j \\frac{2\\pi}{N} k n}, \\quad k = 0, 1, \\ldots, N-1$$

The **Fast Fourier Transform (FFT)** computes the DFT in $O(N \\log N)$ using twiddle-factor symmetry.

---

## Sampling Theorem (Nyquist–Shannon)

A band-limited signal with maximum frequency $f_{\\max}$ can be **perfectly reconstructed** if:

$$f_s \\geq 2 f_{\\max}$$

---

## Z-Transform

$$X(z) = \\sum_{n=-\\infty}^{\\infty} x[n]\\, z^{-n}$$

**Stability criterion:** All poles of $H(z)$ must lie **strictly inside** the unit circle $|z| < 1$.
"""


@router.post("/auth/register")
async def auth_register(req: AuthRequest):
    from agents.auth_utils import register_user
    if not req.identifier:
        raise HTTPException(422, "email or username is required")
    user = register_user(req.identifier, req.password, req.name)
    if not user:
        raise HTTPException(409, "Account already exists")
    return user


@router.post("/auth/login")
async def auth_login(req: AuthRequest):
    from agents.auth_utils import login_user
    if not req.identifier:
        raise HTTPException(422, "email or username is required")
    user = login_user(req.identifier, req.password)
    if not user:
        raise HTTPException(401, "Invalid credentials")
    return user


@router.post("/auth/refresh")
async def auth_refresh(authorization: Optional[str] = Header(None)):
    """Silently renew a valid token before it expires."""
    from agents.auth_utils import refresh_token
    token = (authorization or "").removeprefix("Bearer ").strip()
    if not token:
        raise HTTPException(401, "No token provided")
    user = refresh_token(token)
    if not user:
        raise HTTPException(401, "Token expired or invalid — please log in again")
    return user


@router.post("/auth/demo-login")
async def auth_demo_login():
    """One-click demo: returns a fixed demo-token and seeds a sample DSP notebook.
    Only works when DEMO_ENABLED=true is set in the environment.
    """
    import os
    if os.environ.get("DEMO_ENABLED", "false").lower() != "true":
        raise HTTPException(403, "Demo mode is disabled on this server.")

    from agents.notebook_store import get_notebooks, create_notebook, get_notebook, update_notebook_note
    from agents.concept_extractor import llm_extract_concepts
    from agents.notebook_store import update_notebook_graph

    demo_user_id = "demo"
    demo_nbs = get_notebooks(demo_user_id)
    demo_nb  = next((nb for nb in demo_nbs if nb.get("name") == "Digital Signal Processing"), None)

    if demo_nb is None:
        demo_nb = create_notebook(demo_user_id, "Digital Signal Processing", "EC301 — DSP")
        update_notebook_note(demo_nb["id"], _DEMO_SAMPLE_NOTE, "Practitioner")
        demo_nb = get_notebook(demo_nb["id"])

        async def _seed_graph():
            try:
                g = await llm_extract_concepts(_DEMO_SAMPLE_NOTE)
                if g.get("nodes"):
                    update_notebook_graph(demo_nb["id"], g)
            except Exception as exc:
                logger.debug("Demo graph seed failed: %s", exc)

        asyncio.create_task(_seed_graph())

    return {
        "id":               demo_user_id,
        "email":            "demo@auragraph.local",
        "name":             "Demo Student",
        "token":            "demo-token",
        "demo_notebook_id": demo_nb["id"],
    }
