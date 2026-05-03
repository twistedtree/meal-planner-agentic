from datetime import datetime, date
from typing import Literal
from pydantic import BaseModel, Field


class Member(BaseModel):
    name: str
    is_adult: bool
    dislikes: list[str] = Field(default_factory=list)


class Profile(BaseModel):
    household_size: int
    members: list[Member]
    household_dislikes: list[str] = Field(default_factory=list)
    dietary_rules: list[str] = Field(default_factory=list)
    preferred_cuisines: list[str] = Field(default_factory=list)
    notes: str = ""


class Recipe(BaseModel):
    id: str
    title: str
    cuisine: str
    main_protein: str
    key_ingredients: list[str]
    tags: list[str] = Field(default_factory=list)
    cook_time_min: int
    last_cooked: datetime | None = None
    times_cooked: int = 0
    avg_rating: float | None = None
    source_url: str | None = None
    source: str = "unknown"  # "cookidoo", "web", "manual", "knowledge"
    notes: str = ""
    added_at: datetime


class Rating(BaseModel):
    recipe_title: str
    rater: str
    rating: Literal["again_soon", "worth_repeating", "meh", "never_again"]
    cooked_at: datetime


class MealPlanSlot(BaseModel):
    day: Literal["Mon", "Tue", "Wed", "Thu", "Fri"]
    recipe_title: str
    recipe_id: str | None = None
    main_protein: str                       # NEW
    key_ingredients: list[str]
    rationale: str


class ArchivedPlan(BaseModel):
    week_of: date
    slots: list[MealPlanSlot]


class State(BaseModel):
    meal_plan: list[MealPlanSlot] = Field(default_factory=list)
    week_of: date | None = None
    plan_history: list[ArchivedPlan] = Field(default_factory=list)
    pantry: list[str] = Field(default_factory=list)
    ratings: list[Rating] = Field(default_factory=list)
    last_updated: datetime
