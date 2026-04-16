# agents/orchestrator.py
import json
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from anthropic import Anthropic
from agents.prompts import ORCHESTRATOR_SYSTEM_PROMPT
from tools.profile import read_profile, update_profile
from tools.state import (
    read_state, update_plan, update_pantry, record_rating,
    snapshot_for_undo, restore_snapshot,
)
import tools.recipes as _recipes_mod
from tools.recipes import (
    load_all_recipes, list_recipes, search_recipes, get_recipe,
    find_new_recipes_tool,
)
from tools.validate import validate_plan

MODEL = "claude-sonnet-4-6"
MAX_TOOL_ITERATIONS = 15

# --- Background job registry ---
# Shared across turns within the same Streamlit process.
_bg_jobs: dict[str, dict] = {}
_bg_lock = threading.Lock()


def get_bg_jobs() -> dict[str, dict]:
    """Return a shallow copy of background jobs (for UI polling)."""
    with _bg_lock:
        return dict(_bg_jobs)


def _run_recipe_search_bg(job_id: str, query: str, count: int, profile):
    """Target for background thread — runs find_new_recipes_tool and stores result."""
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


# --- Tool schema (what Claude sees) ---

TOOL_DEFINITIONS = [
    {
        "name": "read_profile",
        "description": "Read the household profile (members, dislikes, dietary rules).",
        "input_schema": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "update_profile",
        "description": "Create or merge-update the household profile. Pass any subset of fields.",
        "input_schema": {
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
        },
    },
    {
        "name": "read_state",
        "description": "Read the current meal plan, pantry, and ratings.",
        "input_schema": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "update_plan",
        "description": "Replace the meal_plan wholesale. Provide 5 slots (Mon-Fri). Always include week_of (the Monday of the planned week, ISO format YYYY-MM-DD).",
        "input_schema": {
            "type": "object",
            "properties": {
                "week_of": {"type": "string", "description": "Monday of the planned week (YYYY-MM-DD)"},
                "slots": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "day": {"type": "string", "enum": ["Mon","Tue","Wed","Thu","Fri"]},
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
        },
    },
    {
        "name": "update_pantry",
        "description": "Add/remove perishables in the pantry. In/out only (no quantities).",
        "input_schema": {
            "type": "object",
            "properties": {
                "add": {"type": "array", "items": {"type": "string"}},
                "remove": {"type": "array", "items": {"type": "string"}},
            },
            "required": [],
        },
    },
    {
        "name": "record_rating",
        "description": "Record a rating for a cooked meal.",
        "input_schema": {
            "type": "object",
            "properties": {
                "recipe_title": {"type": "string"},
                "rater": {"type": "string"},
                "rating": {"type": "string",
                           "enum": ["again_soon", "worth_repeating", "meh", "never_again"]},
            },
            "required": ["recipe_title", "rater", "rating"],
        },
    },
    {
        "name": "list_recipes",
        "description": "List saved recipes as compact summaries. Optional exact-match filters (cuisine, main_protein, cook_time_min, times_cooked, id).",
        "input_schema": {
            "type": "object",
            "properties": {
                "filters": {"type": "object"},
            },
            "required": [],
        },
    },
    {
        "name": "get_recipe",
        "description": "Fetch full details for one recipe by id.",
        "input_schema": {
            "type": "object",
            "properties": {"id": {"type": "string"}},
            "required": ["id"],
        },
    },
    {
        "name": "search_recipes",
        "description": "Keyword search over saved recipes. Ranks by match count, then rating, then times_cooked.",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "filters": {"type": "object"},
                "top_k": {"type": "integer", "default": 20},
            },
            "required": ["query"],
        },
    },
    {
        "name": "find_new_recipes",
        "description": "Spawn a web-search subagent to discover new recipes. Use ONLY when the user explicitly asks to find/discover or update the recipe database.",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "count": {"type": "integer", "default": 3},
            },
            "required": ["query"],
        },
    },
    {
        "name": "check_search_status",
        "description": "Check the status of a background recipe search. Returns status ('running', 'done', 'error') and results if done.",
        "input_schema": {
            "type": "object",
            "properties": {"job_id": {"type": "string"}},
            "required": ["job_id"],
        },
    },
    {
        "name": "validate_plan",
        "description": "Check the current saved plan against hard rules. Returns a list of warnings (empty = OK).",
        "input_schema": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "undo",
        "description": "Restore the state snapshot taken at the start of this turn.",
        "input_schema": {"type": "object", "properties": {}, "required": []},
    },
]


# --- Tool dispatcher ---

def _dispatch(name: str, args: dict) -> str:
    """Run a tool and return a JSON-serialisable string result for the agent."""
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
            return json.dumps(update_plan(args["slots"], week_of=week_of).model_dump(mode="json"))
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
            job_id = f"search-{datetime.now().timestamp()}"
            with _bg_lock:
                _bg_jobs[job_id] = {"status": "running", "result": None, "progress": (0, 5, "Starting\u2026")}
            thread = threading.Thread(
                target=_run_recipe_search_bg,
                args=(job_id, args["query"], args.get("count", 3), read_profile()),
                daemon=True,
            )
            thread.start()
            return json.dumps({
                "status": "started",
                "job_id": job_id,
                "message": f"Recipe search for '{args['query']}' running in background. "
                           f"Use check_search_status to poll, or continue with other tasks.",
            })
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
    except Exception as exc:  # surface errors back to the agent, don't crash the session
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


# --- Public API ---

def run_turn(user_message: str, history: list[dict]) -> tuple[str, list[dict]]:
    """Run one conversational turn. Returns (assistant text, updated history).

    history is a list of {role, content} dicts in the Anthropic Messages API shape.
    """
    snapshot_for_undo()  # capture state at turn entry — undo restores to here
    client = Anthropic()
    messages = history + [{"role": "user", "content": user_message}]
    system = _build_system_prompt()

    for _ in range(MAX_TOOL_ITERATIONS):
        response = client.messages.create(
            model=MODEL,
            max_tokens=4096,
            system=system,
            tools=TOOL_DEFINITIONS,
            messages=messages,
        )
        # Append assistant turn
        messages.append({"role": "assistant", "content": response.content})

        if response.stop_reason != "tool_use":
            text_parts = [b.text for b in response.content if b.type == "text"]
            return ("\n".join(text_parts).strip(), messages)

        # Run every tool call in the response — parallelise where safe
        tool_blocks = [b for b in response.content if b.type == "tool_use"]
        if len(tool_blocks) == 1:
            block = tool_blocks[0]
            result = _dispatch(block.name, block.input or {})
            tool_results = [{
                "type": "tool_result",
                "tool_use_id": block.id,
                "content": result,
            }]
        else:
            with ThreadPoolExecutor(max_workers=len(tool_blocks)) as pool:
                futures = {
                    pool.submit(_dispatch, block.name, block.input or {}): block
                    for block in tool_blocks
                }
                tool_results = []
                for future in as_completed(futures):
                    block = futures[future]
                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": future.result(),
                    })
        messages.append({"role": "user", "content": tool_results})

    return ("(tool loop limit hit — simplify your request)", messages)
