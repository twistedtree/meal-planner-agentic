from datetime import datetime, date
from models import Profile, Member, Recipe, Rating, MealPlanSlot, State, ArchivedPlan


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
        main_protein="none",
        key_ingredients=["pasta", "tomato", "basil"],
        rationale="Uses what's in the pantry",
    )
    assert slot.recipe_id is None


def test_state_empty_defaults():
    s = State(meal_plan=[], pantry=[], ratings=[], last_updated=datetime(2026, 4, 15))
    assert s.meal_plan == []
    assert s.pantry == []


def test_state_has_week_of_field():
    s = State(meal_plan=[], pantry=[], ratings=[], last_updated=datetime(2026, 4, 15))
    assert s.week_of is None


def test_state_week_of_set():
    s = State(
        meal_plan=[], pantry=[], ratings=[],
        last_updated=datetime(2026, 4, 15),
        week_of=date(2026, 4, 13),
    )
    assert s.week_of == date(2026, 4, 13)


def test_archived_plan_roundtrip():
    slot = MealPlanSlot(
        day="Mon", recipe_title="Test", recipe_id=None,
        main_protein="chicken", key_ingredients=["onion"], rationale="test",
    )
    ap = ArchivedPlan(week_of=date(2026, 4, 6), slots=[slot])
    dumped = ap.model_dump_json()
    loaded = ArchivedPlan.model_validate_json(dumped)
    assert loaded.week_of == date(2026, 4, 6)
    assert len(loaded.slots) == 1


def test_state_plan_history_default_empty():
    s = State(meal_plan=[], pantry=[], ratings=[], last_updated=datetime(2026, 4, 15))
    assert s.plan_history == []


def test_state_plan_history_roundtrip():
    slot = MealPlanSlot(
        day="Mon", recipe_title="Test", recipe_id=None,
        main_protein="chicken", key_ingredients=["onion"], rationale="test",
    )
    ap = ArchivedPlan(week_of=date(2026, 4, 6), slots=[slot])
    s = State(
        meal_plan=[], pantry=[], ratings=[],
        last_updated=datetime(2026, 4, 15),
        plan_history=[ap],
    )
    dumped = s.model_dump_json()
    loaded = State.model_validate_json(dumped)
    assert len(loaded.plan_history) == 1
    assert loaded.plan_history[0].week_of == date(2026, 4, 6)


def test_recipe_notes_defaults_to_empty_string():
    r = Recipe(
        id="x", title="X", cuisine="x", main_protein="x",
        key_ingredients=["a"], cook_time_min=10,
        added_at=datetime(2026, 5, 3),
    )
    assert r.notes == ""


def test_recipe_notes_round_trips():
    r = Recipe(
        id="x", title="X", cuisine="x", main_protein="x",
        key_ingredients=["a"], cook_time_min=10,
        added_at=datetime(2026, 5, 3),
        notes="great with brown rice",
    )
    j = r.model_dump_json()
    r2 = Recipe.model_validate_json(j)
    assert r2.notes == "great with brown rice"


def test_pantry_item_minimal():
    from models import PantryItem
    p = PantryItem(name="rice")
    assert p.name == "rice"
    assert p.quantity is None
    assert p.expiry_at is None


def test_pantry_item_full():
    from datetime import date
    from models import PantryItem
    p = PantryItem(name="salmon", quantity="280g", expiry_at=date(2026, 5, 7))
    assert p.quantity == "280g"
    assert p.expiry_at == date(2026, 5, 7)


def test_one_off_meal_minimal():
    from datetime import datetime
    from models import OneOffMeal
    m = OneOffMeal(recipe_title="Pasta al Pomodoro", cooked_at=datetime(2026, 5, 5, 19, 0))
    assert m.members == []
    assert m.time_min is None
