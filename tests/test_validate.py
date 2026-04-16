from datetime import datetime, date
from models import Profile, Member, MealPlanSlot, Rating, ArchivedPlan
from tools.validate import validate_plan, PRODUCE_KEYWORDS


def _profile(**overrides):
    base = dict(
        household_size=2,
        members=[
            Member(name="A", is_adult=True, dislikes=[]),
            Member(name="B", is_adult=True, dislikes=[]),
        ],
        household_dislikes=[],
        dietary_rules=[],
        preferred_cuisines=[],
        notes="",
    )
    base.update(overrides)
    return Profile(**base)


def _slot(day, title, ingredients, protein_hint=None):
    ings = list(ingredients)
    if protein_hint and protein_hint not in ings:
        ings.insert(0, protein_hint)
    return MealPlanSlot(
        day=day, recipe_title=title, recipe_id=None,
        main_protein=protein_hint or "unknown",
        key_ingredients=ings, rationale="test",
    )


def test_valid_plan_no_warnings():
    plan = [
        _slot("Mon", "Salmon bowls", ["broccoli", "rice"], "salmon"),
        _slot("Tue", "Chicken traybake", ["potato", "carrot"], "chicken"),
        _slot("Wed", "Tofu stir fry", ["pak choi", "rice"], "tofu"),
        _slot("Thu", "Beef chilli", ["onion", "tomato"], "beef"),
        _slot("Fri", "Veg pasta", ["zucchini", "pasta"], "mushrooms-free"),
    ]
    assert validate_plan(plan, _profile(), ratings=[]) == []


def test_no_fish_warning():
    plan = [
        _slot("Mon", "Chicken bowls", ["broccoli", "rice"], "chicken"),
        _slot("Tue", "Beef stew", ["potato", "carrot"], "beef"),
        _slot("Wed", "Tofu stir fry", ["pak choi", "rice"], "tofu"),
        _slot("Thu", "Pork chops", ["apple", "cabbage"], "pork"),
        _slot("Fri", "Veg pasta", ["zucchini", "pasta"]),
    ]
    warnings = validate_plan(plan, _profile(), ratings=[])
    assert any("fish" in w.lower() for w in warnings)


def test_missing_veg_warning():
    plan = [
        _slot("Mon", "Plain rice", ["rice"]),
    ]
    warnings = validate_plan(plan, _profile(), ratings=[])
    assert any("vegetable" in w.lower() and "Mon" in w for w in warnings)


def test_household_dislike_warning():
    profile = _profile(household_dislikes=["mushrooms"])
    plan = [
        _slot("Mon", "Mushroom risotto", ["mushrooms", "rice"]),
    ]
    warnings = validate_plan(plan, profile, ratings=[])
    assert any("mushrooms" in w.lower() and "Mon" in w for w in warnings)


def test_both_adults_never_again_warning():
    profile = _profile()
    ratings = [
        Rating(recipe_title="Liver pie", rater="A", rating="never_again",
               cooked_at=datetime(2026, 3, 1)),
        Rating(recipe_title="Liver pie", rater="B", rating="never_again",
               cooked_at=datetime(2026, 3, 1)),
    ]
    plan = [_slot("Mon", "Liver pie", ["liver", "onion"])]
    warnings = validate_plan(plan, profile, ratings=ratings)
    assert any("never_again" in w.lower() or "never again" in w.lower() for w in warnings)


def test_single_adult_never_again_does_not_warn():
    profile = _profile()
    ratings = [
        Rating(recipe_title="Liver pie", rater="A", rating="never_again",
               cooked_at=datetime(2026, 3, 1)),
    ]
    plan = [_slot("Mon", "Liver pie", ["liver", "onion"])]
    warnings = validate_plan(plan, profile, ratings=ratings)
    # Fish and veg warnings might fire, but no "never again" warning
    assert not any("never_again" in w.lower() or "never again" in w.lower() for w in warnings)


def test_produce_keywords_basic():
    # Sanity: basic veg are recognised
    assert "broccoli" in PRODUCE_KEYWORDS
    assert "carrot" in PRODUCE_KEYWORDS
    assert "tomato" in PRODUCE_KEYWORDS


def test_dislike_fires_once_per_pair_even_with_multiple_matching_ingredients():
    profile = _profile(household_dislikes=["onion"])
    plan = [_slot("Mon", "Onion soup", ["onion", "spring onion", "broccoli"])]
    warnings = validate_plan(plan, profile, ratings=[])
    dislike_warnings = [w for w in warnings if "household dislike: onion" in w]
    assert len(dislike_warnings) == 1


def test_never_again_match_is_case_insensitive():
    profile = _profile()
    ratings = [
        Rating(recipe_title="liver pie", rater="A", rating="never_again",
               cooked_at=datetime(2026, 3, 1)),
        Rating(recipe_title="Liver Pie", rater="B", rating="never_again",
               cooked_at=datetime(2026, 3, 1)),
    ]
    plan = [_slot("Mon", "LIVER PIE", ["liver", "onion"])]
    warnings = validate_plan(plan, profile, ratings=ratings)
    assert any("never" in w.lower() for w in warnings)


def test_no_repeat_from_last_week_warns():
    last_week_slots = [
        _slot("Mon", "Salmon bowls", ["broccoli", "rice"], "salmon"),
        _slot("Tue", "Chicken curry", ["onion", "tomato"], "chicken"),
        _slot("Wed", "Tofu stir fry", ["pak choi", "rice"], "tofu"),
        _slot("Thu", "Beef chilli", ["onion", "tomato"], "beef"),
        _slot("Fri", "Prawn pasta", ["zucchini", "pasta"], "prawn"),
    ]
    plan_history = [ArchivedPlan(week_of=date(2026, 4, 6), slots=last_week_slots)]

    this_week = [
        _slot("Mon", "Salmon bowls", ["broccoli", "rice"], "salmon"),
        _slot("Tue", "Chicken traybake", ["potato", "carrot"], "chicken"),
        _slot("Wed", "Pork stir fry", ["pak choi", "rice"], "pork"),
        _slot("Thu", "Fish tacos", ["cabbage", "lime"], "fish"),
        _slot("Fri", "Veg pasta", ["zucchini", "pasta"]),
    ]
    warnings = validate_plan(this_week, _profile(), ratings=[], plan_history=plan_history)
    assert any("salmon bowls" in w.lower() and "last week" in w.lower() for w in warnings)


def test_no_repeat_case_insensitive():
    last_week_slots = [
        _slot("Mon", "chicken curry", ["onion", "tomato"], "chicken"),
        _slot("Tue", "Fish pie", ["potato", "carrot"], "fish"),
        _slot("Wed", "Tofu stir fry", ["pak choi"], "tofu"),
        _slot("Thu", "Beef chilli", ["onion", "tomato"], "beef"),
        _slot("Fri", "Prawn pasta", ["zucchini", "pasta"], "prawn"),
    ]
    plan_history = [ArchivedPlan(week_of=date(2026, 4, 6), slots=last_week_slots)]

    this_week = [
        _slot("Mon", "CHICKEN CURRY", ["onion", "tomato"], "chicken"),
        _slot("Tue", "Salmon bowls", ["broccoli", "rice"], "salmon"),
        _slot("Wed", "Pork stir fry", ["pak choi", "rice"], "pork"),
        _slot("Thu", "Fish tacos", ["cabbage", "lime"], "fish"),
        _slot("Fri", "Veg pasta", ["zucchini", "pasta"]),
    ]
    warnings = validate_plan(this_week, _profile(), ratings=[], plan_history=plan_history)
    assert any("chicken curry" in w.lower() and "last week" in w.lower() for w in warnings)


def test_no_repeat_no_history_no_warning():
    plan = [
        _slot("Mon", "Salmon bowls", ["broccoli", "rice"], "salmon"),
        _slot("Tue", "Chicken traybake", ["potato", "carrot"], "chicken"),
        _slot("Wed", "Tofu stir fry", ["pak choi", "rice"], "tofu"),
        _slot("Thu", "Beef chilli", ["onion", "tomato"], "beef"),
        _slot("Fri", "Veg pasta", ["zucchini", "pasta"]),
    ]
    warnings = validate_plan(plan, _profile(), ratings=[], plan_history=[])
    assert not any("last week" in w.lower() for w in warnings)
