# Meal Planner (Agentic) — Design

**Status:** Draft v1
**Date:** 2026-04-15
**Relationship to sibling project:** Simpler, chat-first reimagining of `../meal-planner/`. Same goal, different architecture. The original's SPEC.md defines the household's planning rules; this doc defines how an agentic version satisfies them with ~5% of the code.

---

## 1. Goal

> A chat interface for weekly dinner planning. The user talks to an agent; the agent reads/writes a meal-plan table and supporting state; all edits happen through natural language.

The original meal-planner is a Next.js PWA with Postgres, Drizzle, onboarding wizards, pantry UIs, budget enforcement, and mutation-tested risk tiers. This version strips every piece of structured UI and replaces it with a conversation plus a table.

---

## 2. Non-goals

- Authentication, multi-user, multi-household
- Budget enforcement / LLM audit log
- Offline mode, PWA, service workers, multi-device concurrency
- Drizzle / Postgres / Neon / Docker
- Onboarding wizard UI (replaced by agent chat)
- Shopping-list as a separate subsystem (agent can recommend what to buy inline)
- Risk-tiered mutation testing, TDD pre-tool-use hooks, Playwright E2E
- Native mobile app

---

## 3. Architecture

```
┌────────────────────────────────────────────────────────────┐
│ Streamlit UI (app.py)                                      │
│  - st.chat_input / st.chat_message                         │
│  - st.dataframe for the meal plan table                    │
│  - Sidebar: pantry pills, recent ratings expander          │
│  - Re-reads JSON state on every turn                       │
└────────────────────┬───────────────────────────────────────┘
                     │ user message
                     ▼
┌────────────────────────────────────────────────────────────┐
│ Orchestrator agent (claude-agent-sdk, Sonnet 4.6)          │
│  System prompt: household context from profile.json        │
│  Tools: read/update profile, read/update state,            │
│         list/get/search recipes, validate_plan,            │
│         find_new_recipes (spawns subagent)                 │
└────────────────────┬───────────────────────────────────────┘
                     │ only on explicit "find new recipes"
                     ▼
┌────────────────────────────────────────────────────────────┐
│ RecipeFinder subagent (Sonnet 4.6 + web_search)            │
│  Isolated context. Returns 3–5 structured Recipe objects.  │
│  Orchestrator appends approved ones to recipes.json.       │
└────────────────────────────────────────────────────────────┘

state/
  profile.json   # household, dislikes, dietary rules (rarely changes)
  recipes.json   # saved recipes (grows on explicit request)
  state.json     # current plan + pantry + ratings (weekly)
```

**Decisions:**

- **One orchestrator for everything except web search.** Web search is isolated in a subagent so bloated tool output doesn't pollute the chat context window.
- **JSON files are the source of truth.** The agent reads them via tools rather than having them stuffed in the system prompt every turn — keeps token use flat as the recipe library grows.
- **Three files, separated by volatility.** Profile (rare changes), recipes (grows), state (weekly).

---

## 4. Data model (Pydantic)

```python
class Member(BaseModel):
    name: str
    is_adult: bool
    dislikes: list[str]

class Profile(BaseModel):
    household_size: int
    members: list[Member]
    household_dislikes: list[str]
    dietary_rules: list[str]        # e.g. "≥1 fish/week", "veg every meal"
    preferred_cuisines: list[str]
    notes: str                      # free-text learned prefs

class Recipe(BaseModel):
    id: str                         # slugified title
    title: str
    cuisine: str
    main_protein: str
    key_ingredients: list[str]
    tags: list[str]                 # "quick", "one-pan", "kid-friendly", etc.
    cook_time_min: int
    last_cooked: datetime | None
    times_cooked: int
    avg_rating: float | None        # derived from ratings
    source_url: str | None          # set only for web-searched recipes
    added_at: datetime

class Rating(BaseModel):
    recipe_title: str
    rater: str                      # member name
    rating: Literal["again_soon", "worth_repeating", "meh", "never_again"]
    cooked_at: datetime

class MealPlanSlot(BaseModel):
    day: Literal["Mon", "Tue", "Wed", "Thu", "Fri"]
    recipe_title: str               # free text; not every meal is in recipes.json
    recipe_id: str | None           # set iff pulled from saved library
    key_ingredients: list[str]
    rationale: str                  # one line, LLM-generated

class State(BaseModel):
    meal_plan: list[MealPlanSlot]
    pantry: list[str]               # perishables only, in/out (no quantities)
    ratings: list[Rating]
    last_updated: datetime
```

**Rationale — free-text `recipe_title` in plan slots:** the agent plans from its own knowledge by default. Not every planned meal lives in `recipes.json`. A slot only gets a `recipe_id` if pulled from the saved library. Keeps plan-gen frictionless.

---

## 5. Tools

Exposed to the orchestrator via `claude-agent-sdk`:

| Tool | Input | Output | Notes |
|---|---|---|---|
| `read_profile` | — | `Profile` JSON | cheap, called whenever context needed |
| `update_profile` | partial `Profile` | new `Profile` | merges; used during onboarding + when prefs change |
| `read_state` | — | `State` JSON | current plan + pantry + ratings |
| `update_plan` | `list[MealPlanSlot]` | new `State` | replaces meal_plan wholesale |
| `update_pantry` | `{add: [str], remove: [str]}` | new `State` | diff-style |
| `record_rating` | `Rating` | new `State` | appends |
| `list_recipes` | optional filter | compact one-liners | `{id, title, cuisine, protein, avg_rating}` |
| `get_recipe` | `id` | full `Recipe` | only called when committing to a candidate |
| `search_recipes` | `{query, filters?}` | top-20 compact matches | matches query against title + tags + ingredients + cuisine, sorted by avg_rating desc then times_cooked desc |
| `find_new_recipes` | `{query, count}` | `list[Recipe]` | **spawns RecipeFinder subagent with web_search**; orchestrator appends approved results to recipes.json |
| `validate_plan` | `list[MealPlanSlot]` | `list[str]` warnings | pure function, no LLM; hard-rule check |

**Cost control:** a 500-recipe library costs ~10K tokens to fully list but only ~400 tokens for a 20-match search. The agent never loads full recipe details for candidates it doesn't commit to. Embeddings are deferred until the library grows past ~500, at which point `search_recipes` can be rebackened with Voyage (Anthropic's partner) with no schema change.

---

## 6. Prompts

### Orchestrator system prompt

```
You are the meal-planning assistant for a 4-person household.

HOUSEHOLD CONTEXT (from profile.json, re-read at each turn):
{profile}

YOUR JOB:
- Plan Mon–Fri dinners on request.
- Edit the plan on natural-language requests from the user.
- Check pantry, suggest swaps, record ratings.
- Default: plan from your own knowledge. Pull from recipes.json when
  the user references past meals or asks "what have we liked recently".
- Web search ONLY when the user explicitly asks to find/discover new
  recipes or "update the database". Use the find_new_recipes tool.

HARD RULES (enforced by validate_plan — surface warnings, don't self-heal):
- ≥1 fish meal per week
- Every meal includes a vegetable
- Never schedule a recipe both adults rated never_again
- Never schedule anything in household_dislikes

SOFT PREFERENCES (use judgement):
- Favor recipes rated 'again_soon' or 'worth_repeating'
- Favor pantry-aligned recipes (ingredients already in stock)
- Include 1–2 recipes requiring shopping — keep it interesting
- Avoid repeating a recipe cooked in the last 7 days

INTERACTION RULES:
- Always confirm before calling update_plan / update_pantry / update_profile
  unless the user said "just do it"
- After any update_plan, call validate_plan and surface warnings verbatim
- Keep responses short. The user reads the table, not prose.
- If the state is empty (first run), open with an onboarding chat.
```

Profile, latest state summary, and today's date are injected per-turn via a pre-prompt. System prompt itself stays stable (prompt-cache-friendly).

### RecipeFinder subagent prompt

```
You are a recipe researcher. Given a query and household context:
1. Use web_search to find 3–5 recipes matching the query.
2. Prefer reputable recipe sites (BBC Good Food, Serious Eats,
   NYT Cooking, Bon Appetit).
3. For each: extract title, cuisine, main_protein, key_ingredients,
   cook_time_min, source_url.
4. Return structured JSON matching the Recipe schema.
5. Filter against household dislikes and dietary rules — do not
   return anything that violates them.
```

Tools: `web_search` only. The orchestrator receives the Recipe list back, shows the user the titles + one-line summaries, confirms, then appends to `recipes.json`. The subagent's full browsing context stays isolated.

---

## 7. UI (Streamlit)

**Layout — main area, top to bottom:**

1. **Meal plan table** (`st.dataframe`, sticky at top). Columns:

   | Day | Recipe | Protein | Key ingredients | Why | Status |
   |---|---|---|---|---|---|
   | Mon | Salmon teriyaki bowls | salmon | broccoli, rice, soy | Fish slot; pantry has salmon | — |

2. **Pantry pills** — comma-separated list of current perishables.
3. **Recent ratings expander** — collapsible.
4. **Chat** — `st.chat_input` + rolling `st.chat_message` history for the session.

**Editing flow:**

```
user:    "swap Wednesday for something lighter, Mia isn't hungry lately"
agent:   [reads state] [calls search_recipes("light weeknight")]
         "How about Vietnamese chicken pho? Light broth, quick,
          Mia rated it 'again_soon' last time."
user:    "yes, do it"
agent:   [calls update_plan with Wed swapped]
         "Done. Pantry is missing rice noodles and bean sprouts —
          add to shopping?"
```

**Principles:**
- Agent never edits silently. One-line confirmation before every mutation, unless the user said "just do it" upfront.
- Single state, no draft mode. `state.json` *is* the current plan. Undo via agent ("undo that") using per-turn in-memory snapshots.
- No scheduled regeneration. User has to ask.

---

## 8. Hard-constraint guardrail

`validate_plan(plan, profile) -> list[str]` — pure function, no LLM. Returns warnings:

- `"No fish this week"` if no slot has `main_protein in {fish, seafood}`
- `"Tue violates household dislike: mushrooms"` if a slot's ingredients intersect `household_dislikes`
- `"Wed (chili con carne) was rated never_again by both adults"` if a slot matches a mutual-never-again recipe
- `"Thu has no vegetable listed"` if `key_ingredients` contains nothing tagged as produce

Agent is prompted to call `validate_plan` after every `update_plan` and surface warnings verbatim. **Non-blocking.** User can override with "ignore that, I don't care this week."

---

## 9. Model routing

- Orchestrator: **Sonnet 4.6** (`claude-sonnet-4-6`)
- RecipeFinder subagent: **Sonnet 4.6 + web_search**
- No Haiku. Workload is low-volume personal use; Sonnet quality matters more than per-call cost.

**Prompt caching:** system prompt + profile go in a cached block (5-minute TTL). Tool definitions are static. Only the user message + compact state summary are uncached per turn.

---

## 10. Project layout

```
meal-planner-agentic/
  app.py                     # Streamlit entrypoint: chat + table + sidebar
  agents/
    orchestrator.py          # builds ClaudeAgentSDK session + tools
    recipe_finder.py         # subagent factory
    prompts.py               # system prompts as constants
  tools/
    profile.py               # read_profile, update_profile
    state.py                 # read_state, update_plan, update_pantry,
                             #   record_rating, snapshot_for_undo
    recipes.py               # list_recipes, get_recipe, search_recipes,
                             #   find_new_recipes (calls subagent)
    validate.py              # validate_plan — pure function, no LLM
  models.py                  # Pydantic: Profile, Recipe, State, Member, etc.
  storage.py                 # atomic JSON read/write helpers
  state/                     # gitignored
    profile.json
    recipes.json
    state.json
  tests/
    test_validate.py
    test_storage.py
    test_search.py
  pyproject.toml
  README.md
  .env.example               # ANTHROPIC_API_KEY=
  .gitignore                 # state/, .env, __pycache__
```

---

## 11. Dependencies

```toml
[project]
dependencies = [
  "claude-agent-sdk >= 0.1",
  "streamlit >= 1.40",
  "pydantic >= 2",
  "python-dotenv",
]

[project.optional-dependencies]
dev = ["pytest"]
```

No DB, no ORM, no migrations, no Docker, no Playwright.

---

## 12. Running it

```
uv sync                      # or pip install -e .
cp .env.example .env         # fill ANTHROPIC_API_KEY
streamlit run app.py         # → http://localhost:8501
```

---

## 13. Testing scope

- **Unit tests** for `validate_plan` (hard rules).
- **Unit tests** for `search_recipes` ranking + filter behavior.
- **Round-trip tests** on `storage.py` (atomic write, no corruption on crash).
- **No E2E.** The agent's conversational behavior is verified by using it.

---

## 14. Open items

- Exact `claude-agent-sdk` API shape for subagent invocation — confirm during scaffold.
- Whether `find_new_recipes` runs sync-blocking (simple) or streams progress back to the chat (nicer UX). Start sync; revisit.
- Undo depth — single-step for v1; multi-step if useful in practice.
