# tools/state.py
from datetime import datetime, date
from models import State, MealPlanSlot, Rating, ArchivedPlan, PantryItem
from storage import load_json, save_json, STATE_DIR


def _now() -> datetime:
    return datetime.now()


def read_state() -> State:
    s = load_json("state.json", State)
    if s is None:
        s = State(meal_plan=[], pantry=[], ratings=[], last_updated=_now())
        save_json("state.json", s)
    return s


def update_plan(slots: list[dict], week_of: date | None = None) -> State:
    """Replace meal_plan wholesale. Archive the previous plan to plan_history
    only when crossing into a different week — same-week resaves overwrite in
    place so validate_plan Rule 5 does not flag earlier drafts as "last week"
    (issue #1).
    """
    s = read_state()
    if s.meal_plan and s.week_of is not None and s.week_of != week_of:
        s.plan_history.append(ArchivedPlan(week_of=s.week_of, slots=s.meal_plan))
        s.plan_history = s.plan_history[-4:]
    s.meal_plan = [MealPlanSlot.model_validate(slot) for slot in slots]
    s.week_of = week_of
    s.last_updated = _now()
    save_json("state.json", s)
    return s


def update_pantry(
    add: list[str | dict] | None = None,
    remove: list[str] | None = None,
) -> State:
    """Apply a diff to the pantry.

    `add` accepts bare strings or {name, quantity?, expiry_at?} dicts.
    Dedupe key is name.lower().strip(). On collision, non-None quantity /
    expiry_at from the new entry overwrite the existing values; bare-name
    re-adds preserve existing quantity / expiry_at.
    `remove` is a list of names; case-insensitive exact match.
    """
    s = read_state()
    by_name: dict[str, PantryItem] = {
        p.name.lower().strip(): p for p in s.pantry
    }

    for entry in (add or []):
        if isinstance(entry, str):
            new = PantryItem(name=entry.strip())
        else:
            new = PantryItem.model_validate(entry)
        key = new.name.lower().strip()
        if key in by_name:
            existing = by_name[key]
            merged = existing.model_copy(update={
                "quantity": new.quantity if new.quantity is not None else existing.quantity,
                "expiry_at": new.expiry_at if new.expiry_at is not None else existing.expiry_at,
            })
            by_name[key] = merged
        else:
            by_name[key] = new

    for name in (remove or []):
        by_name.pop(name.lower().strip(), None)

    s.pantry = sorted(by_name.values(), key=lambda p: p.name.lower())
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


def snapshot_for_undo() -> None:
    """Capture current state for a one-step undo. Called at turn start."""
    current = read_state()
    snapshot_path = STATE_DIR / ".snapshot.json"
    snapshot_path.parent.mkdir(parents=True, exist_ok=True)
    snapshot_path.write_text(current.model_dump_json(indent=2), encoding="utf-8")


def restore_snapshot() -> State | None:
    """Restore the most recent snapshot. Returns the restored state or None."""
    snapshot_path = STATE_DIR / ".snapshot.json"
    if not snapshot_path.exists():
        return None
    restored = State.model_validate_json(snapshot_path.read_text(encoding="utf-8"))
    save_json("state.json", restored)
    snapshot_path.unlink()
    return restored
