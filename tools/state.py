# tools/state.py
from datetime import datetime
from models import State, MealPlanSlot, Rating
from storage import load_json, save_json


def _now() -> datetime:
    return datetime.now()


def read_state() -> State:
    s = load_json("state.json", State)
    if s is None:
        s = State(meal_plan=[], pantry=[], ratings=[], last_updated=_now())
        save_json("state.json", s)
    return s


def update_plan(slots: list[dict]) -> State:
    """Replace meal_plan wholesale with the given slots."""
    s = read_state()
    s.meal_plan = [MealPlanSlot.model_validate(slot) for slot in slots]
    s.last_updated = _now()
    save_json("state.json", s)
    return s


def update_pantry(add: list[str] | None = None, remove: list[str] | None = None) -> State:
    """Apply a diff to the pantry. Items are normalised to lowercase, stripped."""
    s = read_state()
    current = {p.lower().strip() for p in s.pantry}
    for item in (add or []):
        current.add(item.lower().strip())
    for item in (remove or []):
        current.discard(item.lower().strip())
    s.pantry = sorted(current)
    s.last_updated = _now()
    save_json("state.json", s)
    return s


def record_rating(recipe_title: str, rater: str, rating: str,
                  cooked_at: str | None = None) -> State:
    """Append a rating. cooked_at is an ISO-8601 string or defaults to now."""
    s = read_state()
    ts = datetime.fromisoformat(cooked_at) if cooked_at else _now()
    s.ratings.append(Rating(
        recipe_title=recipe_title, rater=rater, rating=rating, cooked_at=ts,
    ))
    s.last_updated = _now()
    save_json("state.json", s)
    return s


_SNAPSHOT: State | None = None


def snapshot_for_undo() -> None:
    """Capture current state for a one-step undo. Called before any mutation."""
    global _SNAPSHOT
    _SNAPSHOT = read_state().model_copy(deep=True)


def restore_snapshot() -> State | None:
    """Restore the most recent snapshot. Returns the restored state or None."""
    global _SNAPSHOT
    if _SNAPSHOT is None:
        return None
    save_json("state.json", _SNAPSHOT)
    restored = _SNAPSHOT
    _SNAPSHOT = None
    return restored
