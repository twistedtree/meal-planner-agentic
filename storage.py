import os
from pathlib import Path
from typing import TypeVar, Type
from pydantic import BaseModel

STATE_DIR = Path(__file__).parent / "state"

T = TypeVar("T", bound=BaseModel)


def _ensure_dir() -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True)


def load_json(filename: str, model: Type[T]) -> T | None:
    """Load and parse a JSON file into the given Pydantic model. Returns None if missing."""
    path = STATE_DIR / filename
    if not path.exists():
        return None
    return model.model_validate_json(path.read_text(encoding="utf-8"))


def load_json_list(filename: str, model: Type[T]) -> list[T]:
    """Load a JSON file containing a list of models. Returns [] if missing."""
    path = STATE_DIR / filename
    if not path.exists():
        return []
    import json
    raw = json.loads(path.read_text(encoding="utf-8"))
    return [model.model_validate(item) for item in raw]


def save_json(filename: str, value: BaseModel) -> None:
    """Atomically write a Pydantic model to STATE_DIR/filename."""
    _ensure_dir()
    path = STATE_DIR / filename
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(value.model_dump_json(indent=2), encoding="utf-8")
    os.replace(tmp, path)


def save_json_list(filename: str, values: list[BaseModel]) -> None:
    """Atomically write a list of Pydantic models."""
    _ensure_dir()
    path = STATE_DIR / filename
    tmp = path.with_suffix(path.suffix + ".tmp")
    import json
    tmp.write_text(
        json.dumps([v.model_dump(mode="json") for v in values], indent=2),
        encoding="utf-8",
    )
    os.replace(tmp, path)
