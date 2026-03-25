"""Tests for agents/mastery_store.py — run: cd backend && python -m pytest tests/test_mastery_store.py -v"""
import sys, os, pytest
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

def _patch_store(monkeypatch, tmp_path):
    import agents.mastery_store as ms
    db = str(tmp_path / "mastery_test.db")
    monkeypatch.setattr(ms, "DB_PATH", db)
    ms._init_tables()

def test_get_db_new_user_has_nodes(monkeypatch, tmp_path):
    _patch_store(monkeypatch, tmp_path)
    from agents.mastery_store import get_db
    db = get_db("alice")
    assert "nodes" in db and "edges" in db
    assert len(db["nodes"]) > 0

def test_save_and_get_db_roundtrip(monkeypatch, tmp_path):
    _patch_store(monkeypatch, tmp_path)
    from agents.mastery_store import get_db, save_db
    db = get_db("bob")
    if db["nodes"]:
        db["nodes"][0]["status"] = "mastered"
        save_db(db, "bob")
        db2 = get_db("bob")
        assert db2["nodes"][0]["status"] == "mastered"

def test_update_node_status(monkeypatch, tmp_path):
    _patch_store(monkeypatch, tmp_path)
    from agents.mastery_store import get_db, update_node_status
    db = get_db("carol")
    if db["nodes"]:
        label = db["nodes"][0]["label"]
        result = update_node_status(label, "mastered", "carol")
        assert result is not None
        db2 = get_db("carol")
        node = next((n for n in db2["nodes"] if n["label"] == label), None)
        assert node is not None and node["status"] == "mastered"

def test_increment_mutation_count(monkeypatch, tmp_path):
    _patch_store(monkeypatch, tmp_path)
    from agents.mastery_store import get_db, increment_mutation_count
    db = get_db("dave")
    if db["nodes"]:
        label = db["nodes"][0]["label"]
        increment_mutation_count(label, "dave")
        db2 = get_db("dave")
        node = next((n for n in db2["nodes"] if n["label"] == label), None)
        assert node is not None and node.get("mutation_count", 0) >= 1

def test_separate_users_isolated(monkeypatch, tmp_path):
    _patch_store(monkeypatch, tmp_path)
    from agents.mastery_store import get_db, update_node_status
    db_a = get_db("user_a")
    db_b = get_db("user_b")
    if db_a["nodes"] and db_b["nodes"]:
        label_a = db_a["nodes"][0]["label"]
        # Set both to a known baseline so the test is deterministic
        update_node_status(label_a, "partial", "user_a")
        update_node_status(label_a, "partial", "user_b")
        # Now only update user_a
        update_node_status(label_a, "mastered", "user_a")
        db_b2 = get_db("user_b")
        node_b = next((n for n in db_b2["nodes"] if n["label"] == label_a), None)
        if node_b is not None:
            assert node_b["status"] == "partial", \
                f"User B's status should not have been changed; got {node_b['status']!r}"
