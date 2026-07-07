"""Coverage backfill for the AOW_AUDIT "untested-but-believed-correct"
capability effects: M22 War Drums extra Provender, C1/M1 Battering Ram
(counts-as-2 Lords + Surrender-die reroll), M13 Siege Towers (Muslim
side gating)."""
from __future__ import annotations

import almoravid.rng as R
from almoravid.actions import apply_action
from almoravid.scenarios import load_scenario
from almoravid.state import CardInPlay, Cylinder
from tests._plan_helpers import legal_pad, step_levy


def _activate_lord(scenario, lord_id, seed=1):
    s = load_scenario(scenario, seed=seed)
    side = s.lords[lord_id].side
    apply_action(s, {"type": "begin_levy"})
    for _ in range(15):
        if s.meta.phase != "levy":
            break
        step_levy(s)
    apply_action(s, {"type": "plan_add_card", "side": side,
                     "plan_kind": "command", "lord_id": lord_id})
    legal_pad(s, side)
    other = "muslim" if side == "christian" else "christian"
    legal_pad(s, other)
    apply_action(s, {"type": "finalize_plan", "side": "christian"})
    apply_action(s, {"type": "finalize_plan", "side": "muslim"})
    for _ in range(20):
        if s.meta.active_lord_id == lord_id:
            return s
        apply_action(s, {"type": "command_reveal",
                         "side": s.meta.active_player})
        if s.meta.active_lord_id and s.meta.active_lord_id != lord_id:
            apply_action(s, {"type": "end_card",
                             "side": s.meta.active_player})
    raise RuntimeError(f"Could not activate {lord_id}")


def _deploy(s, card, side):
    s.decks.capabilities_in_play.append(
        CardInPlay(card_id=card, scope="side_wide", owner_side=side))


# --- M22 War Drums: "Yusuf, Sir, and Muslim Lieutenants Ravage for 1
# --- extra Prov" (Arts of War ref M22 capability half).

def test_m22_war_drums_yusuf_ravages_extra_prov() -> None:
    s = _activate_lord("scenario_a_toledo_beset", "al_mutamid")
    _deploy(s, "M22", "muslim")
    yus = s.lords["yusuf"]
    # Swap the active Lord: reuse al_mutamid's activation for Yusuf.
    s.meta.active_lord_id = "yusuf"
    yus.cylinder = Cylinder(kind="locale", locale_id="coria")
    yus.in_stronghold = False
    yus.assets = {}
    s.locales["coria"].ravaged = "none"
    apply_action(s, {"type": "cmd_ravage", "side": "muslim"})
    # Stronghold Ravage: +1 Loot, +1 Prov normal, +1 Prov War Drums.
    assert yus.assets.get("loot") == 1
    assert yus.assets.get("prov") == 2


def test_m22_war_drums_not_for_plain_taifa_lord() -> None:
    s = _activate_lord("scenario_a_toledo_beset", "al_mutamid")
    _deploy(s, "M22", "muslim")
    mut = s.lords["al_mutamid"]
    mut.cylinder = Cylinder(kind="locale", locale_id="coria")
    mut.in_stronghold = False
    mut.assets = {}
    assert not mut.is_lieutenant
    s.locales["coria"].ravaged = "none"
    apply_action(s, {"type": "cmd_ravage", "side": "muslim"})
    # Normal Stronghold Ravage only: no War Drums bonus.
    assert mut.assets.get("loot") == 1
    assert mut.assets.get("prov") == 1


# --- C1 Battering Ram: "This Lord at Siege counts as 2 Lords and may
# --- reroll 1 Surrender die per Christian Siege action".

def test_c1_battering_ram_counts_as_two_lords_for_siegeworks() -> None:
    """A LONE Lord with Battering Ram at a capacity-2 Town CAN add a
    Siegeworks marker (1 + 1 = 2 >= 2)."""
    s = _activate_lord("scenario_a_toledo_beset", "alvar_fanez")
    al = s.lords["alvar_fanez"]
    al.cylinder = Cylinder(kind="locale", locale_id="jativa")  # Town, cap 2
    al.capabilities = ["C1"]
    s.locales["jativa"].siege_yellow = 1
    r = apply_action(s, {"type": "cmd_siege", "side": "christian",
                         "surrender": False})
    assert r["siegeworks"] is True and r["placed"] == 1
    assert s.locales["jativa"].siege_yellow == 2


def test_c1_battering_ram_rerolls_failed_surrender_die(monkeypatch) -> None:
    """Town (Value 1, one Surrender die), 3 Siege markers -> threshold
    3. Die "5" fails; the Battering Ram reroll "2" succeeds -> the
    Stronghold Surrenders and is Conquered."""
    s = _activate_lord("scenario_a_toledo_beset", "alvar_fanez")
    al = s.lords["alvar_fanez"]
    al.cylinder = Cylinder(kind="locale", locale_id="jativa")
    al.capabilities = ["C1"]
    s.locales["jativa"].siege_yellow = 3

    queue = [5, 2]

    def scripted(state):
        v = queue.pop(0)
        state.meta.rng_state += 1
        return v

    monkeypatch.setattr(R, "roll_d6", scripted)
    r = apply_action(s, {"type": "cmd_siege", "side": "christian",
                         "surrender": True})
    assert not queue
    assert r["surrender"]["dice"] == [2]      # the rerolled die
    assert r["surrender"]["succeeded"] is True
    assert s.locales["jativa"].conquered_markers == 1


# --- M13 Siege Towers: Muslim twin of C6 (Walls -1 from Round 2).

def test_m13_siege_towers_gates_muslim_attacker() -> None:
    from almoravid.battle import BattleSide, _storm_setup
    s = load_scenario("scenario_a_toledo_beset", seed=1)
    mut = s.lords["al_mutamid"]
    mut.cylinder = Cylinder(kind="locale", locale_id="toledo")
    mut.in_stronghold = False
    mut.capabilities = ["M13"]
    s.lords["alfonso"].cylinder = Cylinder(kind="locale",
                                           locale_id="toledo")
    s.lords["alfonso"].in_stronghold = True
    s.locales["toledo"].siege_green = 2
    atk = BattleSide(side="muslim", role="attacker",
                     lord_ids=["al_mutamid"], forces={"men_at_arms": 2})
    dfd = BattleSide(side="christian", role="defender",
                     lord_ids=["alfonso"], forces={"militia": 1})
    ss, _mr = _storm_setup(s, atk, dfd)
    assert ss["siege_towers"] is True
    # And a CHRISTIAN attacker holding M13 gains nothing (wrong card).
    s2 = load_scenario("scenario_a_toledo_beset", seed=1)
    s2.lords["alvar_fanez"].cylinder = Cylinder(kind="locale",
                                                locale_id="toledo")
    s2.lords["alvar_fanez"].capabilities = ["M13"]
    s2.lords["al_mutamid"].cylinder = Cylinder(kind="locale",
                                               locale_id="toledo")
    s2.lords["al_mutamid"].in_stronghold = True
    s2.locales["toledo"].siege_yellow = 2
    atk2 = BattleSide(side="christian", role="attacker",
                      lord_ids=["alvar_fanez"], forces={"knights": 1})
    dfd2 = BattleSide(side="muslim", role="defender",
                      lord_ids=["al_mutamid"], forces={"militia": 1})
    ss2, _ = _storm_setup(s2, atk2, dfd2)
    assert ss2["siege_towers"] is False
