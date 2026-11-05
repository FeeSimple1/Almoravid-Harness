"""In-place rollback for rejected compound actions."""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel

from .state import GameState


class ActionCheckpoint:
    """Restore a failed action without invalidating callers' state references.

    Record shallow copies of the current board's mutable containers and
    model fields. Restoring those same objects also repairs references to
    Lords, mats, or lists retained by a library caller. Historical entries
    are read-only to handlers; only the dispatcher appends to history, so
    its length is sufficient and checkpoint cost does not grow with play.
    """

    def __init__(self, state: GameState) -> None:
        self._history = state.history
        self._history_length = len(state.history)
        self._containers: list[tuple[Any, Any]] = []
        self._models: list[tuple[BaseModel, dict[str, Any], set[str]]] = []
        seen: set[int] = set()
        pending: list[Any] = [state]
        immutable_types = {str, int, float, bool, type(None)}
        while pending:
            value = pending.pop()
            # Most state fields are immutable scalars; skip them before
            # identity checks or inspecting models and containers.
            if (type(value) in immutable_types
                    or value is self._history or id(value) in seen):
                continue
            seen.add(id(value))
            if isinstance(value, BaseModel):
                self._models.append((value, value.__dict__, value.__pydantic_fields_set__))
                pending.extend((value.__dict__, value.__pydantic_fields_set__))
            elif isinstance(value, dict):
                self._containers.append((value, value.copy()))
                pending.extend(value.values())
            elif isinstance(value, list):
                self._containers.append((value, value.copy()))
                pending.extend(value)
            elif isinstance(value, set):
                # The state models' sets contain immutable field names.
                self._containers.append((value, value.copy()))
            elif isinstance(value, tuple):
                pending.extend(value)

    def restore(self) -> None:
        # Validated assignment may replace a model's dictionary or fields set.
        # Reattach the original containers before restoring their contents.
        for model, fields, fields_set in self._models:
            object.__setattr__(model, "__dict__", fields)
            object.__setattr__(model, "__pydantic_fields_set__", fields_set)
        for target, contents in self._containers:
            if isinstance(target, list):
                target[:] = contents
            else:
                target.clear()
                target.update(contents)
        del self._history[self._history_length:]

