"""P-2 (combat playtest 2026-05-22): when the sole besieging Lord is
eliminated in COMBAT (Storm/Sally/Battle), the Stronghold "becomes free
of Enemy Lords" and its Siege/Bypass markers must be removed.

Rule 4.5.4 (Siege section): "Whenever a Besieged or Bypassed Stronghold
becomes free of Enemy Lords in the Locale, remove all Siege or Bypass
markers there." The F7 fix covered the Disband and March departure paths;
combat elimination (3.3.1 permanent removal inside apply_battle_losses)
was an uncovered path that left an orphaned Siege marker.
"""
from __future__ import annotations

from almoravid.battle import apply_battle_losses, BattleSide, BattleResult
from almoravid.scenarios import load_scenario
from almoravid.state import Cylinder


def test_storm_loss_eliminating_sole_besieger_clears_siege_marker() -> None:
    """Drive a real Scenario-A Storm to the point where Álvar (the only
    besieger at Toledo) is wiped out, and assert the siege marker clears."""
    from almoravid.actions import apply_action
    s = load_scenario("scenario_a_toledo_beset", seed=7)
    # Advance through Levy.
    apply_action(s, {"type": "begin_levy"})
    guard = 0
    while s.meta.phase == "levy" and guard < 60:
        # Process the mandatory AoW draw if owed, else pass.
        side = s.meta.active_player
        if (s.meta.levy_step == "arts_of_war"
                and not s.meta.aow_draw_done.get(side)):
            apply_action(s, {"type": "aow_draw", "side": side})
            for cid in list(s.decks.pending_draw.get(side, [])):
                apply_action(s, {"type": "aow_deploy_capability",
                                 "side": side, "card_id": cid,
                                 "lord_id": "alvar_fanez" if side == "christian"
                                 else "al_mutamid"})
        else:
            apply_action(s, {"type": "pass_step", "side": side})
        guard += 1
    assert s.meta.phase == "campaign"
    # Minimal legal plans (<=5 Pass).
    apply_action(s, {"lord_id": "alvar_fanez", "plan_kind": "command",
                     "side": "christian", "type": "plan_add_card"})
    apply_action(s, {"lord_id": "alfonso", "plan_kind": "command",
                     "side": "christian", "type": "plan_add_card"})
    for _ in range(5):
        apply_action(s, {"plan_kind": "pass", "side": "christian",
                         "type": "plan_add_card"})
    apply_action(s, {"side": "christian", "type": "finalize_plan"})
    apply_action(s, {"lord_id": "al_mutamid", "plan_kind": "command",
                     "side": "muslim", "type": "plan_add_card"})
    apply_action(s, {"lord_id": "al_mustain", "plan_kind": "command",
                     "side": "muslim", "type": "plan_add_card"})
    for _ in range(5):
        apply_action(s, {"plan_kind": "pass", "side": "muslim",
                         "type": "plan_add_card"})
    apply_action(s, {"side": "muslim", "type": "finalize_plan"})
    apply_action(s, {"side": "christian", "type": "command_reveal"})
    assert s.meta.active_lord_id == "alvar_fanez"
    assert s.locales["toledo"].siege_yellow == 1
    res = apply_action(s, {"side": "christian", "type": "cmd_storm"})
    # Álvar's 4-unit army vs a City (walls 1-4) + 6-unit garrison is wiped.
    assert s.lords["alvar_fanez"].cylinder.kind == "removed", res
    # The orphaned siege marker must be gone (4.5.4).
    assert s.locales["toledo"].siege_yellow == 0


def test_apply_battle_losses_clears_marker_on_permanent_removal() -> None:
    """Unit-level: a besieger reduced to zero Forces in apply_battle_losses
    triggers the orphaned-marker cleanup at his Locale."""
    s = load_scenario("scenario_a_toledo_beset", seed=1)
    av = s.lords["alvar_fanez"]
    assert av.cylinder.kind == "locale" and av.cylinder.locale_id == "toledo"
    s.locales["toledo"].siege_yellow = 2
    # Force Álvar to zero Forces so the 3.3.1 removal path fires.
    av.forces = {}
    av.routed_units = {}
    atk = BattleSide(side="christian", role="attacker",
                     lord_ids=["alvar_fanez"], forces={})
    deff = BattleSide(side="muslim", role="defender",
                      lord_ids=[], forces={})
    res = BattleResult(engagement="storm", attacker=atk, defender=deff,
                       winner="muslim", rounds=[])
    out = apply_battle_losses(s, res, {"losers": [
        {"lord_id": "alvar_fanez", "fate": "retreat"}]}, storm=True)
    assert out["alvar_fanez"].get("permanently_removed")
    assert s.lords["alvar_fanez"].cylinder.kind == "removed"
    assert s.locales["toledo"].siege_yellow == 0
