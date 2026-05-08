import os

import pytest

import tools.recipes as recipes_mod
from agents.orchestrator import run_turn

pytestmark = pytest.mark.eval


def _last_summary_tools(traces_dir):
    import json
    sf = traces_dir / "summary.jsonl"
    last = json.loads(sf.read_text("utf-8").splitlines()[-1])
    return [c["name"] for c in last["tool_calls"]], last["total_tokens"]


def test_edit_recipe_changes_cuisine(fresh_state, monkeypatch, tmp_path_factory):
    # Pre-condition: salmon-teriyaki-bowls.cuisine == "unknown"
    pre = recipes_mod.load_all_recipes()
    assert next(r for r in pre if r.id == "salmon-teriyaki-bowls").cuisine == "unknown"

    reply, _ = run_turn(
        "change the cuisine on Salmon teriyaki bowls to Japanese, just do it",
        history=[],
    )

    post = recipes_mod.load_all_recipes()
    after = next(r for r in post if r.id == "salmon-teriyaki-bowls")
    assert after.cuisine.lower() == "japanese", f"cuisine not updated; reply was: {reply}"

    # Token ceiling: edit-recipe is a small workflow.
    import tracing
    summary = tracing.last_turn_summary()
    assert summary is not None
    assert summary["total_tokens"] <= 12000, f"edit_recipe burned {summary['total_tokens']} tokens"
    names = [c["name"] for c in summary["tool_calls"]]
    assert "update_recipe" in names


def test_delete_recipe_removes_row(fresh_state):
    pre_ids = {r.id for r in recipes_mod.load_all_recipes()}
    assert "ratatouille" in pre_ids

    reply, _ = run_turn("delete the ratatouille recipe, just do it", history=[])

    post_ids = {r.id for r in recipes_mod.load_all_recipes()}
    assert "ratatouille" not in post_ids, f"not deleted; reply was: {reply}"

    import tracing
    summary = tracing.last_turn_summary()
    assert summary is not None
    assert summary["total_tokens"] <= 12000
    assert "delete_recipe" in [c["name"] for c in summary["tool_calls"]]


def test_validate_runs_inside_update_plan(fresh_state):
    """The orchestrator's dispatcher runs validate inside update_plan; we just
    assert update_plan was called and the plan was persisted with 5 slots."""
    from tools.state import read_state

    reply, _ = run_turn(
        "plan next week's dinners, just do it. use what's already in our recipe library where it makes sense.",
        history=[],
    )
    s = read_state()
    assert len(s.meal_plan) == 5, f"expected 5 slots; reply was: {reply}"

    import tracing
    summary = tracing.last_turn_summary()
    assert summary is not None
    assert summary["total_tokens"] <= 30000
    assert "update_plan" in [c["name"] for c in summary["tool_calls"]]


def test_no_web_search_unless_asked(fresh_state):
    reply, _ = run_turn("plan next week, just do it.", history=[])
    import tracing
    summary = tracing.last_turn_summary()
    assert summary is not None
    assert "find_new_recipes" not in [c["name"] for c in summary["tool_calls"]], reply


def test_web_search_when_explicitly_asked(fresh_state):
    if not os.getenv("OPENROUTER_API_KEY"):
        pytest.skip("OPENROUTER_API_KEY required for web-search eval")

    reply, _ = run_turn(
        "find me 3 new bacalhau recipes from the web — just do it.",
        history=[],
    )
    import tracing
    summary = tracing.last_turn_summary()
    assert summary is not None
    assert summary["total_tokens"] <= 35000
    assert "find_new_recipes" in [c["name"] for c in summary["tool_calls"]], reply
