"""Deterministic, seedable RNG used by the harness.

Per BRIEF: every dice roll and every shuffle must be reproducible from
the seed stored in `meta.seed`. We accomplish this by carrying an
incrementing `meta.rng_state` counter that is advanced atomically with
every consumed RNG event. A given (seed, rng_state) pair always yields
the same value.

We use Python's `random.Random` with a hash-mixed key so adjacent
`rng_state` integers do not produce correlated rolls. The resulting
sequence is fully deterministic given the seed.

Usage from action handlers:

    from almoravid.rng import roll_d6, shuffle
    result = roll_d6(state)              # advances state.meta.rng_state
    shuffled = shuffle(state, ["a","b"]) # returns new shuffled list

Helpers never mutate the input list; they return a new list.
"""

from __future__ import annotations

import hashlib
import random
from typing import TYPE_CHECKING, TypeVar

if TYPE_CHECKING:
    from almoravid.state import GameState

T = TypeVar("T")


def _make_rng(seed: int, rng_state: int) -> random.Random:
    """Build a Random keyed by SHA-256(seed||rng_state) so that adjacent
    rng_state values do not produce correlated draws.
    """
    digest = hashlib.sha256(f"{seed}:{rng_state}".encode()).digest()
    rng = random.Random()
    rng.seed(int.from_bytes(digest[:16], "big"))
    return rng


def roll_d6(state: GameState) -> int:
    """Roll a single d6, advancing state.meta.rng_state by 1."""
    rng = _make_rng(state.meta.seed, state.meta.rng_state)
    state.meta.rng_state += 1
    return rng.randint(1, 6)


def roll_d6_n(state: GameState, n: int) -> list[int]:
    """Roll n d6 results. Each roll advances rng_state by 1."""
    return [roll_d6(state) for _ in range(n)]


def shuffle(state: GameState, items: list[T]) -> list[T]:
    """Return a Fisher-Yates shuffle of items, advancing rng_state by 1.

    Empty / single-element lists still consume an rng_state tick so the
    consumption record matches the action count.
    """
    rng = _make_rng(state.meta.seed, state.meta.rng_state)
    state.meta.rng_state += 1
    out = list(items)
    rng.shuffle(out)
    return out
