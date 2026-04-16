# agents/recipe_finder.py
import json
import re
from datetime import datetime
from typing import Callable
from anthropic import Anthropic
from models import Recipe, Profile
from agents.prompts import RECIPE_FINDER_SYSTEM_PROMPT

MODEL = "claude-sonnet-4-6"


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
) -> list[Recipe]:
    """Run an isolated Claude session with web_search, return structured recipes.

    on_progress(current_step, total_steps, message) is called before each API round.
    """
    client = Anthropic()
    system_prompt = RECIPE_FINDER_SYSTEM_PROMPT.format(
        query=query,
        count=count,
        household_context=_household_context(profile),
    )

    messages: list[dict] = [{
        "role": "user",
        "content": f"Find {count} recipes for: {query}",
    }]

    text_parts: list[str] = []
    for i in range(5):  # at most 5 resumption rounds
        if on_progress:
            on_progress(i + 1, 5, f"Searching for '{query}'\u2026")
        response = client.messages.create(
            model=MODEL,
            max_tokens=4096,
            system=system_prompt,
            tools=[{
                "type": "web_search_20250305",
                "name": "web_search",
                "max_uses": 5,
            }],
            messages=messages,
        )
        # Collect text from this response
        for block in response.content:
            if block.type == "text":
                text_parts.append(block.text)

        # End or pause?
        if response.stop_reason == "pause_turn":
            # Anthropic says: resume by sending the model's content back as-is
            messages.append({"role": "assistant", "content": response.content})
            continue
        if on_progress:
            on_progress(5, 5, "Processing results\u2026")
        break

    raw = "\n".join(text_parts).strip()

    # Pull the JSON array out of the response
    match = re.search(r"\[\s*\{.*?\}\s*\]", raw, re.DOTALL)
    if not match:
        return []
    try:
        parsed = json.loads(match.group(0))
    except json.JSONDecodeError:
        return []

    out: list[Recipe] = []
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
                added_at=now,
            ))
        except (KeyError, ValueError):
            continue
    return out
