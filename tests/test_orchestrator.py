import json
import threading
from datetime import datetime
from models import Recipe
from agents.orchestrator import _dispatch


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
