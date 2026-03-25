"""
Deep mastery store tests — edge cases, concurrency, and data integrity.
Run: cd backend && python -m pytest tests/test_mastery_advanced.py -v
"""
import sys, os, pytest, asyncio
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))


def _patch_store(monkeypatch, tmp_path):
    import agents.mastery_store as ms
    monkeypatch.setattr(ms, "DB_PATH", str(tmp_path / "mastery_adv.db"))
    ms._init_tables()


# ── Non-existent node handling ────────────────────────────────────────────────

def test_update_unknown_label_does_not_raise(monkeypatch, tmp_path):
    """Updating a node with an unknown label should not raise an exception."""
    _patch_store(monkeypatch, tmp_path)
    from agents.mastery_store import update_node_status
    # Should silently do nothing or return None — not raise
    result = update_node_status("label_that_does_not_exist_xyz", "mastered", "user1")
    assert result is None  # graceful no-op


def test_increment_unknown_label_does_not_raise(monkeypatch, tmp_path):
    """Incrementing mutation count for unknown label should not raise."""
    _patch_store(monkeypatch, tmp_path)
    from agents.mastery_store import increment_mutation_count
    # Should silently do nothing — not raise
    increment_mutation_count("unknown_concept_abc", "user1")


# ── Status transitions ────────────────────────────────────────────────────────

def test_status_transitions_unknown_to_mastered(monkeypatch, tmp_path):
    """Node can progress from unknown → partial → mastered."""
    _patch_store(monkeypatch, tmp_path)
    from agents.mastery_store import get_db, update_node_status
    db = get_db("status_tester")
    if not db["nodes"]:
        pytest.skip("No default nodes in mastery store")
    label = db["nodes"][0]["label"]

    for status in ("unknown", "partial", "mastered"):
        result = update_node_status(label, status, "status_tester")
        assert result is not None or status == "unknown"
        db2 = get_db("status_tester")
        node = next((n for n in db2["nodes"] if n["label"] == label), None)
        if result is not None:
            assert node["status"] == status


# ── Mutation count increments ─────────────────────────────────────────────────

def test_mutation_count_increments_are_cumulative(monkeypatch, tmp_path):
    """Multiple increments should accumulate correctly."""
    _patch_store(monkeypatch, tmp_path)
    from agents.mastery_store import get_db, increment_mutation_count
    db = get_db("counter_tester")
    if not db["nodes"]:
        pytest.skip("No default nodes")
    label = db["nodes"][0]["label"]

    increment_mutation_count(label, "counter_tester")
    increment_mutation_count(label, "counter_tester")
    increment_mutation_count(label, "counter_tester")

    db2 = get_db("counter_tester")
    node = next((n for n in db2["nodes"] if n["label"] == label), None)
    assert node.get("mutation_count", 0) >= 3


# ── User isolation ────────────────────────────────────────────────────────────

def test_user_mastery_does_not_bleed_across_users(monkeypatch, tmp_path):
    """Mastering a concept for user_a must not affect user_b."""
    _patch_store(monkeypatch, tmp_path)
    from agents.mastery_store import get_db, update_node_status
    db_a = get_db("user_a2")
    db_b = get_db("user_b2")
    if not db_a["nodes"] or not db_b["nodes"]:
        pytest.skip("No default nodes")

    label = db_a["nodes"][0]["label"]

    # First set both users to a known baseline (partial)
    update_node_status(label, "partial", "user_a2")
    update_node_status(label, "partial", "user_b2")

    # Now only update user_a2 to mastered
    update_node_status(label, "mastered", "user_a2")

    # user_b2 should still be "partial", not "mastered"
    db_b2 = get_db("user_b2")
    node_b = next((n for n in db_b2["nodes"] if n["label"] == label), None)
    if node_b:
        assert node_b.get("status") == "partial", \
            f"User B's mastery should not be affected by User A's update; got {node_b.get('status')!r}"


# ── Concurrent writes ─────────────────────────────────────────────────────────

def test_concurrent_status_updates_do_not_corrupt(monkeypatch, tmp_path):
    """Simulate rapid concurrent writes and verify final state is consistent."""
    _patch_store(monkeypatch, tmp_path)
    from agents.mastery_store import get_db, update_node_status

    db = get_db("concurrent_user")
    if not db["nodes"]:
        pytest.skip("No default nodes")
    label = db["nodes"][0]["label"]

    # Run several updates in rapid succession (simulates concurrent requests)
    statuses = ["partial", "mastered", "partial", "unknown", "mastered"]
    for s in statuses:
        update_node_status(label, s, "concurrent_user")

    db2 = get_db("concurrent_user")
    node = next((n for n in db2["nodes"] if n["label"] == label), None)
    assert node is not None
    assert node["status"] in ("unknown", "partial", "mastered")  # valid state


# ── Empty graphs ──────────────────────────────────────────────────────────────

def test_save_and_reload_empty_graph(monkeypatch, tmp_path):
    """Saving an empty nodes list should not break get_db."""
    _patch_store(monkeypatch, tmp_path)
    from agents.mastery_store import get_db, save_db
    db = get_db("empty_graph_user")
    empty_db = {"nodes": [], "edges": []}
    save_db(empty_db, "empty_graph_user")
    db2 = get_db("empty_graph_user")
    assert isinstance(db2["nodes"], list)
    assert isinstance(db2["edges"], list)


def test_get_db_returns_dict_with_required_keys(monkeypatch, tmp_path):
    """get_db must always return a dict with 'nodes' and 'edges' keys."""
    _patch_store(monkeypatch, tmp_path)
    from agents.mastery_store import get_db
    result = get_db("structure_check_user")
    assert "nodes" in result
    assert "edges" in result
    assert isinstance(result["nodes"], list)
    assert isinstance(result["edges"], list)
