"""
Local Concept Extractor — AuraGraph
Extracts graph nodes/edges directly from note pages.

Policy: one concept node per rendered note page, labelled by that page heading.
"""
import json
import logging
import re
from typing import Any


logger = logging.getLogger(__name__)


def _normalize_id(label: str) -> str:
    """Convert a topic label to a lowercase underscore-separated id."""
    return re.sub(r'[^a-z0-9]+', '_', label.lower()).strip('_')


def _split_note_pages(note_text: str) -> list[str]:
    """Mirror frontend pagination enough for graph cardinality.

    Priority:
      1) Split by H2 headings (##) — each section is one page.
      2) Else split by H3 headings (###) when multiple sections exist.
      3) Else keep the full note as one page.
    """
    if not note_text or not note_text.strip():
        return []

    clean = re.sub(
        r'^\s*```+\s*(?:markdown|md|latex|text)?\s*\n',
        '',
        note_text,
        flags=re.MULTILINE,
    )
    clean = re.sub(r'\n\s*```+\s*$', '', clean)

    by_h2 = [s.strip() for s in re.split(r'(?=^##\s+)', clean, flags=re.MULTILINE) if s.strip()]
    if by_h2:
        return by_h2

    by_h3 = [s.strip() for s in re.split(r'(?=^###\s+)', clean, flags=re.MULTILINE) if s.strip()]
    if len(by_h3) > 1:
        return by_h3

    return [clean.strip()] if clean.strip() else []


def _page_heading(page_text: str, page_num: int) -> str:
    """Return the first markdown heading in a page, else a fallback label."""
    m = re.search(r'^(#{1,6})\s+(.+?)\s*$', page_text, flags=re.MULTILINE)
    if not m:
        return f"Page {page_num}"
    heading = m.group(2).strip().rstrip('.:;,')
    return heading if heading else f"Page {page_num}"


def extract_topics_from_contents(note_text: str) -> dict[str, Any]:
    """
    Deterministic page-based extraction:
    - Exactly one node per note page
    - Node label = page heading
    - Edges are inferred separately (AI path in llm_extract_concepts)
    """
    pages = _split_note_pages(note_text)
    if not pages:
        return {
            'nodes': [{'id': 1, 'label': 'Lecture Topics', 'full_label': 'Lecture Topics',
                        'status': 'partial', 'x': 50, 'y': 50, 'mutation_count': 0}],
            'edges': [],
        }

    topics = [_page_heading(page, i + 1) for i, page in enumerate(pages)]

    # ── Build nodes with grid distribution ──────────────────────────────
    total = len(topics)
    nodes: list[dict] = []
    # Arrange in rows of 3 to avoid a flat line
    cols = 3
    for i, label in enumerate(topics):
        col = i % cols
        row = i // cols
        num_rows = (total + cols - 1) // cols
        x = round(15 + (col / max(cols - 1, 1)) * 70)   # 15–85%
        y = round(15 + (row / max(num_rows - 1, 1)) * 70) if num_rows > 1 else 50  # 15–85%
        nodes.append({
            'id': i + 1,
            'label': label if len(label) <= 32 else label[:30].rsplit(' ', 1)[0] + '…',
            'full_label': label,
            'status': 'partial',
            'x': x,
            'y': y,
            'mutation_count': 0,
        })

    return {'nodes': nodes, 'edges': []}


def _page_summary(page_text: str, max_len: int = 240) -> str:
    """Short content summary for edge inference prompts."""
    body = re.sub(r'^(#{1,6})\s+.+$', '', page_text, flags=re.MULTILINE)
    body = re.sub(r'\s+', ' ', body).strip()
    if len(body) <= max_len:
        return body
    clipped = body[:max_len]
    cut = clipped.rfind(' ')
    return clipped[:cut].rstrip() + '...' if cut > 80 else clipped.rstrip() + '...'


def _strip_fences(raw: str) -> str:
    txt = (raw or '').strip()
    txt = re.sub(r'^```[a-zA-Z]*\n?', '', txt)
    txt = re.sub(r'\n?```$', '', txt)
    return txt.strip()


async def _infer_ai_edges(pages: list[str], nodes: list[dict]) -> list[list[int]]:
    """Infer concept dependencies using AI over page headings + summaries.

    Returns directed edges using numeric frontend node ids.
    If AI is unavailable or response is invalid, returns [] (no fallback chain).
    """
    if len(nodes) <= 1:
        return []

    page_items = []
    valid_ids = set()
    id_to_num = {}
    for idx, (page, node) in enumerate(zip(pages, nodes), start=1):
        pid = f"page_{idx}"
        valid_ids.add(pid)
        id_to_num[pid] = int(node['id'])
        page_items.append({
            'id': pid,
            'heading': node.get('full_label') or node.get('label') or pid,
            'summary': _page_summary(page),
        })

    system = (
        "You infer directed academic prerequisite edges between note pages. "
        "Return ONLY JSON: {\"edges\":[{\"source\":\"page_i\",\"target\":\"page_j\",\"confidence\":0.0-1.0}]}. "
        "Use only given page ids. No self-loops. Prefer meaningful dependencies over chronology."
    )
    user = (
        "Pages (one concept per page):\n"
        + "\n".join(
            f"- {p['id']}: heading={p['heading']} | summary={p['summary']}"
            for p in page_items
        )
        + "\n\nFind real conceptual links (prerequisite, depends-on, used-in)."
    )

    raw = None
    try:
        from agents.graph_builder import _call_azure_json, _call_groq_json
        raw = await _call_azure_json(system, user)
        if raw is None:
            raw = await _call_groq_json(system, user)
    except Exception:
        logger.warning("AI edge inference unavailable", exc_info=True)
        return []

    if not raw:
        return []

    try:
        parsed = json.loads(_strip_fences(raw))
        edges_raw = parsed.get('edges', []) if isinstance(parsed, dict) else []
    except Exception:
        logger.warning("AI edge inference parse failed", exc_info=True)
        return []

    out = []
    seen = set()
    for e in edges_raw:
        if not isinstance(e, dict):
            continue
        src = str(e.get('source', '')).strip().lower()
        tgt = str(e.get('target', '')).strip().lower()
        if src not in valid_ids or tgt not in valid_ids or src == tgt:
            continue
        pair = (id_to_num[src], id_to_num[tgt])
        if pair in seen:
            continue
        seen.add(pair)
        out.append([pair[0], pair[1]])

    return out


# Keep the public name for any direct callers
extract_concepts = extract_topics_from_contents


async def llm_extract_concepts(note_text: str) -> dict:
    """
    Build a notebook graph from generated notes.

    Policy:
    - Nodes: deterministic one-per-page using page heading.
    - Edges: AI-inferred conceptual relationships only.
    """
    graph = extract_topics_from_contents(note_text)
    pages = _split_note_pages(note_text)
    graph['edges'] = await _infer_ai_edges(pages, graph.get('nodes', []))
    return graph
