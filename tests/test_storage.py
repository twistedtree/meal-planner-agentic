from datetime import datetime
from pathlib import Path
import json
import pytest
from models import Profile, Member, State
from storage import load_json, save_json, STATE_DIR


@pytest.fixture
def tmp_state_dir(tmp_path, monkeypatch):
    monkeypatch.setattr("storage.STATE_DIR", tmp_path)
    return tmp_path


def test_load_missing_returns_none(tmp_state_dir):
    assert load_json("profile.json", Profile) is None


def test_save_then_load_roundtrip(tmp_state_dir):
    p = Profile(
        household_size=2,
        members=[Member(name="A", is_adult=True, dislikes=[])],
        household_dislikes=[],
        dietary_rules=[],
        preferred_cuisines=[],
        notes="",
    )
    save_json("profile.json", p)
    loaded = load_json("profile.json", Profile)
    assert loaded == p


def test_save_is_atomic(tmp_state_dir):
    # After a save, there should be no stray .tmp files
    s = State(meal_plan=[], pantry=[], ratings=[], last_updated=datetime(2026, 4, 15))
    save_json("state.json", s)
    assert (tmp_state_dir / "state.json").exists()
    assert not any(p.name.endswith(".tmp") for p in tmp_state_dir.iterdir())


def test_save_overwrites_cleanly(tmp_state_dir):
    s1 = State(meal_plan=[], pantry=["eggs"], ratings=[], last_updated=datetime(2026, 4, 15))
    s2 = State(meal_plan=[], pantry=["milk"], ratings=[], last_updated=datetime(2026, 4, 16))
    save_json("state.json", s1)
    save_json("state.json", s2)
    loaded = load_json("state.json", State)
    assert loaded.pantry == ["milk"]


def test_load_returns_typed_model(tmp_state_dir):
    # Manually write a file; load should parse into the model
    (tmp_state_dir / "profile.json").write_text(
        json.dumps({
            "household_size": 1,
            "members": [{"name": "X", "is_adult": True, "dislikes": []}],
            "household_dislikes": [],
            "dietary_rules": [],
            "preferred_cuisines": [],
            "notes": "",
        })
    )
    loaded = load_json("profile.json", Profile)
    assert isinstance(loaded, Profile)
    assert loaded.household_size == 1
