from models import Profile
from storage import load_json, save_json


def read_profile() -> Profile | None:
    return load_json("profile.json", Profile)


def update_profile(partial: dict) -> Profile:
    """Merge partial updates into profile.json. Create if missing.

    The agent may pass any subset of Profile fields. Fields not present
    are preserved from the existing profile.
    """
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
