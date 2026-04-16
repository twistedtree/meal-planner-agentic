from datetime import datetime, date
import pytest
from models import State, MealPlanSlot, ArchivedPlan
from tools.state import read_state, update_plan


@pytest.fixture
def tmp_state_dir(tmp_path, monkeypatch):
    monkeypatch.setattr("storage.STATE_DIR", tmp_path)
    return tmp_path


def _slot(day, title):
    return {
        "day": day, "recipe_title": title, "recipe_id": None,
        "main_protein": "chicken", "key_ingredients": ["onion"],
        "rationale": "test",
    }


WEEK_1_SLOTS = [_slot(d, f"Week1-{d}") for d in ["Mon", "Tue", "Wed", "Thu", "Fri"]]
WEEK_2_SLOTS = [_slot(d, f"Week2-{d}") for d in ["Mon", "Tue", "Wed", "Thu", "Fri"]]


def test_update_plan_sets_week_of(tmp_state_dir):
    s = update_plan(WEEK_1_SLOTS, week_of=date(2026, 4, 13))
    assert s.week_of == date(2026, 4, 13)


def test_update_plan_archives_previous(tmp_state_dir):
    update_plan(WEEK_1_SLOTS, week_of=date(2026, 4, 13))
    s = update_plan(WEEK_2_SLOTS, week_of=date(2026, 4, 20))
    assert len(s.plan_history) == 1
    assert s.plan_history[0].week_of == date(2026, 4, 13)
    assert s.plan_history[0].slots[0].recipe_title == "Week1-Mon"


def test_update_plan_no_archive_without_week_of(tmp_state_dir):
    update_plan(WEEK_1_SLOTS)  # no week_of
    s = update_plan(WEEK_2_SLOTS, week_of=date(2026, 4, 20))
    assert len(s.plan_history) == 0


def test_update_plan_keeps_max_4_weeks(tmp_state_dir):
    from datetime import timedelta
    base = date(2026, 3, 2)
    for i in range(6):
        slots = [_slot(d, f"W{i}-{d}") for d in ["Mon", "Tue", "Wed", "Thu", "Fri"]]
        update_plan(slots, week_of=base + timedelta(weeks=i))
    s = read_state()
    assert len(s.plan_history) == 4


def test_update_plan_week_of_none_by_default(tmp_state_dir):
    s = update_plan(WEEK_1_SLOTS)
    assert s.week_of is None
