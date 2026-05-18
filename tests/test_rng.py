"""Phase 2a RNG and state-expansion tests.

Determinism is essential: every harness run must be reproducible from
the seed in meta.seed. The rng_state counter advances atomically; per
(seed, rng_state) the result is fixed.
"""

from __future__ import annotations

import pytest

from almoravid.rng import roll_d6, roll_d6_n, shuffle
from almoravid.scenarios import load_scenario


def test_same_seed_same_rolls() -> None:
    a = load_scenario("scenario_a_toledo_beset", seed=42)
    b = load_scenario("scenario_a_toledo_beset", seed=42)
    assert [roll_d6(a) for _ in range(20)] == [roll_d6(b) for _ in range(20)]


def test_different_seeds_diverge() -> None:
    a = load_scenario("scenario_a_toledo_beset", seed=1)
    b = load_scenario("scenario_a_toledo_beset", seed=2)
    assert [roll_d6(a) for _ in range(20)] != [roll_d6(b) for _ in range(20)]


def test_rng_state_advances() -> None:
    s = load_scenario("scenario_a_toledo_beset", seed=7)
    assert s.meta.rng_state == 0
    roll_d6(s)
    assert s.meta.rng_state == 1
    roll_d6_n(s, 4)
    assert s.meta.rng_state == 5
    shuffle(s, [1, 2, 3, 4, 5])
    assert s.meta.rng_state == 6


def test_roll_d6_in_range() -> None:
    s = load_scenario("scenario_a_toledo_beset", seed=1)
    for _ in range(100):
        v = roll_d6(s)
        assert 1 <= v <= 6


def test_shuffle_returns_new_list() -> None:
    s = load_scenario("scenario_a_toledo_beset", seed=1)
    original = [1, 2, 3, 4, 5]
    shuffled = shuffle(s, original)
    assert sorted(shuffled) == sorted(original)
    assert shuffled is not original  # Returns new list
    assert original == [1, 2, 3, 4, 5]  # Original unmutated


def test_shuffle_empty_advances_state() -> None:
    """Empty shuffles still tick rng_state (so consumption matches action count)."""
    s = load_scenario("scenario_a_toledo_beset", seed=1)
    before = s.meta.rng_state
    out = shuffle(s, [])
    assert out == []
    assert s.meta.rng_state == before + 1


# ---- State expansions --------------------------------------------------

def test_meta_has_levy_step_fields() -> None:
    s = load_scenario("scenario_a_toledo_beset")
    assert s.meta.levy_step is None
    assert s.meta.levy_step_completed_christian is False
    assert s.meta.levy_step_completed_muslim is False
    assert s.meta.first_levy_done is False
    assert s.meta.rng_state == 0


def test_decks_has_event_persistence_buckets() -> None:
    """Pattern 13 / 14: persistence buckets exist from day one with correct shape."""
    s = load_scenario("scenario_a_toledo_beset")
    assert s.decks.this_levy_events == {}
    assert s.decks.this_campaign_events == {}
    assert s.decks.pending_draw == {}


def test_version_bumped_to_0_2_0() -> None:
    s = load_scenario("scenario_a_toledo_beset")
    assert s.meta.version == "0.2.0"
