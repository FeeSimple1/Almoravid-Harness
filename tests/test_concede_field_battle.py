"""Open-field Battle Concede the Field (rule 4.4.2).

Regression tests for the fix that wires Concede into open-field Battles.
Unlike a Storm (4.5.2: only the Attacker may Concede, Round 2+), in an
open-field Battle EITHER side -- Attacker then Defender -- may Concede at
the start of any Round (from Round 1). Concede is pre-declared per side
via the `attacker_concede_round` / `defender_concede_round` arguments,
mirroring the Storm's `concede_after_round`.

Winner determination checks Concede BEFORE Rout, so these outcomes are
deterministic regardless of dice: the non-conceding side wins.
"""

from __future__ import annotations

from almoravid.actions import apply_action
from almoravid.battle import BattleSide, resolve_battle
from almoravid.scenarios import load_scenario
from almoravid.state import Cylinder
from tests._plan_helpers import legal_pad, step_levy


def _sides(seed: int = 7) -> tuple:
    s = load_scenario("scenario_a_toledo_beset", seed=seed)
    atk = BattleSide(side="christian", role="attacker",
                     lord_ids=["alfonso"], forces={"knights": 4})
    dfd = BattleSide(side="muslim", role="defender",
                     lord_ids=["al_mutamid"], forces={"sergeants": 4})
    return s, atk, dfd


# ---- resolver level: BOTH sides can Concede --------------------------------

def test_defender_can_concede_attacker_wins() -> None:
    """Defender Concedes at Round 1 -> Attacker (Christian) wins."""
    s, atk, dfd = _sides()
    result = resolve_battle(s, atk, dfd, defender_concede_round=1)
    assert result.winner == "christian"
    assert len(result.rounds) == 1  # Concede ends the Battle that Round


def test_attacker_can_concede_defender_wins() -> None:
    """Attacker Concedes at Round 1 -> Defender (Muslim) wins.

    This is the half the program was missing: the Attacker (and, above,
    the Defender) can now Concede an open-field Battle.
    """
    s, atk, dfd = _sides()
    result = resolve_battle(s, atk, dfd, attacker_concede_round=1)
    assert result.winner == "muslim"
    assert len(result.rounds) == 1


def test_concede_is_symmetric() -> None:
    """Same Array, opposite conceder -> opposite winner (refutes the
    'only one side may Concede' bug directly)."""
    s1, atk1, dfd1 = _sides()
    s2, atk2, dfd2 = _sides()
    w_atk_concedes = resolve_battle(s1, atk1, dfd1,
                                    attacker_concede_round=1).winner
    w_dfd_concedes = resolve_battle(s2, atk2, dfd2,
                                    defender_concede_round=1).winner
    assert {w_atk_concedes, w_dfd_concedes} == {"christian", "muslim"}


def test_concede_round_two_runs_two_rounds() -> None:
    """A Round-2 Concede plays Round 1 normally, then ends after Round 2."""
    s, atk, dfd = _sides()
    # Strong, balanced forces so neither side fully Routs in one Round.
    atk.forces = {"knights": 8}
    dfd.forces = {"knights": 8}
    result = resolve_battle(s, atk, dfd, defender_concede_round=2)
    assert result.winner == "christian"
    assert len(result.rounds) == 2


def test_no_concede_by_default() -> None:
    """Without a concede arg, neither side Concedes (battle decided by
    Rout / max_rounds as before -- behaviour unchanged)."""
    s, atk, dfd = _sides()
    atk.forces = {"knights": 6, "men_at_arms": 4}
    dfd.forces = {"sergeants": 1}
    result = resolve_battle(s, atk, dfd)
    assert result.winner == "christian"  # overwhelming attacker, by Rout
    assert not atk.conceded and not dfd.conceded


# ---- action layer: Concede honored through the live cmd_battle flow --------

def _activate_alfonso(seed: int):
    s = load_scenario("scenario_a_toledo_beset", seed=seed)
    apply_action(s, {"type": "begin_levy"})
    for _ in range(15):
        if s.meta.phase != "levy":
            break
        step_levy(s)
    apply_action(s, {"type": "plan_add_card", "side": "christian",
                     "plan_kind": "command", "lord_id": "alfonso"})
    legal_pad(s, "christian")
    legal_pad(s, "muslim")
    apply_action(s, {"type": "finalize_plan", "side": "christian"})
    apply_action(s, {"type": "finalize_plan", "side": "muslim"})
    for _ in range(20):
        if s.meta.active_lord_id == "alfonso":
            break
        apply_action(s, {"type": "command_reveal", "side": s.meta.active_player})
        if s.meta.active_lord_id and s.meta.active_lord_id != "alfonso":
            apply_action(s, {"type": "end_card", "side": s.meta.active_player})
    else:
        raise RuntimeError("could not activate alfonso")
    # Set up a clean 1-v-1 Battle at Sahagun.
    s.lords["al_mutamid"].cylinder = Cylinder(kind="locale", locale_id="sahagun")
    s.lords["pedro_ansurez"].cylinder = Cylinder(kind="locale", locale_id="leon")
    s.lords["garcia_ordonez"].cylinder = Cylinder(kind="locale", locale_id="burgos")
    return s


def test_cmd_battle_defender_concede_via_action() -> None:
    s = _activate_alfonso(seed=3)
    r = apply_action(s, {"type": "cmd_battle", "side": "christian",
                         "defender_concede_round": 1})
    assert r["winner"] == "christian"


def test_cmd_battle_attacker_concede_via_action() -> None:
    s = _activate_alfonso(seed=3)
    r = apply_action(s, {"type": "cmd_battle", "side": "christian",
                         "attacker_concede_round": 1})
    assert r["winner"] == "muslim"


def test_cmd_battle_bad_concede_arg_rejected() -> None:
    s = _activate_alfonso(seed=3)
    try:
        apply_action(s, {"type": "cmd_battle", "side": "christian",
                         "attacker_concede_round": 0})
    except Exception as e:  # IllegalAction
        assert "concede" in str(e).lower()
    else:
        raise AssertionError("expected rejection of concede round 0")
