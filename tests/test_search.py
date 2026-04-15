from datetime import datetime
from models import Recipe
from tools.recipes import search_recipes, list_recipes, recipe_summary


def _r(id, title, cuisine="x", protein="chicken", tags=None, key=None,
       avg_rating=None, times=0, cook=20):
    return Recipe(
        id=id, title=title, cuisine=cuisine, main_protein=protein,
        key_ingredients=key or ["onion"], tags=tags or [], cook_time_min=cook,
        avg_rating=avg_rating, times_cooked=times,
        added_at=datetime(2026, 1, 1),
    )


RECIPES = [
    _r("a", "Chicken pho", cuisine="vietnamese", protein="chicken",
       tags=["light", "quick"], key=["chicken", "rice noodles", "bean sprouts"],
       avg_rating=4.5, times=3),
    _r("b", "Chicken curry", cuisine="indian", protein="chicken",
       tags=["comfort"], key=["chicken", "coconut milk", "onion"],
       avg_rating=3.5, times=5),
    _r("c", "Salmon teriyaki", cuisine="japanese", protein="salmon",
       tags=["quick", "kid-friendly"], key=["salmon", "broccoli", "rice"],
       avg_rating=4.8, times=2),
    _r("d", "Beef stew", cuisine="british", protein="beef",
       tags=["comfort"], key=["beef", "potato", "carrot"],
       avg_rating=None, times=0),
]


def test_recipe_summary_is_compact():
    s = recipe_summary(RECIPES[0])
    assert "id" in s and "title" in s and "cuisine" in s
    assert "key_ingredients" not in s  # full details excluded
    assert "source_url" not in s


def test_list_recipes_returns_summaries():
    out = list_recipes(RECIPES)
    assert len(out) == 4
    assert all("id" in r for r in out)


def test_list_recipes_filters_by_cuisine():
    out = list_recipes(RECIPES, filters={"cuisine": "japanese"})
    assert len(out) == 1
    assert out[0]["id"] == "c"


def test_list_recipes_filters_by_protein():
    out = list_recipes(RECIPES, filters={"main_protein": "chicken"})
    assert {r["id"] for r in out} == {"a", "b"}


def test_search_matches_title():
    out = search_recipes(RECIPES, query="pho")
    assert out and out[0]["id"] == "a"


def test_search_matches_ingredients():
    out = search_recipes(RECIPES, query="bean sprouts")
    assert out and out[0]["id"] == "a"


def test_search_matches_tags():
    out = search_recipes(RECIPES, query="kid-friendly")
    assert out and out[0]["id"] == "c"


def test_search_ranks_by_rating_then_times_cooked():
    # Both match "chicken" — higher avg_rating wins
    out = search_recipes(RECIPES, query="chicken")
    assert [r["id"] for r in out[:2]] == ["a", "b"]


def test_search_unrated_last():
    # Beef stew has no rating, 0 times cooked — ranks last among matches
    out = search_recipes(RECIPES, query="comfort")
    ids = [r["id"] for r in out]
    assert ids.index("b") < ids.index("d")


def test_search_respects_top_k():
    out = search_recipes(RECIPES, query="chicken", top_k=1)
    assert len(out) == 1


def test_list_recipes_rejects_unknown_filter_key():
    import pytest
    with pytest.raises(ValueError):
        list_recipes(RECIPES, filters={"main_protien": "chicken"})  # typo
