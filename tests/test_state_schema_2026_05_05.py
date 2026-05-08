"""Schema-bump tests for the 2026-05-05 foundations sub-project."""
import json
from datetime import datetime, date
from pathlib import Path

import storage
import tools.state as state_mod
from models import State, PantryItem


def _write_state(tmp_path: Path, payload: dict) -> Path:
    p = tmp_path / "state.json"
    p.write_text(json.dumps(payload), encoding="utf-8")
    return p


def test_state_loads_legacy_pantry_strings(tmp_path, monkeypatch):
    """Bare-string pantry entries from older state.json files must load."""
    monkeypatch.setattr(storage, "STATE_DIR", tmp_path)
    _write_state(tmp_path, {
        "meal_plan": [], "week_of": None, "plan_history": [],
        "pantry": ["rice", "salmon", "tinned tomatoes"],
        "ratings": [], "last_updated": "2026-05-04T12:00:00",
    })
    s = state_mod.read_state()
    assert all(isinstance(p, PantryItem) for p in s.pantry)
    assert [p.name for p in s.pantry] == ["rice", "salmon", "tinned tomatoes"]
    assert all(p.quantity is None and p.expiry_at is None for p in s.pantry)


def test_state_loads_mixed_pantry(tmp_path, monkeypatch):
    """Mixed string + dict pantry entries must load."""
    monkeypatch.setattr(storage, "STATE_DIR", tmp_path)
    _write_state(tmp_path, {
        "meal_plan": [], "week_of": None, "plan_history": [],
        "pantry": [
            "rice",
            {"name": "salmon", "quantity": "280g", "expiry_at": "2026-05-07"},
        ],
        "ratings": [], "last_updated": "2026-05-04T12:00:00",
    })
    s = state_mod.read_state()
    assert s.pantry[0] == PantryItem(name="rice")
    assert s.pantry[1] == PantryItem(
        name="salmon", quantity="280g", expiry_at=date(2026, 5, 7),
    )


def test_pantry_round_trip_normalises_to_dicts(tmp_path, monkeypatch):
    """Legacy load → save → reload should produce dict-shaped on-disk pantry."""
    monkeypatch.setattr(storage, "STATE_DIR", tmp_path)
    _write_state(tmp_path, {
        "meal_plan": [], "week_of": None, "plan_history": [],
        "pantry": ["rice"],
        "ratings": [], "last_updated": "2026-05-04T12:00:00",
    })
    s = state_mod.read_state()
    storage.save_json("state.json", s)

    raw = json.loads((tmp_path / "state.json").read_text(encoding="utf-8"))
    assert raw["pantry"] == [
        {"name": "rice", "quantity": None, "expiry_at": None},
    ]
