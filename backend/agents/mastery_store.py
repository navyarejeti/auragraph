"""
agents/mastery_store.py — Cognitive Knowledge Graph Store
──────────────────────────────────────────────────────────
Stores per-user concept mastery graphs (nodes + edges).

Priority:
  1. Azure Cosmos DB (NoSQL)  — COSMOS_DB_URL + COSMOS_DB_KEY
  2. SQLite fallback          — always available locally

The Cosmos DB backend stores one document per user, identified by
the user_id as the document id. This gives sub-10ms reads and global
replication for free when deployed on Azure.

Public API (same interface regardless of backend):
  get_db(username)                           → {"nodes": [...], "edges": [...]}
  save_db(db, username)                      → None
  update_node_status(label, status, username)→ node dict | None
  increment_mutation_count(label, username)  → None
"""
from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Optional

logger = logging.getLogger("auragraph")

# ── Default starter graph ─────────────────────────────────────────────────────
_DEFAULT_NODES = [
    {"id": 1, "label": "Fourier Transform",   "status": "mastered",   "x": 50, "y": 18, "mutation_count": 0},
    {"id": 2, "label": "Convolution Theorem", "status": "struggling", "x": 50, "y": 44, "mutation_count": 0},
    {"id": 3, "label": "LTI Systems",          "status": "partial",    "x": 20, "y": 70, "mutation_count": 0},
    {"id": 4, "label": "Freq. Response",       "status": "mastered",   "x": 80, "y": 70, "mutation_count": 0},
    {"id": 5, "label": "Z-Transform",          "status": "partial",    "x": 50, "y": 90, "mutation_count": 0},
]
_DEFAULT_EDGES = [[1, 2], [2, 3], [2, 4], [3, 5], [4, 5]]


# ═══════════════════════════════════════════════════════════════════════════════
# Azure Cosmos DB backend
# ═══════════════════════════════════════════════════════════════════════════════

def _cosmos_configured() -> bool:
    url = os.environ.get("COSMOS_DB_URL", "")
    key = os.environ.get("COSMOS_DB_KEY", "")
    return bool(url and key
                and "placeholder" not in url.lower()
                and "your-" not in key.lower())


class _CosmosBackend:
    """
    Stores each user's graph as a single Cosmos DB document:
      { "id": username, "nodes": [...], "edges": [[src,dst], ...] }
    """

    def __init__(self):
        from azure.cosmos import CosmosClient, PartitionKey, exceptions
        url      = os.environ.get("COSMOS_DB_URL", "").rstrip("/")
        key      = os.environ.get("COSMOS_DB_KEY", "")
        db_name  = os.environ.get("COSMOS_DB_DATABASE", "auragraph")
        ctr_name = os.environ.get("COSMOS_DB_CONTAINER", "mastery")

        self._client = CosmosClient(url=url, credential=key)
        db = self._client.create_database_if_not_exists(id=db_name)
        self._container = db.create_container_if_not_exists(
            id=ctr_name,
            partition_key=PartitionKey(path="/id"),
            offer_throughput=400,
        )
        self._exceptions = exceptions
        logger.info("mastery_store: using Azure Cosmos DB (%s / %s)", db_name, ctr_name)

    def get(self, username: str) -> dict:
        try:
            item = self._container.read_item(item=username, partition_key=username)
            return {"nodes": item.get("nodes", []), "edges": item.get("edges", [])}
        except self._exceptions.CosmosResourceNotFoundError:
            return {"nodes": [], "edges": []}
        except Exception as e:
            logger.warning("Cosmos get_db failed for %s: %s", username, e)
            return {"nodes": [], "edges": []}

    def save(self, username: str, db: dict) -> None:
        try:
            self._container.upsert_item({
                "id":     username,
                "nodes":  db.get("nodes", []),
                "edges":  db.get("edges", []),
            })
        except Exception as e:
            logger.warning("Cosmos save_db failed for %s: %s", username, e)


# ═══════════════════════════════════════════════════════════════════════════════
# SQLite backend (fallback)
# ═══════════════════════════════════════════════════════════════════════════════

class _SQLiteBackend:
    def __init__(self):
        from agents.db_pool import pooled_conn
        self._pooled = pooled_conn
        self._db_path = str(Path(__file__).parent.parent / "auragraph.db")
        self._init_tables()
        logger.info("mastery_store: using SQLite fallback (%s)", self._db_path)

    def _init_tables(self):
        with self._pooled(self._db_path) as con:
            con.executescript("""
                CREATE TABLE IF NOT EXISTS mastery_nodes (
                    user_id        TEXT    NOT NULL,
                    node_id        INTEGER NOT NULL,
                    label          TEXT    NOT NULL,
                    status         TEXT    NOT NULL DEFAULT 'partial',
                    x              REAL    NOT NULL DEFAULT 50,
                    y              REAL    NOT NULL DEFAULT 50,
                    mutation_count INTEGER NOT NULL DEFAULT 0,
                    PRIMARY KEY (user_id, node_id)
                );
                CREATE TABLE IF NOT EXISTS mastery_edges (
                    user_id  TEXT    NOT NULL,
                    from_id  INTEGER NOT NULL,
                    to_id    INTEGER NOT NULL,
                    PRIMARY KEY (user_id, from_id, to_id)
                );
                CREATE INDEX IF NOT EXISTS idx_mn_user ON mastery_nodes(user_id);
                CREATE INDEX IF NOT EXISTS idx_me_user ON mastery_edges(user_id);
            """)

    def get(self, username: str) -> dict:
        with self._pooled(self._db_path) as con:
            nodes = [
                {"id": r["node_id"], "label": r["label"], "status": r["status"],
                 "x": r["x"], "y": r["y"], "mutation_count": r["mutation_count"]}
                for r in con.execute(
                    "SELECT * FROM mastery_nodes WHERE user_id=? ORDER BY node_id", (username,)
                ).fetchall()
            ]
            edges = [
                [r["from_id"], r["to_id"]]
                for r in con.execute(
                    "SELECT from_id, to_id FROM mastery_edges WHERE user_id=?", (username,)
                ).fetchall()
            ]
        return {"nodes": nodes, "edges": edges}

    def save(self, username: str, db: dict) -> None:
        with self._pooled(self._db_path) as con:
            for n in db.get("nodes", []):
                con.execute("""
                    INSERT INTO mastery_nodes (user_id, node_id, label, status, x, y, mutation_count)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(user_id, node_id) DO UPDATE SET
                        label=excluded.label, status=excluded.status,
                        x=excluded.x, y=excluded.y, mutation_count=excluded.mutation_count
                """, (username, n["id"], n["label"], n.get("status", "partial"),
                      n.get("x", 50), n.get("y", 50), n.get("mutation_count", 0)))
            con.execute("DELETE FROM mastery_edges WHERE user_id=?", (username,))
            for e in db.get("edges", []):
                if len(e) >= 2:
                    con.execute(
                        "INSERT OR IGNORE INTO mastery_edges (user_id, from_id, to_id) VALUES (?,?,?)",
                        (username, e[0], e[1])
                    )


# ═══════════════════════════════════════════════════════════════════════════════
# Singleton backend selection
# ═══════════════════════════════════════════════════════════════════════════════

_backend = None

def _get_backend():
    global _backend
    if _backend is not None:
        return _backend
    if _cosmos_configured():
        try:
            _backend = _CosmosBackend()
            return _backend
        except Exception as e:
            logger.warning("Cosmos DB init failed — falling back to SQLite: %s", e)
    _backend = _SQLiteBackend()
    return _backend


# ═══════════════════════════════════════════════════════════════════════════════
# Public API
# ═══════════════════════════════════════════════════════════════════════════════

def get_db(username: str = "anonymous") -> dict:
    """Return mastery graph for *username*, seeding defaults if absent."""
    backend = _get_backend()
    db = backend.get(username)
    if not db["nodes"]:
        db = {"nodes": [dict(n) for n in _DEFAULT_NODES],
              "edges": [list(e) for e in _DEFAULT_EDGES]}
        backend.save(username, db)
    return db


def save_db(db: dict, username: str = "anonymous") -> None:
    _get_backend().save(username, db)


def update_node_status(node_label: str, new_status: str,
                       username: str = "anonymous") -> Optional[dict]:
    """Update mastery status for a node by label. Returns updated node or None."""
    db = get_db(username)
    for node in db["nodes"]:
        if node["label"].lower() == node_label.lower():
            node["status"] = new_status
            save_db(db, username)
            return dict(node)
    return None


def increment_mutation_count(node_label: str, username: str = "anonymous") -> None:
    """Increment mutation_count for the matching node. Silent no-op if not found."""
    db = get_db(username)
    for node in db["nodes"]:
        if node["label"].lower() == node_label.lower():
            node["mutation_count"] = node.get("mutation_count", 0) + 1
            save_db(db, username)
            return


# ── Legacy migration helper (kept for backward compat) ────────────────────────
def migrate_json_files() -> int:
    """One-shot migration from old mock_db_*.json files into the active backend."""
    import json, re
    backend_dir = Path(__file__).parent.parent
    migrated = 0
    for jf in backend_dir.glob("mock_db_*.json"):
        m = re.match(r"mock_db_(.+)\.json$", jf.name)
        if not m:
            continue
        username = m.group(1)
        try:
            data = json.loads(jf.read_text(encoding="utf-8"))
            _get_backend().save(username, data)
            jf.rename(jf.with_suffix(".json.migrated"))
            migrated += 1
            logger.info("mastery_store: migrated %s", jf.name)
        except Exception as exc:
            logger.warning("mastery_store: failed to migrate %s: %s", jf.name, exc)
    return migrated


# ── Test compatibility shims ──────────────────────────────────────────────────
# These are used by tests/test_mastery_store.py via monkeypatch.
# They forward to the SQLite backend and reset the singleton.

DB_PATH = str(Path(__file__).parent.parent / "auragraph.db")


def _init_tables() -> None:
    """
    Re-initialise the SQLite backend, honouring a monkeypatched DB_PATH.
    Called by tests after `monkeypatch.setattr(ms, 'DB_PATH', tmp_path)`.
    Resets the module-level singleton so the new DB_PATH is picked up.
    """
    global _backend
    # Force SQLite backend using the current DB_PATH value
    sqlite_be = _SQLiteBackend.__new__(_SQLiteBackend)
    sqlite_be._pooled = __import__('agents.db_pool', fromlist=['pooled_conn']).pooled_conn
    sqlite_be._db_path = DB_PATH
    sqlite_be._init_tables()
    _backend = sqlite_be
