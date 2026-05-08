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


def _fresh_state(tmp_path, monkeypatch):
    monkeypatch.setattr(storage, "STATE_DIR", tmp_path)


def test_update_pantry_accepts_bare_string(tmp_path, monkeypatch):
    _fresh_state(tmp_path, monkeypatch)
    s = state_mod.update_pantry(add=["rice"])
    assert s.pantry == [PantryItem(name="rice")]


def test_update_pantry_accepts_dict(tmp_path, monkeypatch):
    _fresh_state(tmp_path, monkeypatch)
    s = state_mod.update_pantry(add=[{
        "name": "salmon", "quantity": "280g", "expiry_at": "2026-05-07",
    }])
    assert s.pantry[0].name == "salmon"
    assert s.pantry[0].quantity == "280g"
    assert s.pantry[0].expiry_at == date(2026, 5, 7)


def test_update_pantry_dedupe_overwrites_quantity(tmp_path, monkeypatch):
    _fresh_state(tmp_path, monkeypatch)
    state_mod.update_pantry(add=["rice"])
    s = state_mod.update_pantry(add=[{"name": "rice", "quantity": "1 bag"}])
    assert len(s.pantry) == 1
    assert s.pantry[0].quantity == "1 bag"


def test_update_pantry_dedupe_keeps_later_expiry(tmp_path, monkeypatch):
    _fresh_state(tmp_path, monkeypatch)
    state_mod.update_pantry(add=[{"name": "salmon", "expiry_at": "2026-05-07"}])
    s = state_mod.update_pantry(add=[{"name": "salmon", "expiry_at": "2026-05-09"}])
    assert len(s.pantry) == 1
    assert s.pantry[0].expiry_at == date(2026, 5, 9)


def test_update_pantry_remove_case_insensitive(tmp_path, monkeypatch):
    _fresh_state(tmp_path, monkeypatch)
    state_mod.update_pantry(add=["Salmon"])
    s = state_mod.update_pantry(remove=["salmon"])
    assert s.pantry == []


def test_update_pantry_dedupe_does_not_clear_quantity(tmp_path, monkeypatch):
    """Adding a bare name when an item with quantity already exists must not wipe quantity."""
    _fresh_state(tmp_path, monkeypatch)
    state_mod.update_pantry(add=[{"name": "salmon", "quantity": "280g"}])
    s = state_mod.update_pantry(add=["salmon"])
    assert len(s.pantry) == 1
    assert s.pantry[0].quantity == "280g"


def test_state_summary_renders_pantry_shapes(tmp_path, monkeypatch):
    """Pantry rendering: bare name, name + qty, name + expiry, name + both."""
    monkeypatch.setattr(storage, "STATE_DIR", tmp_path)
    state_mod.update_pantry(add=[
        "rice",
        {"name": "salmon", "quantity": "280g", "expiry_at": "2026-05-07"},
        {"name": "lemons", "quantity": "x4"},
        {"name": "yoghurt", "expiry_at": "2026-05-09"},
    ])

    from agents.orchestrator import _state_summary
    summary = _state_summary()
    assert "rice" in summary
    assert "salmon (280g, exp 2026-05-07)" in summary
    assert "lemons (x4)" in summary
    assert "yoghurt (exp 2026-05-09)" in summary
