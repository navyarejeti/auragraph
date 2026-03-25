"""routers/notebooks.py — /notebooks/* CRUD."""
from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, Header, HTTPException, Query

import deps
from deps import get_current_user, _require_notebook_owner, _is_azure_available, _is_groq_available, _azure_chat, _groq_chat, _check_llm_rate_limit, _record_llm_call
from schemas import (
    NotebookCreateRequest, NotebookUpdateRequest,
    NodeUpdateRequest,
)

logger = logging.getLogger("auragraph")
router = APIRouter(tags=["notebooks"])


@router.post("/notebooks")
async def new_notebook(req: NotebookCreateRequest, authorization: Optional[str] = Header(None)):
    from agents.notebook_store import create_notebook
    user = get_current_user(authorization)
    return create_notebook(user["id"], req.name, req.course)


@router.get("/notebooks")
async def list_notebooks(
    authorization: Optional[str] = Header(None),
    limit: int = Query(default=50, ge=1, le=200, description="Max notebooks to return"),
    offset: int = Query(default=0, ge=0, description="Pagination offset"),
):
    """
    Returns the caller's notebooks, newest first.
    Use `limit` and `offset` for pagination — e.g. `?limit=20&offset=40`.
    """
    from agents.notebook_store import get_notebooks
    user = get_current_user(authorization)
    all_nbs = get_notebooks(user["id"])
    # get_notebooks returns list; slice for pagination
    total   = len(all_nbs)
    page    = all_nbs[offset: offset + limit]
    return {"total": total, "offset": offset, "limit": limit, "notebooks": page}


@router.get("/notebooks/{nb_id}")
async def fetch_notebook(nb_id: str, authorization: Optional[str] = Header(None)):
    user = get_current_user(authorization)
    return _require_notebook_owner(nb_id, user)


@router.patch("/notebooks/{nb_id}/note")
async def save_notebook_note(
    nb_id: str, req: NotebookUpdateRequest,
    authorization: Optional[str] = Header(None),
):
    from agents.notebook_store import update_notebook_note
    user = get_current_user(authorization)
    _require_notebook_owner(nb_id, user)
    async with deps._db_write_lock:
        return update_notebook_note(nb_id, req.note, req.proficiency)


@router.delete("/notebooks/{nb_id}")
async def remove_notebook(nb_id: str, authorization: Optional[str] = Header(None)):
    from agents.notebook_store import delete_notebook
    from agents.knowledge_store import delete_notebook_store
    user = get_current_user(authorization)
    _require_notebook_owner(nb_id, user)
    delete_notebook(nb_id)
    delete_notebook_store(nb_id)
    try:
        from pipeline.vector_db import VectorDB
        VectorDB.delete(nb_id)
    except Exception:
        pass
    return {"status": "deleted"}


@router.get("/notebooks/{nb_id}/knowledge-stats")
async def get_knowledge_stats(nb_id: str, authorization: Optional[str] = Header(None)):
    from agents.knowledge_store import get_chunk_stats
    user = get_current_user(authorization)
    _require_notebook_owner(nb_id, user)
    return get_chunk_stats(nb_id)


# ── Notebook-scoped graph ──────────────────────────────────────────────────────

@router.get("/notebooks/{nb_id}/graph")
async def get_notebook_graph(nb_id: str, authorization: Optional[str] = Header(None)):
    user = get_current_user(authorization)
    nb   = _require_notebook_owner(nb_id, user)
    return nb.get("graph", {"nodes": [], "edges": []})


@router.post("/notebooks/{nb_id}/graph/update")
async def update_notebook_graph_node(
    nb_id: str,
    req: NodeUpdateRequest,
    authorization: Optional[str] = Header(None),
):
    from agents.notebook_store import update_notebook_graph
    user  = get_current_user(authorization)
    nb    = _require_notebook_owner(nb_id, user)
    graph = nb.get("graph", {"nodes": [], "edges": []})
    for node in graph["nodes"]:
        if node["label"].lower() == req.concept_name.lower():
            node["status"] = req.status
            update_notebook_graph(nb_id, graph)
            return {"status": "success", "node": node}
    raise HTTPException(404, "Concept node not found")


# ── Doubts sync endpoints ──────────────────────────────────────────────────────

from typing import List as _List
from pydantic import BaseModel as _BaseModel, field_validator as _fv

class _DoubtEntry(_BaseModel):
    model_config = {"extra": "ignore"}   # silently drop unknown frontend fields
    id:         str
    pageIdx:    int = 0
    doubt:      str
    insight:    str = ""
    gap:        str = ""
    source:     str = "local"
    success:    bool = False
    time:       str = ""
    kind:       Optional[str] = None    # 'mutated' | 'doubt' | None
    unresolved: Optional[bool] = None  # True while offline

    @_fv('id', mode='before')
    @classmethod
    def _coerce_id(cls, v):
        """Accept numeric ids (Date.now() from JS) and coerce to str."""
        return str(v) if v is not None else ""


@router.get("/api/notebooks/{nb_id}/doubts")
async def get_doubts_endpoint(
    nb_id: str,
    authorization: Optional[str] = Header(None),
):
    from agents.notebook_store import get_doubts
    user = get_current_user(authorization)
    _require_notebook_owner(nb_id, user)
    return {"doubts": get_doubts(nb_id)}


@router.post("/api/notebooks/{nb_id}/doubts")
async def save_doubt_endpoint(
    nb_id: str,
    entry: _DoubtEntry,
    authorization: Optional[str] = Header(None),
):
    from agents.notebook_store import save_doubt
    user = get_current_user(authorization)
    _require_notebook_owner(nb_id, user)
    ok = save_doubt(nb_id, entry.model_dump())
    return {"ok": ok}


@router.delete("/api/notebooks/{nb_id}/doubts/{doubt_id}")
async def delete_doubt_endpoint(
    nb_id: str,
    doubt_id: str,
    authorization: Optional[str] = Header(None),
):
    from agents.notebook_store import delete_doubt
    user = get_current_user(authorization)
    _require_notebook_owner(nb_id, user)
    ok = delete_doubt(nb_id, doubt_id)
    return {"ok": ok}


# ── Annotations endpoints ──────────────────────────────────────────────────────

from pydantic import BaseModel as _BM

class _AnnotationEntry(_BM):
    model_config = {"extra": "ignore"}
    id:         str
    page_idx:   int = 0
    type:       str           # 'highlight' | 'sticky' | 'drawing'
    data:       dict = {}
    created_at: str = ""


@router.get("/api/notebooks/{nb_id}/annotations")
async def get_annotations_endpoint(
    nb_id: str,
    authorization: Optional[str] = Header(None),
):
    from agents.notebook_store import get_annotations
    user = get_current_user(authorization)
    _require_notebook_owner(nb_id, user)
    return {"annotations": get_annotations(nb_id)}


@router.post("/api/notebooks/{nb_id}/annotations")
async def save_annotation_endpoint(
    nb_id: str,
    entry: _AnnotationEntry,
    authorization: Optional[str] = Header(None),
):
    from agents.notebook_store import save_annotation
    user = get_current_user(authorization)
    _require_notebook_owner(nb_id, user)
    ok = save_annotation(nb_id, entry.model_dump())
    return {"ok": ok}


@router.delete("/api/notebooks/{nb_id}/annotations/{ann_id}")
async def delete_annotation_endpoint(
    nb_id: str,
    ann_id: str,
    authorization: Optional[str] = Header(None),
):
    from agents.notebook_store import delete_annotation
    user = get_current_user(authorization)
    _require_notebook_owner(nb_id, user)
    ok = delete_annotation(nb_id, ann_id)
    return {"ok": ok}


@router.delete("/api/notebooks/{nb_id}/annotations")
async def delete_all_annotations_endpoint(
    nb_id: str,
    authorization: Optional[str] = Header(None),
):
    from agents.notebook_store import delete_all_annotations
    user = get_current_user(authorization)
    _require_notebook_owner(nb_id, user)
    ok = delete_all_annotations(nb_id)
    return {"ok": ok}
