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


# ---- Besieged-Lord Sally (4.5.3): either side may Concede ------------------

def test_sally_besieged_lord_can_concede() -> None:
    """The sallying (Besieged) side Concedes -> the besieger wins."""
    from almoravid.battle import resolve_sally
    s = load_scenario("scenario_a_toledo_beset", seed=7)
    atk = BattleSide(side="muslim", role="attacker",
                     lord_ids=["al_mutamid"], forces={"knights": 4})
    dfd = BattleSide(side="christian", role="defender",
                     lord_ids=["alfonso"], forces={"knights": 4})
    result = resolve_sally(s, atk, dfd, attacker_concede_round=1)
    assert result.engagement == "sally"
    assert result.winner == "christian"
    assert len(result.rounds) == 1


def test_sally_besieger_can_concede() -> None:
    """The besieger (Defender) Concedes -> the sallying side wins."""
    from almoravid.battle import resolve_sally
    s = load_scenario("scenario_a_toledo_beset", seed=7)
    atk = BattleSide(side="muslim", role="attacker",
                     lord_ids=["al_mutamid"], forces={"knights": 4})
    dfd = BattleSide(side="christian", role="defender",
                     lord_ids=["alfonso"], forces={"knights": 4})
    result = resolve_sally(s, atk, dfd, defender_concede_round=1)
    assert result.winner == "muslim"
    assert len(result.rounds) == 1


# ---- Relief Sally (4.4.1): either side may Concede -------------------------

def _relief_setup(seed: int = 5):
    s = load_scenario("scenario_a_toledo_beset", seed=seed)
    s.lords["alfonso"].forces = {"knights": 4}        # relieving Marcher
    s.lords["al_mutamid"].forces = {"sergeants": 4}   # besieger
    return s


def test_relief_sally_relieving_side_can_concede() -> None:
    """Relieving side (Marchers + Sallyers = Attacker) Concedes ->
    the besieger wins."""
    from almoravid.battle import resolve_relief_sally
    s = _relief_setup()
    result, _lanes = resolve_relief_sally(
        s, ["alfonso"], [], ["al_mutamid"],
        besieger_side="muslim", locale_id="sahagun",
        attacker_concede_round=1)
    assert result.winner == "muslim"
    assert len(result.rounds) == 1


def test_relief_sally_besieger_can_concede() -> None:
    """Besieger (Defender) Concedes -> the relieving side wins."""
    from almoravid.battle import resolve_relief_sally
    s = _relief_setup()
    result, _lanes = resolve_relief_sally(
        s, ["alfonso"], [], ["al_mutamid"],
        besieger_side="muslim", locale_id="sahagun",
        defender_concede_round=1)
    assert result.winner == "christian"
    assert len(result.rounds) == 1


def test_relief_sally_concede_symmetric() -> None:
    """Opposite conceder -> opposite winner (both sides can Concede)."""
    from almoravid.battle import resolve_relief_sally
    s1 = _relief_setup()
    s2 = _relief_setup()
    w_atk, _ = resolve_relief_sally(
        s1, ["alfonso"], [], ["al_mutamid"], besieger_side="muslim",
        locale_id="sahagun", attacker_concede_round=1)
    w_dfd, _ = resolve_relief_sally(
        s2, ["alfonso"], [], ["al_mutamid"], besieger_side="muslim",
        locale_id="sahagun", defender_concede_round=1)
    assert {w_atk.winner, w_dfd.winner} == {"christian", "muslim"}


def test_relief_sally_no_concede_by_default() -> None:
    """Without a concede arg the relief sally runs to its normal end."""
    from almoravid.battle import resolve_relief_sally
    s = _relief_setup()
    s.lords["alfonso"].forces = {"knights": 8, "men_at_arms": 6}  # crush
    s.lords["al_mutamid"].forces = {"sergeants": 1}
    result, _lanes = resolve_relief_sally(
        s, ["alfonso"], [], ["al_mutamid"],
        besieger_side="muslim", locale_id="sahagun")
    assert not result.attacker.conceded and not result.defender.conceded
    assert result.winner == "christian"


# ---- Interactive (reactive, round-stepped) Concede ------------------------

def _drive_interactive(s, *, concede_at=None, conceder="defender"):
    """Drive an interactive Battle to completion. `concede_at` = the Round
    at which `conceder` declares Concede (reactively, after seeing prior
    Rounds); None = never concede. Returns the final result dict."""
    from almoravid.actions import apply_action
    r = apply_action(s, {"type": "cmd_battle", "side": "christian",
                         "interactive_concede": True})
    assert r["battle"] == "awaiting_concede"
    while s.pending is not None and s.pending.kind == "battle_concede":
        cur = s.pending.payload["round_idx"]
        act = {"type": "battle_concede", "side": "christian"}
        if concede_at is not None and cur == concede_at:
            act[f"{conceder}_concede"] = True
        r = apply_action(s, act)
        if "winner" in r:
            return r
    return r


def test_interactive_battle_pauses_for_concede() -> None:
    from almoravid.actions import apply_action
    s = _activate_alfonso(seed=3)
    r = apply_action(s, {"type": "cmd_battle", "side": "christian",
                         "interactive_concede": True})
    assert r["battle"] == "awaiting_concede"
    assert s.pending is not None and s.pending.kind == "battle_concede"
    assert s.pending.waiting_on == "christian" == s.meta.active_player


def test_interactive_legal_moves_offers_concede() -> None:
    from almoravid.actions import apply_action
    from almoravid.legal_moves import legal_moves
    s = _activate_alfonso(seed=3)
    apply_action(s, {"type": "cmd_battle", "side": "christian",
                     "interactive_concede": True})
    kinds = [m for m in legal_moves(s) if m["type"] == "battle_concede"]
    assert len(kinds) == 3
    assert any("attacker_concede" in m for m in kinds)
    assert any("defender_concede" in m for m in kinds)


def test_interactive_no_concede_matches_synchronous() -> None:
    """Driving the interactive Battle without ever conceding is byte-for-
    byte identical to the synchronous resolution (same RNG, same result)."""
    from almoravid.actions import apply_action
    for seed in (1, 3, 7, 11):
        s_sync = _activate_alfonso(seed=seed)
        r_sync = apply_action(s_sync, {"type": "cmd_battle",
                                       "side": "christian"})
        s_int = _activate_alfonso(seed=seed)
        r_int = _drive_interactive(s_int, concede_at=None)
        assert r_int["winner"] == r_sync["winner"]
        assert r_int["rounds"] == r_sync["rounds"]
        assert r_int["attacker_routed"] == r_sync["attacker_routed"]
        assert r_int["defender_routed"] == r_sync["defender_routed"]


def test_interactive_reactive_defender_concede_later_round() -> None:
    """The defender, having watched Rounds 1-2, reactively Concedes at the
    start of Round 3 -> the attacker (Christian) wins after 3 Rounds."""
    s = _activate_alfonso(seed=3)
    s.lords["alfonso"].forces = {"men_at_arms": 6}
    s.lords["al_mutamid"].forces = {"men_at_arms": 6}
    r = _drive_interactive(s, concede_at=3, conceder="defender")
    assert r["winner"] == "christian"
    assert r["rounds"] == 3
    assert s.pending is None or s.pending.kind != "battle_concede"


def test_interactive_reactive_attacker_concede_round1() -> None:
    s = _activate_alfonso(seed=3)
    s.lords["alfonso"].forces = {"men_at_arms": 6}
    s.lords["al_mutamid"].forces = {"men_at_arms": 6}
    r = _drive_interactive(s, concede_at=1, conceder="attacker")
    assert r["winner"] == "muslim"
    assert r["rounds"] == 1
