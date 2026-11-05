"""Transient participant visibility during synchronous combat resolution."""

from __future__ import annotations

from collections.abc import Callable
from contextvars import ContextVar
from functools import wraps
from inspect import signature
from typing import ParamSpec, TypeVar

P = ParamSpec("P")
T = TypeVar("T")
_COMBAT_MATS: ContextVar[tuple[int, set[str]] | None] = ContextVar(
    "almoravid_combat_mats", default=None
)


def combat_visible_lords(state: object) -> set[str]:
    scope = _COMBAT_MATS.get()
    return scope[1] if scope is not None and scope[0] == id(state) else set()


def reveal_combat_mats(function: Callable[P, T]) -> Callable[P, T]:
    parameters = signature(function)

    @wraps(function)
    def wrapped(*args: P.args, **kwargs: P.kwargs) -> T:
        bound = parameters.bind(*args, **kwargs)
        state = bound.arguments["state"]
        lords = set(combat_visible_lords(state))
        for name in ("attacker", "defender"):
            side = bound.arguments.get(name)
            lords.update(getattr(side, "lord_ids", []))
        for name in ("marcher_ids", "sallyer_ids", "defender_ids"):
            lords.update(bound.arguments.get(name) or [])
        token = _COMBAT_MATS.set((id(state), lords))
        try:
            return function(*args, **kwargs)
        finally:
            _COMBAT_MATS.reset(token)

    return wrapped
