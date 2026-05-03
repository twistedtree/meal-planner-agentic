# agents/orchestrator.py
import json
import os
import time
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from litellm import completion
import tracing
from agents.prompts import ORCHESTRATOR_SYSTEM_PROMPT
from tools.profile import read_profile, update_profile
from tools.state import (
    read_state, update_plan, update_pantry, record_rating,
    snapshot_for_undo, restore_snapshot,
)
import tools.recipes as _recipes_mod
from tools.recipes import (
    load_all_recipes, list_recipes, search_recipes, get_recipe,
    find_new_recipes_tool, update_recipe, delete_recipe,
)
from tools.cookidoo import (
    list_cookidoo_collections, get_cookidoo_collection, fetch_cookidoo_recipe,
)
from tools.validate import validate_plan

MODEL = os.getenv("ORCHESTRATOR_MODEL", "openrouter/anthropic/claude-sonnet-4.5")
MAX_TOOL_ITERATIONS = 15

# --- Background job registry ---
_bg_jobs: dict[str, dict] = {}
_bg_lock = threading.Lock()


def get_bg_jobs() -> dict[str, dict]:
    with _bg_lock:
        return dict(_bg_jobs)


def _run_recipe_search_bg(job_id: str, query: str, count: int, profile):
    def _on_progress(cur, total, msg):
        with _bg_lock:
            _bg_jobs[job_id]["progress"] = (cur, total, msg)

    try:
        result = find_new_recipes_tool(query, count, profile, on_progress=_on_progress)
        with _bg_lock:
            _bg_jobs[job_id]["status"] = "done"
            _bg_jobs[job_id]["result"] = result
    except Exception as e:
        with _bg_lock:
            _bg_jobs[job_id]["status"] = "error"
            _bg_jobs[job_id]["result"] = str(e)


# --- Tool schema (OpenAI / OpenRouter format) ---

def _tool(name: str, description: str, parameters: dict) -> dict:
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": description,
            "parameters": parameters,
        },
    }


TOOL_DEFINITIONS = [
    _tool("read_profile",
          "Read the household profile (members, dislikes, dietary rules).",
          {"type": "object", "properties": {}, "required": []}),
    _tool("update_profile",
          "Create or merge-update the household profile. Pass any subset of fields.",
          {
              "type": "object",
              "properties": {
                  "household_size": {"type": "integer"},
                  "members": {
                      "type": "array",
                      "items": {
                          "type": "object",
                          "properties": {
                              "name": {"type": "string"},
                              "is_adult": {"type": "boolean"},
                              "dislikes": {"type": "array", "items": {"type": "string"}},
                          },
                          "required": ["name", "is_adult"],
                      },
                  },
                  "household_dislikes": {"type": "array", "items": {"type": "string"}},
                  "dietary_rules": {"type": "array", "items": {"type": "string"}},
                  "preferred_cuisines": {"type": "array", "items": {"type": "string"}},
                  "notes": {"type": "string"},
              },
              "required": [],
          }),
    _tool("read_state",
          "Read the current meal plan, pantry, and ratings.",
          {"type": "object", "properties": {}, "required": []}),
    _tool("update_plan",
          "Replace the meal_plan wholesale. Provide 5 slots (Mon-Fri). Always include week_of (the Monday of the planned week, ISO format YYYY-MM-DD).",
          {
              "type": "object",
              "properties": {
                  "week_of": {"type": "string", "description": "Monday of the planned week (YYYY-MM-DD)"},
                  "slots": {
                      "type": "array",
                      "items": {
                          "type": "object",
                          "properties": {
                              "day": {"type": "string", "enum": ["Mon", "Tue", "Wed", "Thu", "Fri"]},
                              "recipe_title": {"type": "string"},
                              "recipe_id": {"type": ["string", "null"]},
                              "main_protein": {"type": "string"},
                              "key_ingredients": {"type": "array", "items": {"type": "string"}},
                              "rationale": {"type": "string"},
                          },
                          "required": ["day", "recipe_title", "main_protein", "key_ingredients", "rationale"],
                      },
                  },
              },
              "required": ["slots", "week_of"],
          }),
    _tool("update_pantry",
          "Add/remove perishables in the pantry. In/out only (no quantities).",
          {
              "type": "object",
              "properties": {
                  "add": {"type": "array", "items": {"type": "string"}},
                  "remove": {"type": "array", "items": {"type": "string"}},
              },
              "required": [],
          }),
    _tool("record_rating",
          "Record a rating for a cooked meal.",
          {
              "type": "object",
              "properties": {
                  "recipe_title": {"type": "string"},
                  "rater": {"type": "string"},
                  "rating": {"type": "string",
                             "enum": ["again_soon", "worth_repeating", "meh", "never_again"]},
              },
              "required": ["recipe_title", "rater", "rating"],
          }),
    _tool("list_recipes",
          "List saved recipes as compact summaries. Optional exact-match filters (cuisine, main_protein, cook_time_min, times_cooked, id).",
          {
              "type": "object",
              "properties": {"filters": {"type": "object"}},
              "required": [],
          }),
    _tool("get_recipe",
          "Fetch full details for one recipe by id.",
          {
              "type": "object",
              "properties": {"id": {"type": "string"}},
              "required": ["id"],
          }),
    _tool("search_recipes",
          "Keyword search over saved recipes. Ranks by match count, then rating, then times_cooked.",
          {
              "type": "object",
              "properties": {
                  "query": {"type": "string"},
                  "filters": {"type": "object"},
                  "top_k": {"type": "integer", "default": 20},
              },
              "required": ["query"],
          }),
    _tool("find_new_recipes",
          "Spawn a web-search subagent to discover new recipes. Use ONLY when the user explicitly asks to find/discover or update the recipe database.",
          {
              "type": "object",
              "properties": {
                  "query": {"type": "string"},
                  "count": {"type": "integer", "default": 3},
              },
              "required": ["query"],
          }),
    _tool("update_recipe",
          "Edit fields on a saved recipe. Pass any subset of fields. id is immutable.",
          {
              "type": "object",
              "properties": {
                  "recipe_id": {"type": "string"},
                  "fields": {
                      "type": "object",
                      "properties": {
                          "title":           {"type": "string"},
                          "cuisine":         {"type": "string"},
                          "main_protein":    {"type": "string"},
                          "key_ingredients": {"type": "array", "items": {"type": "string"}},
                          "tags":            {"type": "array", "items": {"type": "string"}},
                          "cook_time_min":   {"type": "integer"},
                          "source_url":      {"type": ["string", "null"]},
                          "source":          {"type": "string"},
                          "notes":           {"type": "string"},
                      },
                      "additionalProperties": False,
                  },
              },
              "required": ["recipe_id", "fields"],
          }),
    _tool("delete_recipe",
          "Remove a saved recipe by id.",
          {"type": "object",
           "properties": {"recipe_id": {"type": "string"}},
           "required": ["recipe_id"]}),
    _tool("check_search_status",
          "Check the status of a background recipe search. Returns status ('running', 'done', 'error') and results if done.",
          {
              "type": "object",
              "properties": {"job_id": {"type": "string"}},
              "required": ["job_id"],
          }),
    _tool("list_cookidoo_collections",
          "List the household's Cookidoo (Thermomix) managed collections. Use when the user asks about their Cookidoo library or Thermomix recipes. Returns [{id, name, description, recipe_count}].",
          {"type": "object", "properties": {}, "required": []}),
    _tool("get_cookidoo_collection",
          "Fetch the recipes inside one Cookidoo collection. Returns [{id, name, total_time_min, chapter}]. The recipe id (e.g. 'r471786') is what to pass to fetch_cookidoo_recipe.",
          {
              "type": "object",
              "properties": {"col_id": {"type": "string"}},
              "required": ["col_id"],
          }),
    _tool("fetch_cookidoo_recipe",
          "Fetch full authenticated details for one Cookidoo recipe (ingredients, time, url) and save it to the recipe library. The id looks like 'r471786' and can come from get_cookidoo_collection or from a cookidoo.com.au URL path segment.",
          {
              "type": "object",
              "properties": {"recipe_id": {"type": "string"}},
              "required": ["recipe_id"],
          }),
    _tool("validate_plan",
          "Check the current saved plan against hard rules. Returns a list of warnings (empty = OK).",
          {"type": "object", "properties": {}, "required": []}),
    _tool("undo",
          "Restore the state snapshot taken at the start of this turn.",
          {"type": "object", "properties": {}, "required": []}),
]


# --- Tool dispatcher ---

MAX_TOOL_RESULT_CHARS = 4000


def _dispatch(name: str, args: dict, turn_id: str | None = None) -> str:
    try:
        if name == "read_profile":
            p = read_profile()
            return json.dumps(p.model_dump(mode="json") if p else None)
        if name == "update_profile":
            return json.dumps(update_profile(args).model_dump(mode="json"))
        if name == "read_state":
            return json.dumps(read_state().model_dump(mode="json"))
        if name == "update_plan":
            from datetime import date as date_type
            week_of_str = args.get("week_of")
            week_of = date_type.fromisoformat(week_of_str) if week_of_str else None
            state = update_plan(args["slots"], week_of=week_of)
            profile = read_profile()
            warnings = []
            if profile:
                warnings = validate_plan(
                    state.meal_plan, profile, state.ratings,
                    plan_history=state.plan_history,
                )
            return json.dumps({"ok": True, "warnings": warnings})
        if name == "update_pantry":
            return json.dumps(update_pantry(
                add=args.get("add", []), remove=args.get("remove", [])
            ).model_dump(mode="json"))
        if name == "record_rating":
            return json.dumps(record_rating(
                recipe_title=args["recipe_title"],
                rater=args["rater"],
                rating=args["rating"],
            ).model_dump(mode="json"))
        if name == "list_recipes":
            return json.dumps(list_recipes(_recipes_mod.load_all_recipes(), filters=args.get("filters")))
        if name == "get_recipe":
            return json.dumps(get_recipe(args["id"]))
        if name == "search_recipes":
            return json.dumps(search_recipes(
                _recipes_mod.load_all_recipes(),
                query=args["query"],
                filters=args.get("filters"),
                top_k=args.get("top_k", 20),
            ))
        if name == "find_new_recipes":
            result = find_new_recipes_tool(
                query=args["query"],
                count=args.get("count", 3),
                profile=read_profile(),
                parent_turn_id=turn_id,
            )
            return json.dumps(result)
        if name == "update_recipe":
            result = update_recipe(args["recipe_id"], args.get("fields", {}))
            return json.dumps(result)
        if name == "delete_recipe":
            ok = delete_recipe(args["recipe_id"])
            return json.dumps({"ok": ok})
        if name == "check_search_status":
            job_id = args["job_id"]
            with _bg_lock:
                job = _bg_jobs.get(job_id)
            if job is None:
                return json.dumps({"error": f"Unknown job: {job_id}"})
            return json.dumps({
                "status": job["status"],
                "progress": job.get("progress"),
                "result": job["result"] if job["status"] != "running" else None,
            })
        if name == "list_cookidoo_collections":
            return json.dumps(list_cookidoo_collections())
        if name == "get_cookidoo_collection":
            return json.dumps(get_cookidoo_collection(args["col_id"]))
        if name == "fetch_cookidoo_recipe":
            return json.dumps(fetch_cookidoo_recipe(args["recipe_id"]))
        if name == "validate_plan":
            state = read_state()
            profile = read_profile()
            if profile is None:
                return json.dumps(["No profile set yet — skipping validation."])
            return json.dumps(validate_plan(
                state.meal_plan, profile, state.ratings,
                plan_history=state.plan_history,
            ))
        if name == "undo":
            restored = restore_snapshot()
            return json.dumps({"ok": restored is not None})
        return json.dumps({"error": f"unknown tool: {name}"})
    except Exception as exc:
        return json.dumps({"error": str(exc)})


# --- Per-turn system prompt assembly ---

def _profile_summary() -> str:
    p = read_profile()
    if p is None:
        return "(empty — no profile yet; onboard the user before planning)"
    members = ", ".join(f"{m.name}{'*' if m.is_adult else ''}" for m in p.members)
    return (
        f"Size: {p.household_size}; Members: {members} (* = adult); "
        f"Household dislikes: {p.household_dislikes or 'none'}; "
        f"Dietary rules: {p.dietary_rules or 'none'}; "
        f"Preferred cuisines: {p.preferred_cuisines or 'none'}; "
        f"Notes: {p.notes or 'none'}"
    )


def _state_summary() -> str:
    s = read_state()
    plan_line = (
        " | ".join(f"{slot.day}: {slot.recipe_title}" for slot in s.meal_plan)
        if s.meal_plan else "(no plan set)"
    )
    week_label = f"Week of {s.week_of.isoformat()}" if s.week_of else "(no week set)"
    pantry = ", ".join(s.pantry) if s.pantry else "(empty)"
    n_ratings = len(s.ratings)

    parts = [
        f"Current plan ({week_label}): {plan_line}",
        f"Pantry: {pantry}",
        f"Ratings recorded: {n_ratings}",
    ]

    if s.plan_history:
        last = s.plan_history[-1]
        last_titles = ", ".join(slot.recipe_title for slot in last.slots)
        parts.append(f"Last week ({last.week_of.isoformat()}): {last_titles}")

    return "\n".join(parts)


def _build_system_prompt() -> str:
    return ORCHESTRATOR_SYSTEM_PROMPT.format(
        profile_summary=_profile_summary(),
        state_summary=_state_summary(),
        today=datetime.now().strftime("%A %Y-%m-%d"),
    )


# --- History management ---

MAX_HISTORY_TURNS = 20


def _trim_history(history: list[dict]) -> list[dict]:
    """Keep only the last MAX_HISTORY_TURNS messages.

    Tool results accumulate large JSON blobs, and the system prompt already
    re-injects current state each turn. After trimming, drop any leading
    orphaned tool messages (a `tool` role with no preceding `assistant`
    tool_calls would error out the API).
    """
    if len(history) <= MAX_HISTORY_TURNS:
        return history
    trimmed = history[-MAX_HISTORY_TURNS:]
    while trimmed and trimmed[0].get("role") == "tool":
        trimmed = trimmed[1:]
    return trimmed


# --- Public API ---

def _run_one(tc, turn_id: str) -> dict:
    try:
        args = json.loads(tc.function.arguments or "{}")
    except json.JSONDecodeError:
        args = {}
    t0 = time.monotonic()
    result = _dispatch(tc.function.name, args, turn_id)
    elapsed_ms = (time.monotonic() - t0) * 1000
    tracing.record_tool_call(turn_id, tc.function.name, args, len(result), elapsed_ms)
    if len(result) > MAX_TOOL_RESULT_CHARS:
        result = result[:MAX_TOOL_RESULT_CHARS] + " ...(truncated)"
    return {
        "role": "tool",
        "tool_call_id": tc.id,
        "name": tc.function.name,
        "content": result,
    }


def run_turn(user_message: str, history: list[dict]) -> tuple[str, list[dict]]:
    """Run one conversational turn. Returns (assistant text, updated history).

    history is a list of OpenAI-shape messages: {role, content, [tool_calls], [tool_call_id]}.
    """
    snapshot_for_undo()
    history = _trim_history(history)
    turn_id = tracing.start_turn(user_message)
    messages = (
        [{"role": "system", "content": _build_system_prompt()}]
        + history
        + [{"role": "user", "content": user_message}]
    )

    try:
        for iteration in range(MAX_TOOL_ITERATIONS):
            t0 = time.monotonic()
            response = completion(
                model=MODEL,
                messages=messages,
                tools=TOOL_DEFINITIONS,
                max_tokens=4096,
            )
            tracing.record_completion(turn_id, response, (time.monotonic() - t0) * 1000)

            choice = response.choices[0]
            msg = choice.message
            tool_calls = getattr(msg, "tool_calls", None) or []

            assistant_entry = {
                "role": "assistant",
                "content": msg.content or "",
            }
            if tool_calls:
                assistant_entry["tool_calls"] = [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {"name": tc.function.name, "arguments": tc.function.arguments},
                    }
                    for tc in tool_calls
                ]
            messages.append(assistant_entry)

            if not tool_calls:
                final_text = (msg.content or "").strip()
                tracing.end_turn(turn_id, final_text, messages)
                return (final_text, messages[1:])

            if iteration > 0:
                time.sleep(2)

            if len(tool_calls) == 1:
                messages.append(_run_one(tool_calls[0], turn_id))
            else:
                results: list[dict] = []
                with ThreadPoolExecutor(max_workers=len(tool_calls)) as pool:
                    futures = {pool.submit(_run_one, tc, turn_id): tc for tc in tool_calls}
                    for future in as_completed(futures):
                        results.append(future.result())
                id_order = {tc.id: i for i, tc in enumerate(tool_calls)}
                results.sort(key=lambda r: id_order[r["tool_call_id"]])
                messages.extend(results)

        final_text = "(tool loop limit hit — simplify your request)"
        tracing.end_turn(turn_id, final_text, messages)
        return (final_text, messages[1:])
    except Exception:
        # Make sure the trace is closed even on a hard failure.
        try:
            tracing.end_turn(turn_id, "(error)", messages)
        except Exception:
            pass
        raise
