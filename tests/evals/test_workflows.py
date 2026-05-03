import os

import pytest

from agents.orchestrator import run_turn
from tools.state import read_state
from tools.profile import read_profile

pytestmark = pytest.mark.eval


def test_onboard_then_plan(tmp_path, monkeypatch):
    """Empty state → onboarding chat sets profile → plan call sets meal_plan."""
    import storage
    monkeypatch.setattr(storage, "STATE_DIR", tmp_path)

    reply1, hist1 = run_turn(
        "I'm a household of 4: 2 adults, 2 kids. The kids dislike mushrooms. "
        "We aim for fish once a week and veg every meal. Just do it — set my profile.",
        history=[],
    )
    p = read_profile()
    assert p is not None and p.household_size == 4
    assert "mushrooms" in [d.lower() for d in p.household_dislikes] + [
        d.lower() for m in p.members for d in m.dislikes
    ]

    reply2, _ = run_turn("now plan next week, just do it.", history=hist1)
    s = read_state()
    assert len(s.meal_plan) == 5, f"reply was: {reply2}"


def test_swap_then_rate(fresh_state):
    """Plan → swap one day → rate the cooked meal."""
    reply1, hist1 = run_turn("plan next week, just do it.", history=[])
    s1 = read_state()
    assert len(s1.meal_plan) == 5

    reply2, hist2 = run_turn(
        "swap Wednesday for something lighter, just do it.",
        history=hist1,
    )
    s2 = read_state()
    assert len(s2.meal_plan) == 5
    wed1 = next(slot for slot in s1.meal_plan if slot.day == "Wed").recipe_title
    wed2 = next(slot for slot in s2.meal_plan if slot.day == "Wed").recipe_title
    assert wed1 != wed2, f"Wednesday should have changed; reply was: {reply2}"

    reply3, _ = run_turn(
        f"we cooked {s2.meal_plan[0].recipe_title} on Monday and Adult1 loved it. "
        f"record that — rating again_soon. just do it.",
        history=hist2,
    )
    s3 = read_state()
    assert len(s3.ratings) >= 1, f"reply was: {reply3}"


def test_cookidoo_import():
    if not os.getenv("cookidoo_user") or not os.getenv("cookiday_pass"):
        pytest.skip("Cookidoo creds not set; skipping integration eval")
    pytest.skip("test_cookidoo_import requires a known recipe id; provide one in env COOKIDOO_TEST_RECIPE_ID")
