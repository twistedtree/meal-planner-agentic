import json
import threading
import time
from collections import namedtuple
from datetime import datetime
from models import Recipe
from agents.orchestrator import _dispatch, _run_tool_calls

_F = namedtuple("Func", ["name", "arguments"])
_TC = namedtuple("Tc", ["id", "function"])


def test_dispatch_search_recipes_is_safe_to_parallelize(tmp_path, monkeypatch):
    """Two concurrent search_recipes calls should not interfere."""
    monkeypatch.setattr("storage.STATE_DIR", tmp_path)

    recipes = [
        Recipe(
            id="a", title="Chicken pho", cuisine="vietnamese",
            main_protein="chicken", key_ingredients=["chicken", "noodles"],
            tags=["light"], cook_time_min=20, added_at=datetime(2026, 1, 1),
        ),
        Recipe(
            id="b", title="Salmon teriyaki", cuisine="japanese",
            main_protein="salmon", key_ingredients=["salmon", "rice"],
            tags=["quick"], cook_time_min=15, added_at=datetime(2026, 1, 1),
        ),
    ]

    monkeypatch.setattr("tools.recipes.load_all_recipes", lambda: recipes)

    results = [None, None]

    def search_0():
        results[0] = json.loads(_dispatch("search_recipes", {"query": "chicken"}))

    def search_1():
        results[1] = json.loads(_dispatch("search_recipes", {"query": "salmon"}))

    t0 = threading.Thread(target=search_0)
    t1 = threading.Thread(target=search_1)
    t0.start()
    t1.start()
    t0.join()
    t1.join()

    assert results[0] is not None and len(results[0]) > 0
    assert results[1] is not None and len(results[1]) > 0
    assert results[0][0]["id"] == "a"
    assert results[1][0]["id"] == "b"


def _instrumented_dispatch_factory():
    """Return (dispatch fn, observed) — observed tracks max concurrent calls
    per category (mutating vs read-only) so tests can assert serialisation."""
    state = {
        "active_mutating": 0,
        "active_read": 0,
        "max_concurrent_mutating": 0,
        "max_concurrent_read": 0,
    }
    lock = threading.Lock()

    def fake_dispatch(name, args, turn_id=None):
        is_mut = name in {
            "update_plan", "update_pantry", "update_profile",
            "update_recipe", "delete_recipe", "record_rating",
        }
        key = "active_mutating" if is_mut else "active_read"
        max_key = "max_concurrent_mutating" if is_mut else "max_concurrent_read"
        with lock:
            state[key] += 1
            if state[key] > state[max_key]:
                state[max_key] = state[key]
        time.sleep(0.05)  # widen the overlap window so races are caught
        with lock:
            state[key] -= 1
        return '{"ok": true}'

    return fake_dispatch, state


def test_run_tool_calls_runs_mutating_serially_and_reads_in_parallel(monkeypatch):
    """Mixed batch: mutating tools must not overlap; read-only ones must."""
    dispatch, observed = _instrumented_dispatch_factory()
    monkeypatch.setattr("agents.orchestrator._dispatch", dispatch)

    tool_calls = [
        _TC("a", _F("update_pantry", "{}")),
        _TC("b", _F("get_recipe", "{}")),
        _TC("c", _F("update_plan", "{}")),
        _TC("d", _F("search_recipes", "{}")),
        _TC("e", _F("list_recipes", "{}")),
    ]

    results = _run_tool_calls(tool_calls, "test-turn")

    assert len(results) == 5
    assert observed["max_concurrent_mutating"] == 1, (
        "mutating tools overlapped — read-modify-write race possible"
    )
    assert observed["max_concurrent_read"] >= 2, (
        "read-only tools should still fan out concurrently"
    )
    # Result order matches input tool_call order so OpenAI tool_call_id semantics hold.
    assert [r["tool_call_id"] for r in results] == ["a", "b", "c", "d", "e"]


def test_run_tool_calls_single_call_skips_executor(monkeypatch):
    """Single-tool case stays on the calling thread — no executor overhead."""
    dispatch, _ = _instrumented_dispatch_factory()
    monkeypatch.setattr("agents.orchestrator._dispatch", dispatch)

    results = _run_tool_calls([_TC("only", _F("read_state", "{}"))], "t")
    assert len(results) == 1
    assert results[0]["tool_call_id"] == "only"


def test_run_tool_calls_all_mutating_runs_strictly_sequential(monkeypatch):
    """A batch of only-mutating tools must produce zero overlap."""
    dispatch, observed = _instrumented_dispatch_factory()
    monkeypatch.setattr("agents.orchestrator._dispatch", dispatch)

    tool_calls = [
        _TC("a", _F("update_pantry", "{}")),
        _TC("b", _F("update_plan", "{}")),
        _TC("c", _F("record_rating", "{}")),
    ]

    _run_tool_calls(tool_calls, "t")
    assert observed["max_concurrent_mutating"] == 1
