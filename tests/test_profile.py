from concurrent.futures import ThreadPoolExecutor

import pytest

from tools.profile import read_profile, update_profile


@pytest.fixture
def tmp_state_dir(tmp_path, monkeypatch):
    monkeypatch.setattr("storage.STATE_DIR", tmp_path)
    return tmp_path


def test_update_profile_creates_when_missing(tmp_state_dir):
    p = update_profile({
        "household_size": 1,
        "members": [{"name": "X", "is_adult": True, "dislikes": []}],
    })
    assert p.household_size == 1
    assert read_profile().household_size == 1


def test_update_profile_merges_into_existing(tmp_state_dir):
    update_profile({
        "household_size": 2,
        "members": [{"name": "A", "is_adult": True, "dislikes": []}],
    })
    p = update_profile({"notes": "vegetarian-leaning"})
    assert p.household_size == 2  # preserved
    assert p.notes == "vegetarian-leaning"


def test_update_profile_concurrent_partials_dont_lose_fields(tmp_state_dir):
    """Concurrent update_profile calls modifying distinct fields must all persist.

    Without _profile_lock, two threads can read the same snapshot and each
    write back, with one thread's distinct-field mutation overwriting the
    other's because both started from the pre-mutation state. The lock
    serialises read-modify-write so each call sees the prior call's writes.
    """
    update_profile({
        "household_size": 1,
        "members": [{"name": "X", "is_adult": True, "dislikes": []}],
    })

    def t(i):
        if i % 2 == 0:
            update_profile({"notes": f"n_{i:02d}"})
        else:
            update_profile({"preferred_cuisines": [f"c_{i:02d}"]})

    with ThreadPoolExecutor(max_workers=16) as pool:
        list(pool.map(t, range(50)))

    p = read_profile()
    assert p.notes != "", "notes was lost — race in update_profile"
    assert len(p.preferred_cuisines) > 0, "preferred_cuisines was lost — race in update_profile"
