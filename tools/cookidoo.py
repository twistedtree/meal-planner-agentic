"""Cookidoo (Thermomix) integration.

Three tools exposed to the orchestrator:
  - list_cookidoo_collections()         → [{id, name, description, recipe_count}]
  - get_cookidoo_collection(col_id)     → [{id, name, total_time_min}]
  - fetch_cookidoo_recipe(recipe_id)    → Recipe summary (also appended to recipes.json)

Library (cookidoo-api) is async-only; each tool call opens a fresh aiohttp
session via asyncio.run(). Slight per-call login cost; acceptable for
human-speed interactions.
"""
import asyncio
import os
import re
from datetime import datetime
from typing import Any

import aiohttp
from cookidoo_api import Cookidoo, get_localization_options
from cookidoo_api.types import CookidooConfig

from models import Recipe
from tools.recipes import append_recipes, recipe_summary

_PROTEIN_KEYWORDS = [
    # order matters — more specific first
    "salmon", "tuna", "cod", "snapper", "barramundi", "prawn", "shrimp",
    "scallop", "mussel", "oyster", "fish",
    "chicken", "duck", "turkey",
    "beef", "veal", "steak",
    "pork", "bacon", "ham", "prosciutto",
    "lamb",
    "tofu", "tempeh",
    "chickpea", "lentil", "bean",
    "egg",
]

# Order matters — specific cuisines before ones with overlapping vocabulary
# (e.g. "thai" before "indian" so "thai red curry" → thai not indian).
_CUISINE_KEYWORDS: list[tuple[str, list[str]]] = [
    ("thai", ["thai", "tom yum", "pad thai", "lemongrass", "galangal", "fish sauce"]),
    ("vietnamese", ["pho", "banh mi", "nuoc cham", "vietnamese"]),
    ("japanese", ["miso", "soba", "teriyaki", "sushi", "dashi", "mirin", "wasabi", "ramen", "tempura", "sashimi"]),
    ("korean", ["kimchi", "gochujang", "bulgogi", "bibimbap", "korean"]),
    ("chinese", ["hoisin", "szechuan", "sichuan", "bok choy", "congee", "chinese", "sweet and sour", "stir-fry", "stir fry", "wok", "cantonese"]),
    ("indian", ["masala", "tikka", "naan", "biryani", "tandoori", "paneer", "garam masala", "dahl", "dal ", "bhaji", "raita", "korma", "vindaloo"]),
    ("moroccan", ["tagine", "harissa", "couscous", "ras el hanout", "preserved lemon", "moroccan"]),
    ("middle-eastern", ["hommus", "hummus", "tahini", "falafel", "shawarma", "baba ganoush", "za'atar", "zaatar", "pita", "mutabbal", "fattoush"]),
    ("mexican", ["tortilla", "salsa", "guacamole", "enchilada", "quesadilla", "nacho", "fajita", "taco", "chipotle", "burrito", "tomatillo"]),
    ("italian", ["pasta", "parmesan", "pizza", "risotto", "gnocchi", "lasagne", "lasagna", "bolognese", "prosciutto", "mozzarella", "pesto", "carbonara", "focaccia", "tiramisu", "minestrone", "caprese", "bruschetta", "arrabbiata", "puttanesca", "ravioli"]),
    ("french", ["confit", "hollandaise", "béarnaise", "bearnaise", "bouillabaisse", "ratatouille", "crème brûlée", "creme brulee", "quiche", "soufflé", "souffle", "cassoulet", "coq au vin", "croissant", "profiterole", "crêpe"]),
    ("spanish", ["paella", "chorizo", "gazpacho", "romesco", "spanish"]),
    ("german", ["sauerkraut", "bratwurst", "schnitzel", "spätzle", "spatzle", "german"]),
    ("british", ["shepherd's pie", "shepherds pie", "fish and chips", "yorkshire", "cornish pasty", "bangers and mash"]),
    ("australian", ["anzac", "lamington", "pavlova", "aussie"]),
]


def _infer_cuisine(title: str, ingredient_names: list[str]) -> str:
    haystack = (title + " " + " ".join(ingredient_names)).lower()
    for cuisine, keywords in _CUISINE_KEYWORDS:
        if any(kw in haystack for kw in keywords):
            return cuisine
    return "unknown"


def _async_run(coro):
    """Run an async coroutine from sync code. New event loop per call."""
    return asyncio.run(coro)


async def _client(session: aiohttp.ClientSession) -> Cookidoo:
    loc = (await get_localization_options(country="au", language="en-AU"))[0]
    c = Cookidoo(session, cfg=CookidooConfig(
        email=os.environ["cookidoo_user"],
        password=os.environ["cookiday_pass"],
        localization=loc,
    ))
    await c.login()
    return c


# --- Mapping ---

def _slugify(title: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")
    return slug[:60] or "untitled"


# Compound ingredient names that contain a protein keyword but aren't a main protein
# (fish sauce, chicken stock, beef bouillon, etc.). Stripped before keyword match.
_PROTEIN_NOISE = [
    "fish sauce", "anchovy paste",
    "chicken stock", "chicken broth", "chicken bouillon", "chicken bouillon powder", "chicken stock paste",
    "beef stock", "beef broth", "beef bouillon", "beef stock paste",
    "vegetable stock", "vegetable broth", "vegetable stock paste",
]


def _guess_main_protein(ingredient_names: list[str]) -> str:
    haystack = " ".join(n.lower() for n in ingredient_names)
    for noise in _PROTEIN_NOISE:
        haystack = haystack.replace(noise, "")
    for kw in _PROTEIN_KEYWORDS:
        if kw in haystack:
            return kw
    return "unknown"


def _cookidoo_details_to_recipe(details: Any) -> Recipe:
    """Map CookidooShoppingRecipeDetails → Recipe."""
    ingredient_names = [getattr(i, "name", "") for i in getattr(details, "ingredients", [])]
    categories = [getattr(c, "name", "") for c in getattr(details, "categories", [])]
    total_time = getattr(details, "total_time", None)
    cook_time_min = int(total_time // 60) if total_time else 30

    return Recipe(
        id=details.id,  # e.g. "r471786" — stable, use directly
        title=details.name,
        cuisine=_infer_cuisine(details.name, ingredient_names),
        main_protein=_guess_main_protein(ingredient_names),
        key_ingredients=ingredient_names[:8],
        tags=categories[:3],
        cook_time_min=cook_time_min,
        source_url=getattr(details, "url", None),
        source="cookidoo",
        added_at=datetime.now(),
    )


# --- Tool-facing (sync) ---

def list_cookidoo_collections() -> list[dict]:
    """Return compact summaries of all managed (Vorwerk-curated) Cookidoo collections."""
    async def _run() -> list[dict]:
        async with aiohttp.ClientSession() as session:
            c = await _client(session)
            cols = await c.get_managed_collections(page=0)
            out = []
            for col in cols:
                recipe_count = sum(len(ch.recipes) for ch in getattr(col, "chapters", []))
                out.append({
                    "id": col.id,
                    "name": col.name,
                    "description": (col.description or "")[:200],
                    "recipe_count": recipe_count,
                })
            return out
    return _async_run(_run())


def get_cookidoo_collection(col_id: str) -> list[dict]:
    """Return recipes inside one collection as [{id, name, total_time_min}]."""
    async def _run() -> list[dict]:
        async with aiohttp.ClientSession() as session:
            c = await _client(session)
            cols = await c.get_managed_collections(page=0)
            match = next((col for col in cols if col.id == col_id), None)
            if match is None:
                return []
            recipes = []
            for chapter in getattr(match, "chapters", []):
                for r in chapter.recipes:
                    recipes.append({
                        "id": r.id,
                        "name": r.name,
                        "total_time_min": (r.total_time // 60) if r.total_time else None,
                        "chapter": chapter.name,
                    })
            return recipes
    return _async_run(_run())


def fetch_cookidoo_recipe(recipe_id: str) -> dict | None:
    """Fetch full recipe details, persist to recipes.json, return the summary."""
    async def _run() -> Any:
        async with aiohttp.ClientSession() as session:
            c = await _client(session)
            return await c.get_recipe_details(recipe_id)

    details = _async_run(_run())
    if details is None:
        return None
    recipe = _cookidoo_details_to_recipe(details)
    append_recipes([recipe])  # idempotent on id
    return recipe_summary(recipe)
