# agents/recipe_finder.py
import json
import os
import re
import time
import threading
from datetime import datetime
from typing import Callable
from litellm import completion
from litellm.exceptions import RateLimitError
from models import Recipe, Profile
from agents.prompts import RECIPE_FINDER_SYSTEM_PROMPT

# Use a model with the ':online' suffix so OpenRouter routes web search
# (via Exa) automatically. Override with RECIPE_FINDER_MODEL in .env.
MODEL = os.getenv("RECIPE_FINDER_MODEL", "openrouter/google/gemini-2.5-flash:online")

# Limit concurrent recipe-finder API sessions to avoid rate-limit bursts.
_api_semaphore = threading.Semaphore(1)


def _slugify(title: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")
    return slug[:60] or "untitled"


def _household_context(profile: Profile | None) -> str:
    if profile is None:
        return "(no household profile set yet)"
    dislikes = ", ".join(profile.household_dislikes) or "none"
    rules = "; ".join(profile.dietary_rules) or "none"
    cuisines = ", ".join(profile.preferred_cuisines) or "no preference"
    return (
        f"Household dislikes: {dislikes}\n"
        f"Dietary rules: {rules}\n"
        f"Preferred cuisines: {cuisines}\n"
    )


def find_new_recipes(
    query: str,
    count: int,
    profile: Profile | None,
    on_progress: Callable[[int, int, str], None] | None = None,
    parent_turn_id: str | None = None,
) -> tuple[list[Recipe], dict]:
    """Run an isolated LLM call with web search (via OpenRouter ':online'),
    return (recipes, sub_summary)."""
    import time as _time
    import tracing as _tracing

    sub_id = _tracing.start_turn(f"[subagent] {query}")
    system_prompt = RECIPE_FINDER_SYSTEM_PROMPT.format(
        query=query,
        count=count,
        household_context=_household_context(profile),
    )
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": f"Find {count} recipes for: {query}"},
    ]

    with _api_semaphore:
        if on_progress:
            on_progress(1, 2, f"Searching for '{query}'…")

        response = None
        for attempt in range(4):
            try:
                t0 = _time.monotonic()
                response = completion(
                    model=MODEL,
                    messages=messages,
                    max_tokens=4096,
                )
                _tracing.record_completion(sub_id, response, (_time.monotonic() - t0) * 1000)
                break
            except RateLimitError:
                wait = 2 ** attempt * 15
                if on_progress:
                    on_progress(1, 2, f"Rate limited, retrying in {wait}s…")
                time.sleep(wait)

        if on_progress:
            on_progress(2, 2, "Processing results…")

    if response is None:
        _tracing.end_turn(sub_id, "(no response)", messages)
        return ([], {"sub_turn_id": sub_id, "recipes_found": 0, "model": MODEL})

    raw = (response.choices[0].message.content or "").strip()

    out: list[Recipe] = []
    match = re.search(r"\[\s*\{.*?\}\s*\]", raw, re.DOTALL)
    if match:
        try:
            parsed = json.loads(match.group(0))
        except json.JSONDecodeError:
            parsed = []
        now = datetime.now()
        for item in parsed:
            try:
                out.append(Recipe(
                    id=_slugify(item.get("title", "")),
                    title=item["title"],
                    cuisine=item.get("cuisine", "unknown"),
                    main_protein=item.get("main_protein", "unknown"),
                    key_ingredients=item.get("key_ingredients", []),
                    tags=item.get("tags", []),
                    cook_time_min=int(item.get("cook_time_min", 30)),
                    source_url=item.get("source_url"),
                    source="web",
                    added_at=now,
                ))
            except (KeyError, ValueError):
                continue

    final_messages = messages + [{"role": "assistant", "content": raw}]
    _tracing.end_turn(sub_id, raw[:500], final_messages)

    sub_summary = {
        "sub_turn_id": sub_id,
        "model": MODEL,
        "recipes_found": len(out),
    }
    if parent_turn_id:
        _tracing.attach_subagent(parent_turn_id, sub_summary)
    return (out, sub_summary)
