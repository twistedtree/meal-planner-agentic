import threading

from models import Profile
from storage import load_json, save_json

# Serialises read-modify-write on profile.json. Mirrors tools/state._state_lock
# and tools/recipes._recipes_lock. Without it concurrent update_profile calls
# with distinct partial dicts lose mutations to lost-update races, and Windows
# os.replace raises PermissionError under contention.
_profile_lock = threading.RLock()


def read_profile() -> Profile | None:
    return load_json("profile.json", Profile)


def update_profile(partial: dict) -> Profile:
    """Merge partial updates into profile.json. Create if missing.

    The agent may pass any subset of Profile fields. Fields not present
    are preserved from the existing profile.
    """
    with _profile_lock:
        current = read_profile()
        merged: dict
        if current is None:
            # First time — require all mandatory fields
            merged = partial
        else:
            merged = current.model_dump()
            merged.update(partial)
        new_profile = Profile.model_validate(merged)
        save_json("profile.json", new_profile)
        return new_profile
