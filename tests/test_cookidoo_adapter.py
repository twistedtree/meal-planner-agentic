"""Unit test for the Cookidoo→Recipe adapter (no live API)."""
from types import SimpleNamespace

from tools.cookidoo import _cookidoo_details_to_recipe, _guess_main_protein, _infer_cuisine


def _fake_details() -> SimpleNamespace:
    return SimpleNamespace(
        id="r471786",
        name="Rare beef steak with herb garlic butter",
        ingredients=[
            SimpleNamespace(name="fresh flat-leaf parsley", description="2 sprigs"),
            SimpleNamespace(name="fresh thyme", description="4 sprigs"),
            SimpleNamespace(name="beef scotch fillet steaks", description="2 x 200 g"),
            SimpleNamespace(name="unsalted butter", description="50 g"),
            SimpleNamespace(name="garlic cloves", description="2"),
        ],
        categories=[SimpleNamespace(name="Main dishes - meat and poultry", notes="")],
        total_time=8100,  # 135 min
        url="https://cookidoo.com.au/recipes/recipe/en-AU/r471786",
    )


def test_adapter_maps_core_fields():
    r = _cookidoo_details_to_recipe(_fake_details())
    assert r.id == "r471786"
    assert r.title == "Rare beef steak with herb garlic butter"
    assert r.main_protein == "beef"
    assert r.cook_time_min == 135
    assert r.source_url.endswith("r471786")
    assert r.source == "cookidoo"
    assert "cookidoo" not in r.tags  # source replaces tag
    assert "Main dishes - meat and poultry" in r.tags


def test_cuisine_inferred_from_title_italian():
    r = _cookidoo_details_to_recipe(SimpleNamespace(
        id="r1", name="Spaghetti carbonara",
        ingredients=[SimpleNamespace(name="pasta", description="")],
        categories=[], total_time=1200, url="u",
    ))
    assert r.cuisine == "italian"


def test_cuisine_inferred_thai_beats_indian_when_thai_word_present():
    assert _infer_cuisine("Thai red chicken curry", ["chicken", "red curry paste"]) == "thai"


def test_cuisine_unknown_when_no_keyword_hits():
    assert _infer_cuisine("Rare beef steak with herb garlic butter",
                          ["beef", "butter", "thyme", "parsley"]) == "unknown"


def test_adapter_key_ingredients_capped_at_8():
    details = _fake_details()
    details.ingredients = [SimpleNamespace(name=f"ing{i}", description="") for i in range(20)]
    r = _cookidoo_details_to_recipe(details)
    assert len(r.key_ingredients) == 8


def test_protein_guess_order_fish_before_chicken():
    # Salmon should win over chicken if both appear (fish listed first)
    assert _guess_main_protein(["salmon fillet", "chicken stock"]) == "salmon"


def test_protein_guess_unknown_when_nothing_matches():
    assert _guess_main_protein(["flour", "sugar", "butter"]) == "unknown"


def test_protein_guess_ignores_fish_sauce():
    # Classic Thai curry: fish sauce is seasoning, chicken is the protein
    assert _guess_main_protein(["chicken thighs", "fish sauce", "coconut milk"]) == "chicken"


def test_protein_guess_ignores_chicken_stock():
    # Risotto with chicken stock is not a "chicken" dish
    assert _guess_main_protein(["arborio rice", "chicken stock", "mushrooms"]) == "unknown"


def test_adapter_handles_missing_total_time():
    details = _fake_details()
    details.total_time = None
    r = _cookidoo_details_to_recipe(details)
    assert r.cook_time_min == 30  # default
