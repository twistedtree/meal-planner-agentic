from datetime import datetime
from models import Profile, Member, Recipe, Rating, MealPlanSlot, State


def test_profile_roundtrip():
    p = Profile(
        household_size=4,
        members=[
            Member(name="Ana", is_adult=True, dislikes=["mushrooms"]),
            Member(name="Mia", is_adult=False, dislikes=["olives"]),
        ],
        household_dislikes=["liver"],
        dietary_rules=["≥1 fish/week"],
        preferred_cuisines=["italian", "sg-chinese"],
        notes="",
    )
    s = p.model_dump_json()
    p2 = Profile.model_validate_json(s)
    assert p2 == p


def test_recipe_defaults():
    r = Recipe(
        id="salmon-teriyaki",
        title="Salmon teriyaki",
        cuisine="japanese",
        main_protein="salmon",
        key_ingredients=["salmon", "soy sauce", "mirin"],
        tags=["quick", "kid-friendly"],
        cook_time_min=25,
        added_at=datetime(2026, 4, 15),
    )
    assert r.times_cooked == 0
    assert r.last_cooked is None
    assert r.avg_rating is None
    assert r.source_url is None


def test_meal_plan_slot_optional_recipe_id():
    slot = MealPlanSlot(
        day="Mon",
        recipe_title="Pantry pasta",
        recipe_id=None,
        key_ingredients=["pasta", "tomato", "basil"],
        rationale="Uses what's in the pantry",
    )
    assert slot.recipe_id is None


def test_state_empty_defaults():
    s = State(meal_plan=[], pantry=[], ratings=[], last_updated=datetime(2026, 4, 15))
    assert s.meal_plan == []
    assert s.pantry == []
