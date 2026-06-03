"""Property-based (fuzz) tests for combat invariants — rule 4.4.2.

Hypothesis is an OPTIONAL dependency. To keep `pytest` collection robust
when it is absent, EVERY reference to `given` / `settings` / `st` lives
inside the `if _HYP:` block below. Python evaluates decorator expressions
at import time, so defining the decorated tests unconditionally would raise
`NameError: name 'given' is not defined` during collection on a machine
without Hypothesis — before pytest could honour any skip marker. Guarding
the definitions (rather than the bodies) avoids that entirely: with
Hypothesis installed the fuzz tests are collected and run; without it they
simply are not defined, and the plain sanity tests below still run.
"""

from __future__ import annotations

import math

from almoravid.battle import BattleSide, _allocate_rounded_hits, resolve_battle
from almoravid.scenarios import load_scenario

try:
    from hypothesis import given, settings
    from hypothesis import strategies as st
    _HYP = True
except ImportError:  # pragma: no cover - exercised only when Hypothesis absent
    _HYP = False


# ---------------------------------------------------------------------------
# Shared helpers (no Hypothesis dependency).
# ---------------------------------------------------------------------------

_KINDS = ["crossbows", "bowmen", "javelins", "slingers", "missiles", "melee"]


def _sides(knights: int, sergeants: int) -> tuple:
    """A fresh single-Lord-per-side Battle Array with the given Forces."""
    s = load_scenario("scenario_a_toledo_beset", seed=7)
    atk = BattleSide(side="christian", role="attacker",
                     lord_ids=["alfonso"], forces={"knights": knights})
    dfd = BattleSide(side="muslim", role="defender",
                     lord_ids=["al_mutamid"], forces={"sergeants": sergeants})
    return s, atk, dfd


def _allocation_invariant(by_kind: dict[str, float]) -> None:
    """sum(allocated) == ceil(total) and every kind gets >= its floor."""
    total = sum(by_kind.values())
    out = _allocate_rounded_hits(total, by_kind)
    assert sum(out.values()) == math.ceil(total)
    for kind, contrib in by_kind.items():
        assert out.get(kind, 0) >= math.floor(contrib)
    assert all(v >= 0 for v in out.values())


def _concede_invariant(knights: int, sergeants: int) -> None:
    """Concede (4.4.2) is checked before Rout, so the outcome is fixed
    regardless of dice: the non-conceding side wins in exactly 1 Round."""
    s, atk, dfd = _sides(knights, sergeants)
    r = resolve_battle(s, atk, dfd, defender_concede_round=1)
    assert r.winner == "christian"
    assert len(r.rounds) == 1
    s, atk, dfd = _sides(knights, sergeants)
    r = resolve_battle(s, atk, dfd, attacker_concede_round=1)
    assert r.winner == "muslim"
    assert len(r.rounds) == 1


def _determinism_invariant(knights: int, sergeants: int) -> None:
    """Same Array + same seed -> identical winner and Round count."""
    s1, a1, d1 = _sides(knights, sergeants)
    s2, a2, d2 = _sides(knights, sergeants)
    r1 = resolve_battle(s1, a1, d1)
    r2 = resolve_battle(s2, a2, d2)
    assert r1.winner == r2.winner
    assert len(r1.rounds) == len(r2.rounds)


# ---------------------------------------------------------------------------
# Plain sanity tests — always run, even without Hypothesis installed.
# ---------------------------------------------------------------------------

def test_allocation_invariant_examples() -> None:
    _allocation_invariant({"bowmen": 1.5})
    _allocation_invariant({"crossbows": 1.5, "bowmen": 1.5})
    _allocation_invariant({"melee": 2.5, "slingers": 0.5})


def test_concede_invariant_example() -> None:
    _concede_invariant(4, 4)


def test_determinism_invariant_example() -> None:
    _determinism_invariant(3, 5)


# ---------------------------------------------------------------------------
# Property-based fuzz tests — collected only when Hypothesis is available.
# Every `given` / `settings` / `st` use is confined to this block.
# ---------------------------------------------------------------------------

if _HYP:

    _half_units = st.builds(lambda h: h / 2.0, st.integers(min_value=0,
                                                           max_value=8))
    _by_kind = st.dictionaries(
        keys=st.sampled_from(_KINDS), values=_half_units,
        min_size=1, max_size=len(_KINDS),
    ).filter(lambda d: sum(d.values()) > 0)

    @settings(max_examples=200, deadline=None)
    @given(_by_kind)
    def test_fuzz_allocate_rounded_hits(by_kind: dict[str, float]) -> None:
        _allocation_invariant(by_kind)

    @settings(max_examples=60, deadline=None)
    @given(st.integers(min_value=1, max_value=8),
           st.integers(min_value=1, max_value=8))
    def test_fuzz_concede_is_deterministic(knights: int,
                                           sergeants: int) -> None:
        _concede_invariant(knights, sergeants)

    @settings(max_examples=40, deadline=None)
    @given(st.integers(min_value=1, max_value=8),
           st.integers(min_value=1, max_value=8))
    def test_fuzz_resolve_battle_is_seed_deterministic(
            knights: int, sergeants: int) -> None:
        _determinism_invariant(knights, sergeants)
