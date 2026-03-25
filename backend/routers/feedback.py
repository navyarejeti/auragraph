"""routers/feedback.py — Student feedback collection + admin read."""
from __future__ import annotations

import logging
import os
from typing import Optional

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel, Field

from deps import get_current_user

logger = logging.getLogger("auragraph")
router = APIRouter(tags=["feedback"])


class FeedbackRequest(BaseModel):
    context:     str = "dashboard"        # 'dashboard' | 'notebook'
    notebook_id: Optional[str] = None
    rating:      Optional[int] = Field(default=None, ge=1, le=5)
    liked:       str = ""
    disliked:    str = ""
    category:    str = "general"          # 'notes' | 'questions' | 'mutation' | 'ui' | 'general'
    message:     str = Field(default="", max_length=2000)
    page_url:    str = ""


async def _send_webhook(entry: dict):
    """Fire-and-forget Discord/Slack webhook so feedback reaches developers instantly."""
    url = os.environ.get("FEEDBACK_WEBHOOK_URL", "")
    if not url:
        return
    try:
        import httpx
        stars = "⭐" * (entry.get("rating") or 0)
        text = (
            f"**New AuraGraph Feedback** {stars}\n"
            f"• Context: `{entry.get('context','?')}` | "
            f"Category: `{entry.get('category','?')}`\n"
            f"• User: `{entry.get('user_email') or entry.get('user_id','anonymous')}`\n"
        )
        if entry.get("liked"):
            text += f"• 👍 Liked: {entry['liked']}\n"
        if entry.get("disliked"):
            text += f"• 👎 Disliked: {entry['disliked']}\n"
        if entry.get("message"):
            text += f"• Message: {entry['message']}\n"
        # Discord payload
        payload = {"content": text[:1900]}
        async with httpx.AsyncClient(timeout=8.0) as client:
            await client.post(url, json=payload)
    except Exception as exc:
        logger.warning("feedback webhook failed: %s", exc)


@router.post("/api/feedback")
async def submit_feedback(
    req: FeedbackRequest,
    authorization: Optional[str] = Header(None),
):
    """Submit feedback — available to all authenticated users."""
    from agents.notebook_store import save_feedback
    try:
        user = get_current_user(authorization)
    except HTTPException:
        user = {"id": "anonymous", "email": ""}

    entry = req.model_dump()
    entry["user_id"]    = user.get("id", "anonymous")
    entry["user_email"] = user.get("email", "")

    fid = save_feedback(entry)

    # Async webhook — don't await so response is instant
    import asyncio
    asyncio.ensure_future(_send_webhook(entry))

    return {"ok": True, "id": fid}


@router.get("/api/feedback")
async def get_feedback(
    authorization: Optional[str] = Header(None),
    limit: int = 200,
):
    """Admin endpoint — protected by ADMIN_KEY env var."""
    admin_key = os.environ.get("ADMIN_KEY", "")
    # Accept admin_key passed as Bearer token OR as query param
    token = ""
    if authorization:
        token = authorization.replace("Bearer ", "").strip()
    if admin_key and token != admin_key:
        raise HTTPException(403, "Admin access required.")
    if not admin_key:
        raise HTTPException(503, "ADMIN_KEY not configured on server.")
    from agents.notebook_store import get_all_feedback
    rows = get_all_feedback(limit=limit)
    return {"feedback": rows, "total": len(rows)}
