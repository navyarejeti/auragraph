"""
agents/graph_builder.py — LLM-powered knowledge graph construction.

Takes generated notes and produces a concept relationship graph
using an LLM (Azure OpenAI → Groq fallback → deterministic fallback).

Pipeline:
  Generated Notes → extract_concepts_from_notes()
                  → build_graph_with_llm()  (chunked if large)
                  → merge_graphs()          (combine chunk results)
                  → { "nodes": [...], "edges": [...] }
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import re
from typing import Any, Optional

logger = logging.getLogger("auragraph.graph_builder")

# ── Constants ────────────────────────────────────────────────────────────────

# Max concepts per LLM chunk to stay well within token limits
_CHUNK_SIZE = 15

_VALID_RELATIONS = {
    "part_of", "type_of", "depends_on",
    "causes", "leads_to", "used_in", "related_to",
}

_GRAPH_SYSTEM_PROMPT = """\
You are a knowledge-graph builder for an academic study platform.

Given a list of concepts with short explanations extracted from lecture notes,
produce a clean knowledge graph with properly named concept nodes.

Return ONLY a valid JSON object — no markdown fences, no prose, no explanation.

Required schema:
{
  "nodes": [
    {"id": "concept_name_snake_case", "label": "Concept Name"}
  ],
  "edges": [
    {"source": "concept_a", "target": "concept_b", "relation": "relation_type"}
  ]
}

CONCEPT LABEL RULES (most important — read carefully):
Every node label must be a clean, meaningful academic concept name — the kind a
student would write on a flashcard or see in a textbook index.

You MUST rename raw headings into proper concept names:
  • Strip structural prefixes entirely: "Theorem 3.", "Lemma 2.", "Corollary of",
    "Definition:", "Case:", "Section", "Part", numbered prefixes like "3.1", "2.4.1".
  • Expand vague case labels: "Discrete case" → "Discrete Probability Distribution",
    "Continuous case" → "Continuous Probability Distribution",
    "General case" → use the parent concept name with "General Form".
  • Expand abbreviations: "cont rv" → "Continuous Random Variable",
    "disc rv" → "Discrete Random Variable", "pdf" → "Probability Density Function",
    "cdf" → "Cumulative Distribution Function", "pgf" → "Probability Generating Function",
    "mgf" → "Moment Generating Function", "iid" → "Independent and Identically Distributed".
  • Remove filler at the start: "Introduction to", "Overview of", "Notes on", "Basics of".
  • Use proper title case: "fourier transform" → "Fourier Transform".
  • Name WHAT a theorem is about, not its number:
    "Theorem 3" → use the body summary to determine: e.g. "Central Limit Theorem",
    "Bayes Theorem", "Law of Total Probability" — whatever the summary describes.
  • Corollaries: "Corollary of Theorem 3" → name the corollary's actual content,
    e.g. "Corollary: Variance of Sample Mean".
  • Ideal length: 2–5 words. Never more than 6 words.
  • Every label must represent a concept a student can study, practice, and be tested on.

EDGE DIRECTION RULES:
- source = the foundational/prerequisite concept (learned FIRST).
- target = the dependent/advanced concept (learned AFTER the source).
- Edges flow from EARLIER/simpler to LATER/more advanced topics.

Other rules:
- Node "id" must be lowercase with underscores (no spaces).
- Every input concept MUST appear as a node in the output (with a cleaned label).
- Edge "source" and "target" must reference valid node ids.
- Edge "relation" must be one of: part_of, type_of, depends_on, causes, leads_to, used_in, related_to.
- Create a RICH graph — most concepts should have 2+ connections.
- Only add edges where a clear academic relationship exists.
- Do NOT invent new concepts not in the input.
- Return valid JSON only.
"""


# ── Step 1: Extract concepts from generated notes ───────────────────────────

def extract_concepts_from_notes(note_text: str) -> list[dict[str, str]]:
    """
    Extract concept titles and short summaries from generated Markdown notes.

    Returns a list of dicts: [{"title": "...", "summary": "..."}, ...]
    The title is pre-cleaned to remove the most obvious structural noise
    (theorem numbers, "case" labels, abbreviations) before reaching the LLM.
    """
    concepts: list[dict[str, str]] = []

    # Split note into sections by ## headings
    sections = re.split(r'^(##\s+.+)$', note_text, flags=re.MULTILINE)

    # sections alternates: [preamble, heading1, body1, heading2, body2, ...]
    i = 1
    while i < len(sections) - 1:
        heading = sections[i].strip().lstrip('#').strip()
        body = sections[i + 1].strip()
        i += 2

        # Skip administrative headings
        if re.search(
            r'^(contents|table\s+of\s+contents|references|proficiency|study\s+notes)',
            heading, re.IGNORECASE,
        ):
            continue

        if not heading or len(heading) < 3:
            continue

        # ── Pre-clean the heading before sending to LLM ─────────────────
        heading = _clean_heading(heading)

        if not heading or len(heading) < 3:
            continue

        # Take first ~200 chars of the body as a summary
        summary = body[:200].strip()
        if len(body) > 200:
            cut = summary.rfind('.')
            if cut > 60:
                summary = summary[:cut + 1]

        concepts.append({"title": heading, "summary": summary})

    return concepts


def _clean_heading(heading: str) -> str:
    """
    Pre-clean a Markdown ## heading before it becomes a knowledge-graph node label.

    Removes structural noise that makes concept names useless to students:
      • Theorem/Lemma/Corollary/Definition numbers: "Theorem 3." → stripped prefix
      • Pure case labels: "Discrete case" → kept as-is for LLM to expand
      • Numbered section prefixes: "3.1 Sampling" → "Sampling"
      • Leading articles and filler: "The Fourier Transform" → "Fourier Transform"
      • Trailing punctuation
    The LLM then does the deeper semantic renaming (expanding abbreviations, etc.)
    """
    h = heading.strip()

    # Remove numbered section prefix like "3.1 " or "1.2.3 "
    h = re.sub(r'^\d+(\.\d+)*\s+', '', h)

    # Strip leading structural labels but keep the rest
    # "Theorem 3. Some title" → "Some title" if title exists, else keep "Theorem 3"
    theorem_match = re.match(
        r'^(Theorem|Lemma|Corollary|Proposition|Definition|Remark|Example|Exercise)'
        r'\s+[\dA-Z]+\.?\s*(.+)$',
        h, re.IGNORECASE,
    )
    if theorem_match:
        remainder = theorem_match.group(2).strip()
        if len(remainder) > 4:  # meaningful remainder → use it
            h = remainder
        # else keep original (the LLM will name it from the summary)

    # Remove leading articles
    h = re.sub(r'^(The|A|An)\s+', '', h, flags=re.IGNORECASE)

    # Remove trailing punctuation
    h = h.rstrip('.:;,')

    return h.strip()


# ── Step 2: Build graph with LLM ────────────────────────────────────────────

def _build_user_prompt(concepts: list[dict[str, str]]) -> str:
    """Format concepts into a prompt for the LLM, preserving lecture order."""
    lines = []
    for i, c in enumerate(concepts, 1):
        lines.append(f"{i}. **{c['title']}**: {c['summary']}")
    return (
        "Concepts from lecture notes (listed in lecture order, earliest first).\n"
        "Remember: you MUST rename any vague headings into proper concept names "
        "(e.g. 'Discrete case' → 'Discrete Probability Distribution', "
        "'Theorem 3' → the actual theorem name from its summary).\n\n"
        + "\n".join(lines)
    )


def _normalize_id(label: str) -> str:
    """Convert a label to a normalized snake_case id."""
    return re.sub(r'[^a-z0-9]+', '_', label.lower()).strip('_')


def _parse_llm_response(raw: str, concepts: list[dict[str, str]]) -> dict[str, Any]:
    """
    Parse the LLM JSON response into a validated graph structure.
    Ensures all input concepts appear as nodes and edges reference valid ids.
    """
    # Strip markdown fences if present
    raw = re.sub(r'^```[a-z]*\n?', '', raw.strip())
    raw = re.sub(r'\n?```$', '', raw.strip())

    graph = json.loads(raw)

    # Validate nodes
    if not isinstance(graph.get("nodes"), list):
        raise ValueError("Missing or invalid 'nodes' array")

    # Build a set of valid node ids from the response
    node_ids = set()
    clean_nodes = []
    for n in graph["nodes"]:
        nid = str(n.get("id", "")).strip()
        label = str(n.get("label", "")).strip()
        if not nid or not label:
            continue
        nid = _normalize_id(nid)
        node_ids.add(nid)
        clean_nodes.append({"id": nid, "label": label})

    # Ensure all input concepts are present
    existing_labels = {n["label"].lower() for n in clean_nodes}
    for c in concepts:
        if c["title"].lower() not in existing_labels:
            nid = _normalize_id(c["title"])
            if nid not in node_ids:
                clean_nodes.append({"id": nid, "label": c["title"]})
                node_ids.add(nid)

    # Validate edges
    clean_edges = []
    if isinstance(graph.get("edges"), list):
        for e in graph["edges"]:
            src = _normalize_id(str(e.get("source", "")))
            tgt = _normalize_id(str(e.get("target", "")))
            rel = str(e.get("relation", "related_to")).strip().lower()
            if src in node_ids and tgt in node_ids and src != tgt:
                if rel not in _VALID_RELATIONS:
                    rel = "related_to"
                clean_edges.append({"source": src, "target": tgt, "relation": rel})

    return {"nodes": clean_nodes, "edges": clean_edges}


async def _call_azure_json(system: str, user: str) -> Optional[str]:
    """Azure OpenAI call that requests JSON output."""
    endpoint = os.environ.get("AZURE_OPENAI_ENDPOINT", "").rstrip("/")
    api_key = os.environ.get("AZURE_OPENAI_API_KEY", "")
    deployment = os.environ.get("AZURE_OPENAI_DEPLOYMENT", "gpt-4o")
    api_ver = os.environ.get("AZURE_OPENAI_API_VERSION", "2024-10-21")

    if not (endpoint and api_key
            and "placeholder" not in endpoint.lower()
            and "placeholder" not in api_key.lower()
            and "mock" not in endpoint.lower()):
        return None

    import httpx
    url = f"{endpoint}/openai/deployments/{deployment}/chat/completions?api-version={api_ver}"
    payload = {
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "max_tokens": 2000,
        "temperature": 0.2,
        "response_format": {"type": "json_object"},
    }
    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.post(
                url,
                headers={"api-key": api_key, "Content-Type": "application/json"},
                json=payload,
            )
            if resp.status_code == 429:
                wait = int(resp.headers.get("Retry-After", "10"))
                logger.warning("graph_builder Azure 429 — retrying in %d s", wait)
                await asyncio.sleep(wait)
                resp = await client.post(
                    url,
                    headers={"api-key": api_key, "Content-Type": "application/json"},
                    json=payload,
                )
            resp.raise_for_status()
            return resp.json()["choices"][0]["message"]["content"].strip()
    except Exception as exc:
        logger.warning("graph_builder Azure call failed: %s", exc)
        return None


async def _call_groq_json(system: str, user: str) -> Optional[str]:
    """Groq fallback call."""
    groq_key = os.environ.get("GROQ_API_KEY", "")
    if not groq_key or groq_key.startswith("your-"):
        return None

    import httpx
    model = os.environ.get("GROQ_MODEL", "llama-3.3-70b-versatile")
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "max_tokens": 2000,
        "temperature": 0.2,
    }
    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.post(
                "https://api.groq.com/openai/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {groq_key}",
                    "Content-Type": "application/json",
                },
                json=payload,
            )
            if resp.status_code == 429:
                wait = int(resp.headers.get("Retry-After", "6"))
                logger.warning("graph_builder Groq 429 — retrying in %d s", wait)
                await asyncio.sleep(wait)
                resp = await client.post(
                    "https://api.groq.com/openai/v1/chat/completions",
                    headers={
                        "Authorization": f"Bearer {groq_key}",
                        "Content-Type": "application/json",
                    },
                    json=payload,
                )
            resp.raise_for_status()
            return resp.json()["choices"][0]["message"]["content"].strip()
    except Exception as exc:
        logger.warning("graph_builder Groq call failed: %s", exc)
        return None


async def build_graph_with_llm(concepts: list[dict[str, str]]) -> dict[str, Any]:
    """
    Send concepts to an LLM and get a knowledge graph of relationships.

    If there are more than _CHUNK_SIZE concepts, chunks them and merges results.
    Falls back to a sequential chain graph if all LLM calls fail.
    """
    if not concepts:
        return {"nodes": [], "edges": []}

    # Chunk if needed
    if len(concepts) <= _CHUNK_SIZE:
        chunks = [concepts]
    else:
        chunks = [
            concepts[i:i + _CHUNK_SIZE]
            for i in range(0, len(concepts), _CHUNK_SIZE)
        ]

    graphs: list[dict[str, Any]] = []
    for chunk in chunks:
        user_prompt = _build_user_prompt(chunk)
        raw = await _call_azure_json(_GRAPH_SYSTEM_PROMPT, user_prompt)
        if raw is None:
            raw = await _call_groq_json(_GRAPH_SYSTEM_PROMPT, user_prompt)

        if raw is not None:
            try:
                g = _parse_llm_response(raw, chunk)
                logger.info(
                    "graph_builder: LLM produced %d nodes, %d edges — sample: %s",
                    len(g["nodes"]), len(g["edges"]),
                    [(e["source"], e["target"], e["relation"]) for e in g["edges"][:8]],
                )
                graphs.append(g)
                continue
            except (json.JSONDecodeError, ValueError, KeyError) as exc:
                logger.warning("graph_builder: LLM response parse failed: %s", exc)

        # Deterministic fallback for this chunk
        logger.info("graph_builder: using deterministic fallback (sequential chain)")
        graphs.append(_deterministic_graph(chunk))

    if len(graphs) == 1:
        return graphs[0]
    return merge_graphs(graphs)


def _deterministic_graph(concepts: list[dict[str, str]]) -> dict[str, Any]:
    """
    Fallback: build a simple sequential chain from the concepts.
    Used when no LLM is available.
    """
    nodes = [
        {"id": _normalize_id(c["title"]), "label": c["title"]}
        for c in concepts
    ]
    edges = []
    for i in range(len(nodes) - 1):
        edges.append({
            "source": nodes[i]["id"],
            "target": nodes[i + 1]["id"],
            "relation": "leads_to",
        })
    return {"nodes": nodes, "edges": edges}


# ── Step 3: Merge multiple chunk graphs ─────────────────────────────────────

def merge_graphs(graphs: list[dict[str, Any]]) -> dict[str, Any]:
    """
    Merge multiple sub-graphs into one unified graph.
    Deduplicates nodes by id; keeps all unique edges.
    Adds cross-chunk bridge edges (last node of chunk N → first node of chunk N+1).
    """
    seen_node_ids: set[str] = set()
    merged_nodes: list[dict] = []
    merged_edges: list[dict] = []
    chunk_boundaries: list[tuple[str, str]] = []  # (last_id of prev, first_id of next)

    for g in graphs:
        first_id = None
        last_id = None
        for n in g.get("nodes", []):
            nid = n["id"]
            if nid not in seen_node_ids:
                seen_node_ids.add(nid)
                merged_nodes.append(n)
            if first_id is None:
                first_id = nid
            last_id = nid

        if first_id and chunk_boundaries:
            prev_last = chunk_boundaries[-1][1]
            if prev_last and prev_last != first_id:
                merged_edges.append({
                    "source": prev_last,
                    "target": first_id,
                    "relation": "leads_to",
                })
        chunk_boundaries.append((first_id, last_id))

        # Deduplicate edges
        edge_set = {(e["source"], e["target"]) for e in merged_edges}
        for e in g.get("edges", []):
            key = (e["source"], e["target"])
            if key not in edge_set:
                edge_set.add(key)
                merged_edges.append(e)

    return {"nodes": merged_nodes, "edges": merged_edges}


# ── Public entry point ──────────────────────────────────────────────────────

def _to_frontend_format(graph: dict[str, Any]) -> dict[str, Any]:
    """
    Convert the LLM graph format to the frontend-expected format:
    - nodes: [{id: int, label, full_label, status, x, y, mutation_count}, ...]
    - edges: [[src_id, dst_id], ...]

    Positions are computed via topological layering so the graph
    looks like a proper network, not a straight line.
    """
    import math

    nodes = graph.get("nodes", [])
    edges = graph.get("edges", [])
    total = len(nodes)

    if total == 0:
        return {"nodes": [], "edges": []}

    # Map string ids → numeric ids
    id_map: dict[str, int] = {}
    str_ids: list[str] = []
    for i, n in enumerate(nodes):
        numeric_id = i + 1
        id_map[n["id"]] = numeric_id
        str_ids.append(n["id"])

    # Build adjacency for layout (using string ids)
    children: dict[str, list[str]] = {sid: [] for sid in str_ids}
    parents: dict[str, list[str]] = {sid: [] for sid in str_ids}
    for e in edges:
        src, tgt = e.get("source"), e.get("target")
        if src in children and tgt in parents:
            children[src].append(tgt)
            parents[tgt].append(src)

    # ── Topological layering (Kahn's algorithm) ─────────────────────────
    in_degree = {sid: len(parents[sid]) for sid in str_ids}
    layer_of: dict[str, int] = {}
    queue = [sid for sid in str_ids if in_degree[sid] == 0]
    # If no roots (cycle or all connected), pick first node
    if not queue:
        queue = [str_ids[0]]

    layer = 0
    visited: set[str] = set()
    layers: list[list[str]] = []
    while queue:
        layers.append(queue)
        for sid in queue:
            layer_of[sid] = layer
            visited.add(sid)
        next_queue = []
        for sid in queue:
            for child in children[sid]:
                if child not in visited:
                    in_degree[child] -= 1
                    if in_degree[child] <= 0:
                        next_queue.append(child)
        layer += 1
        queue = next_queue

    # Place any unvisited nodes (disconnected or in cycles) in the last layer
    for sid in str_ids:
        if sid not in visited:
            layer_of[sid] = layer
            if not layers or len(layers) <= layer:
                layers.append([])
            layers[-1].append(sid)

    # ── Compute x, y positions from layers ───────────────────────────────
    num_layers = max(layer_of.values()) + 1 if layer_of else 1
    positions: dict[str, tuple[int, int]] = {}

    for ly in range(num_layers):
        members = [sid for sid in str_ids if layer_of.get(sid) == ly]
        count = len(members)
        # y: spread layers top-to-bottom (10–90%)
        y = round(10 + (ly / max(num_layers - 1, 1)) * 80) if num_layers > 1 else 50
        for j, sid in enumerate(members):
            # x: spread nodes in this layer left-to-right (10–90%)
            x = round(10 + (j / max(count - 1, 1)) * 80) if count > 1 else 50
            positions[sid] = (x, y)

    # ── Build frontend nodes ─────────────────────────────────────────────
    frontend_nodes: list[dict] = []
    for i, n in enumerate(nodes):
        sid = n["id"]
        x, y = positions.get(sid, (50, 50))
        frontend_nodes.append({
            "id": id_map[sid],
            "label": (n["label"] if len(n["label"]) <= 32
                      else n["label"][:30].rsplit(' ', 1)[0] + '…'),
            "full_label": n["label"],
            "status": "partial",
            "x": x,
            "y": y,
            "mutation_count": 0,
        })

    frontend_edges: list[list[int]] = []
    seen_edges: set[tuple[int, int]] = set()
    for e in edges:
        src = id_map.get(e["source"])
        tgt = id_map.get(e["target"])
        if src and tgt and (src, tgt) not in seen_edges:
            seen_edges.add((src, tgt))
            frontend_edges.append([src, tgt])

    return {"nodes": frontend_nodes, "edges": frontend_edges}


async def build_knowledge_graph(note_text: str) -> dict[str, Any]:
    """
    Full pipeline: notes → concept extraction → LLM graph → frontend format.

    Returns: {"nodes": [...], "edges": [...]} ready for the frontend.
    """
    concepts = extract_concepts_from_notes(note_text)
    if not concepts:
        return {
            "nodes": [{"id": 1, "label": "Lecture Topics", "full_label": "Lecture Topics",
                        "status": "partial", "x": 50, "y": 50, "mutation_count": 0}],
            "edges": [],
        }

    graph = await build_graph_with_llm(concepts)
    return _to_frontend_format(graph)
