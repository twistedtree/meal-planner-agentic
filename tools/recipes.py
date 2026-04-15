from typing import Any
from models import Recipe


SUMMARY_FIELDS = ("id", "title", "cuisine", "main_protein", "avg_rating",
                  "times_cooked", "tags", "cook_time_min")


def recipe_summary(r: Recipe) -> dict[str, Any]:
    """Compact representation — cheap to list even with hundreds of recipes."""
    return {
        "id": r.id,
        "title": r.title,
        "cuisine": r.cuisine,
        "main_protein": r.main_protein,
        "avg_rating": r.avg_rating,
        "times_cooked": r.times_cooked,
        "tags": r.tags,
        "cook_time_min": r.cook_time_min,
    }


def list_recipes(
    recipes: list[Recipe],
    filters: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Return compact summaries, optionally filtered by exact-match fields."""
    filters = filters or {}
    out = []
    for r in recipes:
        if all(getattr(r, k, None) == v for k, v in filters.items()):
            out.append(recipe_summary(r))
    return out


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
    candidates = [
        r for r in recipes
        if all(getattr(r, k, None) == v for k, v in filters.items())
    ]
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
    # Higher score first, then higher rating, then more times cooked
    scored.sort(key=lambda x: (-x[0], -x[1], -x[2]))
    return [recipe_summary(r) for _, _, _, r in scored[:top_k]]
