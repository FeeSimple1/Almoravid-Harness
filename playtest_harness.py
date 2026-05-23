"""Self-contained playtest harness for the Almoravid engine.

Designed for an INDEPENDENT agent (e.g. ChatGPT's code interpreter) to drive
the game model-agnostically: a plain-text briefing + a numbered, *validated*
legal-action menu in; an index or action-dict out. Per the cross-harness
advisory, the action palette is validated (every candidate is probed via
deepcopy->apply and any the executor would reject is dropped AND logged), so
the driver never sees an illegal move and you still get over-enumeration
diagnostics. The engine's RNG lives in the state, so probing never disturbs
the real game's dice.

Requirements: Python 3.10+ and `pydantic` (>=2). NOTE: `typer` is NOT needed
(only the optional CLI uses it). No network or `pip install` required — this
file puts `src/` on the path itself.

Quick start (from the repo root):

    from playtest_harness import Harness
    print(Harness.scenarios())                 # list scenario ids
    h = Harness("scenario_a_toledo_beset", seed=1)
    print(h.briefing())                        # human-readable state
    for i, m in enumerate(h.legal()):          # numbered, validated menu
        print(i, m)
    h.apply(0)                                 # apply menu item 0 (or pass a dict)
    print(h.findings)                          # any over-enumeration diagnostics
"""
from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent
_SRC = _ROOT / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from almoravid.actions import IllegalAction, apply_action          # noqa: E402
from almoravid.legal_moves import legal_moves as _legal_moves      # noqa: E402
from almoravid.scenarios import list_scenarios, load_scenario      # noqa: E402
from almoravid.state import GameState                              # noqa: E402

try:
    from almoravid import render as _render
except Exception:                       # pragma: no cover - render is optional
    _render = None


class Harness:
    """Drive one game. `findings` accumulates structured anomalies:
    {kind, move/action, code, detail, box, phase} for over-enumeration
    (a menu move the executor rejected) and invariant violations."""

    def __init__(self, scenario: str, seed: int = 0):
        if scenario not in list_scenarios():
            raise ValueError(f"unknown scenario {scenario!r}; "
                             f"choose from {list_scenarios()}")
        self.state: GameState = load_scenario(scenario, seed=seed)
        self.findings: list[dict] = []
        self._last_menu: list[dict] = []

    # -- discovery ------------------------------------------------------
    @staticmethod
    def scenarios() -> list[str]:
        return list_scenarios()

    # -- views ----------------------------------------------------------
    def _where(self) -> dict:
        m = self.state.meta
        return {"box": self.state.calendar.current_box, "phase": m.phase,
                "levy_step": m.levy_step, "campaign_step": m.campaign_step,
                "active": m.active_player,
                "active_lord": m.active_lord_id,
                "actions_remaining": m.actions_remaining}

    def briefing(self, mode: str = "verbose") -> str:
        """Plain-text state. Uses the engine's renderer (render_verbose /
        render_summary) when available; falls back to a compact summary."""
        if _render is not None:
            fn = "render_verbose" if mode == "verbose" else "render_summary"
            r = getattr(_render, fn, None) or getattr(_render, "render_summary", None)
            if callable(r):
                try:
                    return r(self.state)
                except Exception:
                    pass
        # Fallback compact briefing.
        w = self._where()
        lines = [f"box={w['box']} phase={w['phase']} "
                 f"levy={w['levy_step']} campaign={w['campaign_step']} "
                 f"active={w['active']} VP=C{self.state.score.christian}/"
                 f"M{self.state.score.muslim}"]
        for lid, l in self.state.lords.items():
            if l.cylinder.kind == "locale":
                lines.append(f"  {l.side[:1]} {lid} @{l.cylinder.locale_id}"
                             f"{' (inside)' if l.in_stronghold else ''} "
                             f"forces={dict(l.forces)} caps={l.capabilities}")
        return "\n".join(lines)

    def show(self, mode: str = "verbose") -> str:
        """Alias for briefing() — the readable per-side battle/board view."""
        return self.briefing(mode=mode)

    def start(self, scenario: str, seed: int = 0) -> "Harness":
        """(Re)start this harness on `scenario` (any id from scenarios(),
        including 'sagrajas'). Mutates and returns self so both
        `h.start('sagrajas', seed=1)` and `Harness.start(...)` styles work."""
        self.__init__(scenario, seed=seed)
        return self

    def pending(self) -> dict | None:
        return self.state.pending.model_dump() if self.state.pending else None

    # -- legal moves (validated palette) --------------------------------
    def legal(self, validate: bool = True) -> list[dict]:
        """Return the numbered legal-move menu. With validate=True (default),
        each candidate is probed on a deep copy; any the executor would
        reject is DROPPED and recorded in `findings` as an over-enumeration
        diagnostic (this should never happen in a correct engine)."""
        raw = _legal_moves(self.state)
        if not validate:
            self._last_menu = list(raw)
            return self._last_menu
        kept: list[dict] = []
        for m in raw:
            probe = copy.deepcopy(self.state)
            try:
                apply_action(probe, m)
            except IllegalAction as e:
                self.findings.append({
                    "kind": "over_enumeration", "move": m,
                    "code": e.code, "detail": str(e), **self._where()})
            except Exception as e:  # pragma: no cover
                self.findings.append({
                    "kind": "handler_exception", "move": m,
                    "detail": f"{type(e).__name__}: {e}", **self._where()})
            else:
                kept.append(m)
        self._last_menu = kept
        return kept

    # -- apply ----------------------------------------------------------
    def apply(self, choice) -> dict:
        """Apply a move: an int index into the last legal() menu, or an
        explicit action dict. Records invariant violations to `findings`."""
        if isinstance(choice, int):
            if not self._last_menu:
                self.legal()
            action = self._last_menu[choice]
        elif isinstance(choice, dict):
            action = choice
        else:
            raise TypeError("choice must be an int menu index or an action dict")
        try:
            result = apply_action(self.state, action)
        except IllegalAction as e:
            self.findings.append({"kind": "apply_rejected", "action": action,
                                  "code": e.code, "detail": str(e),
                                  **self._where()})
            raise
        errs = self.invariants()
        if errs:
            self.findings.append({"kind": "invariant_violation",
                                  "after": action.get("type"),
                                  "violations": errs, **self._where()})
        return result

    # -- invariants -----------------------------------------------------
    def invariants(self) -> list[str]:
        """Always-on sanity checks (cheap). A non-empty list is a bug."""
        s = self.state
        e: list[str] = []
        for lid, l in s.lords.items():
            if l.cylinder.kind == "locale" and l.cylinder.locale_id not in s.locales:
                e.append(f"{lid}: bad locale")
            if any(v < 0 for v in l.forces.values()):
                e.append(f"{lid}: negative forces")
            if any(v < 0 for v in l.assets.values()):
                e.append(f"{lid}: negative assets")
            if len(l.capabilities) > 2:
                e.append(f"{lid}: >2 this-lord caps")
        for lid, loc in s.locales.items():
            if not (0 <= loc.siege_yellow <= 4) or not (0 <= loc.siege_green <= 4):
                e.append(f"{lid}: siege out of range")
            if loc.conquered_markers and loc.jihad_markers:
                e.append(f"{lid}: both Conquered AND Jihad")
        if s.taifas_box_coin < 0 or s.taifas_box_vp < 0 or s.meta.actions_remaining < 0:
            e.append("negative counter")
        if s.pending is not None and s.pending.waiting_on != s.meta.active_player:
            e.append("pending/active desync")
        if s.pending is None:   # co-location: opposing field Lords sharing a Locale
            by: dict[str, set] = {}
            for lid, l in s.lords.items():
                if l.cylinder.kind == "locale" and not l.in_stronghold:
                    by.setdefault(l.cylinder.locale_id, set()).add(l.side)
            for loc, sides in by.items():
                if "christian" in sides and "muslim" in sides:
                    e.append(f"{loc}: opposing field Lords co-located")
        return e

    # -- persistence ----------------------------------------------------
    def save(self, path: str) -> None:
        Path(path).write_text(self.state.model_dump_json(indent=2))

    @classmethod
    def load(cls, path: str) -> "Harness":
        h = cls.__new__(cls)
        h.state = GameState.model_validate_json(Path(path).read_text())
        h.findings = []
        h._last_menu = []
        return h


def selfplay_smoke(scenario: str = "scenario_a_toledo_beset", seed: int = 1,
                   steps: int = 200) -> dict:
    """Drive a quick first-legal self-play run with the validated palette and
    invariants active. Returns a summary; any `findings` indicate a bug."""
    import random
    h = Harness(scenario, seed=seed)
    rng = random.Random(seed)
    n = 0
    for _ in range(steps):
        if h.state.meta.phase == "ended":
            break
        menu = h.legal()
        if not menu:
            h.findings.append({"kind": "zero_legal_moves", **h._where()})
            break
        h.apply(rng.randrange(len(menu)))
        n += 1
    return {"scenario": scenario, "seed": seed, "steps": n,
            "ended": h.state.meta.phase == "ended",
            "findings": h.findings}


if __name__ == "__main__":
    print("Scenarios:", Harness.scenarios())
    print(json.dumps(selfplay_smoke(steps=120), indent=2, default=str)[:1500])


def start(scenario: str, seed: int = 0) -> "Harness":
    """Module-level convenience: `start("sagrajas", seed=1)` -> Harness."""
    return Harness(scenario, seed=seed)
