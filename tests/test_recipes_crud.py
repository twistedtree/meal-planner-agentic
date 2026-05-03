from datetime import datetime
from pathlib import Path
import pytest

from models import Recipe
import storage
import tools.recipes as recipes_mod


def _seed(tmp_path: Path, monkeypatch, items: list[Recipe]) -> None:
    monkeypatch.setattr(storage, "STATE_DIR", tmp_path)
    recipes_mod.save_all_recipes(items)


def _r(rid: str, **kw) -> Recipe:
    base = dict(
        id=rid, title=rid.replace("-", " ").title(),
        cuisine="unknown", main_protein="unknown",
        key_ingredients=["a"], cook_time_min=20,
        source="manual", added_at=datetime(2026, 5, 3),
    )
    base.update(kw)
    return Recipe(**base)


def test_update_recipe_merges_fields(tmp_path, monkeypatch):
    _seed(tmp_path, monkeypatch, [_r("salmon-bowls", cuisine="unknown", main_protein="unknown")])

    out = recipes_mod.update_recipe("salmon-bowls", {"cuisine": "japanese"})

    assert out is not None
    assert out["cuisine"] == "japanese"
    persisted = recipes_mod.load_all_recipes()
    assert persisted[0].cuisine == "japanese"
    # untouched field preserved
    assert persisted[0].main_protein == "unknown"


def test_update_recipe_drops_immutable_fields(tmp_path, monkeypatch):
    _seed(tmp_path, monkeypatch, [_r("salmon-bowls")])

    out = recipes_mod.update_recipe(
        "salmon-bowls",
        {"id": "MUTATED", "added_at": "2099-01-01T00:00:00", "cuisine": "japanese"},
    )

    assert out is not None
    assert out["id"] == "salmon-bowls"  # id is immutable
    persisted = recipes_mod.load_all_recipes()
    assert persisted[0].id == "salmon-bowls"
    assert persisted[0].added_at == datetime(2026, 5, 3)
    assert persisted[0].cuisine == "japanese"  # mutable change still applied


def test_update_recipe_invalid_type_raises(tmp_path, monkeypatch):
    from pydantic import ValidationError

    _seed(tmp_path, monkeypatch, [_r("salmon-bowls")])

    with pytest.raises(ValidationError):
        recipes_mod.update_recipe("salmon-bowls", {"cook_time_min": "twenty"})


def test_update_recipe_unknown_id_returns_none(tmp_path, monkeypatch):
    _seed(tmp_path, monkeypatch, [_r("salmon-bowls")])
    assert recipes_mod.update_recipe("nope", {"cuisine": "x"}) is None
