import threading
from typing import Any
from models import Recipe

_recipes_lock = threading.Lock()


SUMMARY_FIELDS = ("id", "title", "cuisine", "main_protein", "avg_rating",
                  "times_cooked", "tags", "cook_time_min")

FILTERABLE_FIELDS = frozenset({
    "id", "cuisine", "main_protein", "cook_time_min", "times_cooked"
})


def recipe_summary(r: Recipe) -> dict[str, Any]:
    """Compact representation — cheap to list even with hundreds of recipes."""
    return {k: getattr(r, k) for k in SUMMARY_FIELDS}


def _apply_filters(r: Recipe, filters: dict[str, Any]) -> bool:
    """Exact-match filter check. Raises ValueError for unknown keys."""
    unknown = set(filters) - FILTERABLE_FIELDS
    if unknown:
        raise ValueError(f"Unknown filter fields: {sorted(unknown)}")
    return all(getattr(r, k, None) == v for k, v in filters.items())


def list_recipes(
    recipes: list[Recipe],
    filters: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Return compact summaries, optionally filtered by exact-match fields."""
    filters = filters or {}
    return [recipe_summary(r) for r in recipes if _apply_filters(r, filters)]


def _score_match(r: Recipe, query: str) -> int:
    """Count how many query tokens appear in searchable fields."""
    q_tokens = [t for t in query.lower().split() if t]
    if not q_tokens:
        return 0
    haystack = " ".join([
        r.title.lower(),
        r.cuisine.lower(),
        r.main_protein.lower(),
        " ".join(t.lower() for t in r.tags),
        " ".join(i.lower() for i in r.key_ingredients),
    ])
    return sum(1 for t in q_tokens if t in haystack)


def search_recipes(
    recipes: list[Recipe],
    query: str,
    filters: dict[str, Any] | None = None,
    top_k: int = 20,
) -> list[dict[str, Any]]:
    """Match query against title/tags/ingredients/cuisine. Rank by (match count,
    avg_rating desc, times_cooked desc). Apply exact-match filters first."""
    filters = filters or {}
    candidates = [r for r in recipes if _apply_filters(r, filters)]
    scored: list[tuple[int, float, int, Recipe]] = []
    for r in candidates:
        s = _score_match(r, query)
        if s == 0 and query.strip():
            continue
        scored.append((
            s,
            r.avg_rating if r.avg_rating is not None else -1.0,
            r.times_cooked,
            r,
        ))
    scored.sort(key=lambda x: (-x[0], -x[1], -x[2]))
    return [recipe_summary(r) for _, _, _, r in scored[:top_k]]


# --- Persistence + subagent wiring ---

from datetime import datetime
from storage import load_json_list, save_json_list
from models import Profile


def load_all_recipes() -> list[Recipe]:
    """Load every saved recipe from recipes.json (returns [] if missing)."""
    return load_json_list("recipes.json", Recipe)


def save_all_recipes(recipes: list[Recipe]) -> None:
    with _recipes_lock:
        save_json_list("recipes.json", recipes)


def get_recipe(recipe_id: str) -> dict | None:
    """Return the full recipe as a dict, or None if not found."""
    for r in load_all_recipes():
        if r.id == recipe_id:
            return r.model_dump(mode="json")
    return None


def append_recipes(new: list[Recipe]) -> list[Recipe]:
    """Append new recipes, skipping duplicates by id. Returns the newly added."""
    with _recipes_lock:
        existing = load_all_recipes()
        existing_ids = {r.id for r in existing}
        added: list[Recipe] = []
        for r in new:
            if r.id in existing_ids:
                continue
            existing.append(r)
            added.append(r)
            existing_ids.add(r.id)
        save_json_list("recipes.json", existing)
    return added


def find_new_recipes_tool(query: str, count: int, profile: Profile | None) -> list[dict]:
    """Tool-facing: spawn subagent, append results to recipes.json, return summaries."""
    from agents.recipe_finder import find_new_recipes  # local import avoids cycle
    found = find_new_recipes(query, count, profile)
    added = append_recipes(found)
    return [recipe_summary(r) for r in added]
