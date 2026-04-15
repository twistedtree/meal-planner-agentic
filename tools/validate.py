from models import MealPlanSlot, Profile, Rating

FISH_KEYWORDS = {
    "salmon", "tuna", "cod", "haddock", "trout", "mackerel", "sardine",
    "anchovy", "seabass", "sea bass", "tilapia", "pollock", "fish",
    "prawn", "shrimp", "squid", "calamari", "octopus", "mussel", "clam",
    "oyster", "scallop", "crab", "lobster",
}

PRODUCE_KEYWORDS = {
    # leafy + cruciferous
    "spinach", "kale", "lettuce", "cabbage", "pak choi", "bok choy",
    "broccoli", "cauliflower", "brussels sprout", "chard", "rocket", "arugula",
    # roots
    "carrot", "potato", "sweet potato", "beetroot", "beet", "parsnip", "turnip",
    "radish", "onion", "leek", "shallot", "garlic", "ginger",
    # fruiting
    "tomato", "cucumber", "zucchini", "courgette", "pepper", "capsicum",
    "eggplant", "aubergine", "pumpkin", "squash", "avocado",
    # pods / beans
    "green bean", "snap pea", "snow pea", "pea", "edamame", "asparagus",
    "okra", "corn", "sweetcorn",
    # alliums / herbs that count
    "spring onion", "scallion", "mushroom",
    # fruit that counts in savoury dishes
    "apple", "pear", "lemon", "lime", "orange",
}


def _matches_any(ingredients: list[str], keywords: set[str]) -> bool:
    lowered = [i.lower() for i in ingredients]
    for ing in lowered:
        for kw in keywords:
            if kw in ing:
                return True
    return False


def validate_plan(
    plan: list[MealPlanSlot],
    profile: Profile,
    ratings: list[Rating],
) -> list[str]:
    """Return a list of human-readable warnings. Empty list = all good."""
    warnings: list[str] = []

    # Rule 1: ≥1 fish meal per week
    if plan and not any(_matches_any(s.key_ingredients, FISH_KEYWORDS) for s in plan):
        warnings.append("No fish this week — at least 1 fish meal is expected.")

    # Rule 2: every meal has a vegetable
    for slot in plan:
        if not _matches_any(slot.key_ingredients, PRODUCE_KEYWORDS):
            warnings.append(
                f"{slot.day} ({slot.recipe_title}) has no vegetable listed."
            )

    # Rule 3: no household dislike
    dislikes = {d.lower() for d in profile.household_dislikes}
    for slot in plan:
        for ing in slot.key_ingredients:
            for d in dislikes:
                if d in ing.lower():
                    warnings.append(
                        f"{slot.day} ({slot.recipe_title}) violates household dislike: {d}"
                    )
                    break

    # Rule 4: no recipe both adults rated never_again
    adult_names = {m.name for m in profile.members if m.is_adult}
    never_again_by_recipe: dict[str, set[str]] = {}
    for r in ratings:
        if r.rating == "never_again" and r.rater in adult_names:
            never_again_by_recipe.setdefault(r.recipe_title, set()).add(r.rater)
    mutual_never = {
        title for title, raters in never_again_by_recipe.items()
        if raters >= adult_names and len(adult_names) > 0
    }
    for slot in plan:
        if slot.recipe_title in mutual_never:
            warnings.append(
                f"{slot.day} ({slot.recipe_title}) was rated never_again by both adults."
            )

    return warnings
