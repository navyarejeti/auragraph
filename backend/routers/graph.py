"""routers/graph.py — /api/graph* and legacy /api/extract-concepts."""
from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, Header, HTTPException

from deps import get_current_user, _require_notebook_owner
from schemas import NodeUpdateRequest, ConceptExtractRequest

logger = logging.getLogger("auragraph")
router = APIRouter(tags=["graph"])


@router.get("/api/graph")
async def get_graph(authorization: Optional[str] = Header(None)):
    """Returns the calling user's global concept graph (mastery store)."""
    from agents.mastery_store import get_db
    user = get_current_user(authorization)
    return get_db(user["id"])


@router.post("/api/graph/update")
async def update_graph(
    req: NodeUpdateRequest,
    authorization: Optional[str] = Header(None),
):
    from agents.mastery_store import update_node_status
    user    = get_current_user(authorization)
    updated = update_node_status(req.concept_name, req.status, user["id"])
    if not updated:
        raise HTTPException(404, "Node not found")
    return {"status": "success", "node": updated}


@router.post("/api/extract-concepts")
async def extract_concepts_endpoint(
    req: ConceptExtractRequest,
    authorization: Optional[str] = Header(None),
):
    from agents.concept_extractor import llm_extract_concepts
    from agents.notebook_store import update_notebook_graph
    user  = get_current_user(authorization)
    graph = await llm_extract_concepts(req.note)
    if req.notebook_id:
        try:
            _require_notebook_owner(req.notebook_id, user)
            update_notebook_graph(req.notebook_id, graph)
        except HTTPException:
            pass   # not owner — return graph but don't save
    return graph
