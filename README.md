# Meal Planner (Agentic)

Chat-driven weekly dinner planner. Talk to an agent; it maintains your meal plan, pantry, and recipe library as JSON files.

See [design spec](docs/superpowers/specs/2026-04-15-meal-planner-agentic-design.md).

## Setup

```bash
uv venv
uv pip install -e ".[dev]"
cp .env.example .env   # fill OPENROUTER_API_KEY (and optionally override model strings)
streamlit run app.py   # → http://localhost:8501
```

## What it does

- Plans Mon–Fri dinners from the agent's own knowledge
- Edits the plan via natural language ("swap Wednesday for something lighter")
- Tracks pantry, ratings, and dislikes in three JSON files under `state/`
- Web search only on explicit request ("find me 3 Portuguese bacalhau recipes")
- Warns when the plan violates hard rules (≥1 fish/week, veg every meal, etc.)

## State files

| File | Purpose |
|---|---|
| `state/profile.json` | Household (members, dislikes, dietary rules) |
| `state/recipes.json` | Saved recipes (grows on web search) |
| `state/state.json` | Current plan + pantry + ratings |

Delete any of these to reset that slice of state.

## Tests

```bash
.venv/Scripts/pytest.exe -v   # Windows
.venv/bin/pytest -v           # macOS/Linux
```

Covers: validator rules, storage round-trips, search ranking, model serialization.
