"""Interactive 4.8 Feed/Pay/Disband choices: Greed Mule-discard (4.8.1)
and voluntary Pay before the mandatory at-limit Disband (4.8.2). With
`interactive_economy`, the optional player choices are exposed as
PendingDecisions; without it, the deterministic default runs."""
from __future__ import annotations

from almoravid.actions import apply_action
from almoravid.campaign import _greed_eligible_lords, _plan_target_size
from almoravid.legal_moves import legal_moves
from almoravid.scenarios import load_scenario
from tests._plan_helpers import legal_pad, step_levy


def _drive_to_campaign(s) -> None:
    apply_action(s, {"type": "begin_levy"})
    for _ in range(20):
        if s.meta.phase != "levy":
            return
        step_levy(s)


def _reveal_alfonso_card(s):
    _drive_to_campaign(s)
    apply_action(s, {"type": "begin_campaign"})
    _plan_target_size(s)
    apply_action(s, {"type": "plan_add_card", "side": "christian",
                     "plan_kind": "command", "lord_id": "alfonso"})
    legal_pad(s, "christian")
    legal_pad(s, "muslim")
    apply_action(s, {"type": "finalize_plan", "side": "christian"})
    apply_action(s, {"type": "finalize_plan", "side": "muslim"})
    apply_action(s, {"type": "command_reveal", "side": "christian"})


def _sm_box(s, lid):
    return next(sm.box for sm in s.calendar.service_markers
               if sm.lord_id == lid)


def test_greed_eligible_detects_unfeedable_mules() -> None:
    s = load_scenario("scenario_a_toledo_beset")
    al = s.lords["alfonso"]
    al.moved_fought = True
    al.forces = {"knights": 6}          # 6 units
    al.assets = {"mule": 3, "prov": 0, "loot": 0}  # 0 capacity -> all short
    elig = _greed_eligible_lords(s, "christian")
    rec = next(e for e in elig if e["lord_id"] == "alfonso")
    assert rec["mules"] == 3 and rec["discardable"] == 3


def test_interactive_greed_then_pay_then_disband_full_cascade() -> None:
    s = load_scenario("scenario_a_toledo_beset")
    _reveal_alfonso_card(s)
    al = s.lords["alfonso"]
    al.moved_fought = True
    al.forces = {"knights": 6}
    al.assets = {"mule": 2, "prov": 0, "loot": 0}   # 2 unfeedable mules

    # End the card interactively -> Greed prompt for the Christian side.
    apply_action(s, {"type": "end_card", "side": "christian",
                     "interactive_economy": True})
    assert s.pending is not None and s.pending.kind == "greed_mule_choice"
    assert s.pending.waiting_on == "christian"
    # legal_moves offers keep-none and discard-all-eligible.
    opts = legal_moves(s)
    assert {"type": "greed_mule_choice", "side": "christian",
            "discard_lords": ["alfonso"]} in opts

    # Choose to discard Alfonso's excess mules -> avoids the Unfed shift.
    apply_action(s, {"type": "greed_mule_choice", "side": "christian",
                     "discard_lords": ["alfonso"]})
    # Mules discarded; with 6 units and 0 mules, need 1 Provender -> still
    # short by 1 (no prov), but the 2-mule Unfed contribution is removed.
    assert s.lords["alfonso"].assets.get("mule", 0) == 0

    # The cascade proceeds to the Pay step (Christian first).
    assert s.pending is not None and s.pending.kind == "pay_before_disband"
    assert s.pending.waiting_on == "christian"
    pay_opts = legal_moves(s)
    assert {"type": "pay_before_disband", "side": "christian",
            "done": True} in pay_opts
    # Christian done -> Muslim Pay step.
    apply_action(s, {"type": "pay_before_disband", "side": "christian",
                     "done": True})
    assert s.pending is not None and s.pending.waiting_on == "muslim"
    # Muslim done -> Disband + finalize; pending cleared, card ended.
    res = apply_action(s, {"type": "pay_before_disband", "side": "muslim",
                           "done": True})
    assert s.pending is None
    assert s.meta.active_lord_id is None
    assert "finalize" in res


def test_interactive_keep_mules_matches_default_when_no_discard() -> None:
    """Choosing to discard nothing reproduces the synchronous default's
    Feed outcome (Mules kept, Unfed penalty applied)."""
    s = load_scenario("scenario_a_toledo_beset")
    _reveal_alfonso_card(s)
    al = s.lords["alfonso"]
    al.moved_fought = True
    al.forces = {"knights": 6}
    al.assets = {"mule": 2, "prov": 0, "loot": 0}
    apply_action(s, {"type": "end_card", "side": "christian",
                     "interactive_economy": True})
    apply_action(s, {"type": "greed_mule_choice", "side": "christian",
                     "discard_lords": []})
    # Default branch keeps all Mules (unlike the discard choice).
    assert s.lords["alfonso"].assets.get("mule", 0) == 2
    apply_action(s, {"type": "pay_before_disband", "side": "christian",
                     "done": True})
    res = apply_action(s, {"type": "pay_before_disband", "side": "muslim",
                           "done": True})
    assert s.pending is None and "finalize" in res


# --- Wastage (4.9.4) interactive choice -----------------------------------
def test_interactive_wastage_lets_owner_pick_the_discarded_item() -> None:
    from almoravid.campaign import _wastage_eligible_lords
    s = load_scenario("scenario_a_toledo_beset")
    # Force an end_campaign state synthetically: set the step and give
    # Alfonso (on map) an over-stock so Wastage triggers.
    s.meta.phase = "campaign"
    s.meta.campaign_step = "end_campaign"
    al = s.lords["alfonso"]
    al.assets = {"mule": 2, "loot": 1}     # two Mules -> eligible
    elig = _wastage_eligible_lords(s, "christian")
    rec = next(e for e in elig if e["lord_id"] == "alfonso")
    assert {"asset": "loot"} in rec["options"]   # count-1 Loot is discardable

    apply_action(s, {"type": "end_campaign", "interactive_wastage": True})
    assert s.pending is not None and s.pending.kind == "wastage_choice"
    assert s.pending.waiting_on == "christian"
    # Choose to discard the single Loot (NOT the default largest stack).
    apply_action(s, {"type": "wastage_choice", "side": "christian",
                     "discards": {"alfonso": {"asset": "loot"}}})
    assert s.lords["alfonso"].assets.get("loot", 0) == 0
    assert s.lords["alfonso"].assets.get("mule", 0) == 2   # mules untouched
    # After Christians, Muslims get their (possibly empty) Wastage step,
    # then end-Campaign completes and the pending is cleared.
    if s.pending is not None and s.pending.kind == "wastage_choice":
        apply_action(s, {"type": "wastage_choice", "side": "muslim",
                         "discards": {}})
    assert s.pending is None


def test_interactive_economy_baton_matches_synchronous() -> None:
    """After end_card, the card-to-card baton (active_player) must be the
    same whether the economy step ran synchronously or interactively."""
    # Synchronous reference.
    s1 = load_scenario("scenario_a_toledo_beset")
    _reveal_alfonso_card(s1)
    apply_action(s1, {"type": "end_card", "side": "christian"})
    ref_player = s1.meta.active_player

    # Interactive cascade (no greed-eligible Lords; just walk Pay -> done).
    s2 = load_scenario("scenario_a_toledo_beset")
    _reveal_alfonso_card(s2)
    apply_action(s2, {"type": "end_card", "side": "christian",
                      "interactive_economy": True})
    # No greed prompt expected here -> straight to Pay (christian).
    assert s2.pending is not None and s2.pending.kind == "pay_before_disband"
    apply_action(s2, {"type": "pay_before_disband", "side": "christian",
                      "done": True})
    apply_action(s2, {"type": "pay_before_disband", "side": "muslim",
                      "done": True})
    assert s2.pending is None
    assert s2.meta.active_player == ref_player
    assert s2.meta.campaign_step == s1.meta.campaign_step
