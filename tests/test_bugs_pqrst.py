"""Bug-hunt pass 4: regression tests for Bugs P, Q, R, S, T."""

from __future__ import annotations

import pytest

from almoravid.actions import IllegalAction, apply_action
from almoravid.battle import (
    BattleResult, BattleSide,
    _consume_camp_attack,
    apply_aftermath,
    apply_retreat_aftermath,
    init_m7_cap,
)
from almoravid.scenarios import load_scenario
from almoravid.state import Cylinder, PendingDecision


# ---------------------------------------------------------------------------
# Bug P: C7 dual effect — opt-out on Christian Retreat
# ---------------------------------------------------------------------------


def test_bug_p_c7_skips_service_shift_when_christian_retreats() -> None:
    """Christian Lord Retreats with C7 in this_levy_events and at least
    one Asset to pay — Service marker stays put, asset count decreases
    by 1."""
    s = load_scenario("scenario_a_toledo_beset", seed=7)
    # Park Alfonso at a region locale (no Stronghold -> no Withdraw)
    # so the Retreat branch fires.
    s.lords["alfonso"].cylinder = Cylinder(kind="locale",
                                           locale_id="transduero")
    s.lords["alfonso"].in_stronghold = False
    # Give Alfonso predictable assets.
    s.lords["alfonso"].assets = {"loot": 1, "coin": 5}
    # Hold C7.
    s.decks.this_levy_events["christian"] = ["C7"]
    # Move all Muslims away so retreat target is clean.
    for lid, l in s.lords.items():
        if l.side == "muslim":
            l.cylinder = Cylinder(kind="locale", locale_id="sevilla")
    box_before = next(sm.box for sm in s.calendar.service_markers
                      if sm.lord_id == "alfonso")
    atk = BattleSide(side="christian", role="attacker",
                     lord_ids=["alfonso"], forces={})
    dfd = BattleSide(side="muslim", role="defender",
                     lord_ids=["al_mutamid"], forces={"knights": 1})
    result = BattleResult(engagement="battle", attacker=atk, defender=dfd,
                          winner="muslim")
    summary = apply_retreat_aftermath(s, result)
    entry = summary["losers"][0]
    assert entry["fate"] == "retreat"
    assert entry.get("c7_opt_out") is True
    assert entry["service_shift_boxes"] == 0
    box_after = next(sm.box for sm in s.calendar.service_markers
                     if sm.lord_id == "alfonso")
    assert box_after == box_before
    # Loot drained first (ASSET_PAY_ORDER preference).
    assert s.lords["alfonso"].assets.get("loot", 0) == 0
    assert s.lords["alfonso"].assets.get("coin", 0) == 5


def test_bug_p_c7_no_optout_without_asset() -> None:
    """If retreating Christian Lord has zero Assets, C7 opt-out cannot
    fire — Service shift proceeds normally."""
    s = load_scenario("scenario_a_toledo_beset", seed=7)
    s.lords["alfonso"].cylinder = Cylinder(kind="locale",
                                           locale_id="transduero")
    s.lords["alfonso"].in_stronghold = False
    s.lords["alfonso"].assets = {}  # no assets to pay
    s.decks.this_levy_events["christian"] = ["C7"]
    for lid, l in s.lords.items():
        if l.side == "muslim":
            l.cylinder = Cylinder(kind="locale", locale_id="sevilla")
    atk = BattleSide(side="christian", role="attacker",
                     lord_ids=["alfonso"], forces={})
    dfd = BattleSide(side="muslim", role="defender",
                     lord_ids=["al_mutamid"], forces={"knights": 1})
    result = BattleResult(engagement="battle", attacker=atk, defender=dfd,
                          winner="muslim")
    summary = apply_retreat_aftermath(s, result)
    entry = summary["losers"][0]
    assert entry.get("c7_opt_out") is not True
    assert entry["service_shift_boxes"] in (1, 2, 3)


def test_bug_p_c7_not_applicable_to_muslim_retreat() -> None:
    """C7 is Christian-only; a Muslim Lord retreating gets no opt-out."""
    s = load_scenario("scenario_a_toledo_beset", seed=7)
    s.lords["al_mutamid"].cylinder = Cylinder(kind="locale",
                                              locale_id="iberico")
    s.lords["al_mutamid"].in_stronghold = False
    s.lords["al_mutamid"].assets = {"loot": 5}
    s.decks.this_levy_events["christian"] = ["C7"]
    for lid, l in s.lords.items():
        if l.side == "christian":
            l.cylinder = Cylinder(kind="locale", locale_id="sevilla")
    atk = BattleSide(side="christian", role="attacker",
                     lord_ids=["alfonso"], forces={"knights": 1})
    dfd = BattleSide(side="muslim", role="defender",
                     lord_ids=["al_mutamid"], forces={})
    result = BattleResult(engagement="battle", attacker=atk, defender=dfd,
                          winner="christian")
    summary = apply_retreat_aftermath(s, result)
    entry = summary["losers"][0]
    assert entry.get("c7_opt_out") is not True
    # Muslim's loot untouched by C7.
    assert s.lords["al_mutamid"].assets.get("loot", 0) == 5


def test_bug_p_c7_survives_cancel_until_engagement_end() -> None:
    """C7 stays in this_levy_events after cancelling M2 so the Retreat
    opt-out half is also available, then apply_aftermath discards it."""
    s = load_scenario("scenario_a_toledo_beset", seed=5)
    s.decks.this_levy_events["christian"] = ["C7"]
    s.decks.this_campaign_events["muslim"] = ["M2"]
    atk = BattleSide(side="christian", role="attacker",
                     lord_ids=["alfonso"], forces={"knights": 2})
    dfd = BattleSide(side="muslim", role="defender",
                     lord_ids=["al_mutamid"], forces={"sergeants": 2})
    result = BattleResult(engagement="battle", attacker=atk, defender=dfd)
    _consume_camp_attack(s, atk, dfd, result)
    # Mid-Battle: C7 still in this_levy_events; M2 discarded.
    assert "C7" in s.decks.this_levy_events.get("christian", [])
    assert "M2" in s.decks.discard
    # apply_aftermath at engagement end will clear and discard.
    apply_aftermath(s, result)
    assert "C7" in s.decks.discard


# ---------------------------------------------------------------------------
# Bug Q: Avoid Battle requires Unladen
# ---------------------------------------------------------------------------


def test_bug_q_laden_defender_cannot_avoid() -> None:
    s = load_scenario("scenario_a_toledo_beset", seed=11)
    s.pending = PendingDecision(
        kind="march_arrival_response", waiting_on="muslim",
        payload={
            "locale_id": "sevilla", "from_locale_id": "cordoba",
            "via_way_type": "road",
            "active_lord_id": "alfonso", "active_side": "christian",
            "defender_lord_ids": ["al_mutamid"],
        },
    )
    s.meta.active_player = "muslim"
    # Make Al-Mutamid heavily Laden (lots of Provender, no carts).
    s.lords["al_mutamid"].cylinder = Cylinder(kind="locale",
                                              locale_id="sevilla")
    s.lords["al_mutamid"].in_stronghold = False
    s.lords["al_mutamid"].assets = {"prov": 10}  # way over transport
    s.lords["al_mutamid"].forces = {"sergeants": 1}
    with pytest.raises(IllegalAction) as ei:
        # Use a road neighbor of sevilla that isn't cordoba.
        from almoravid.map import neighbors_via
        target = [n for n in neighbors_via("sevilla", "road")
                  if n != "cordoba"][0]
        apply_action(s, {"type": "respond_avoid_battle", "side": "muslim",
                         "target_locale_id": target, "way_type": "road"})
    assert ei.value.code == "laden_blocks_avoid"


# ---------------------------------------------------------------------------
# Bug R: permanent removal sets cylinder = removed
# ---------------------------------------------------------------------------


def test_bug_r_permanent_removal_sets_cylinder_removed() -> None:
    """A losing Lord with no Withdraw and no Retreat option must be
    Removed — cylinder.kind == 'removed' so subsequent scans ignore
    the Lord."""
    s = load_scenario("scenario_a_toledo_beset", seed=7)
    # Engineer a no-retreat trap: park al_mutamid at a Locale whose
    # every neighbor either contains a Christian Lord or is the
    # Approach origin AND is a non-Friendly Stronghold so Withdraw
    # also fails. Simplest: synthesize a result with engagement
    # 'battle' and skip the retreat_target search by saturating
    # every neighbor with a Christian Lord (no friendly stronghold).
    s.lords["al_mutamid"].cylinder = Cylinder(kind="locale", locale_id="leon")
    s.lords["al_mutamid"].in_stronghold = False
    from almoravid.map import neighbors_via
    # Put a Christian Lord at every neighbor of leon (road + pass).
    christian_lords = [lid for lid, l in s.lords.items()
                       if l.side == "christian"]
    blockers = christian_lords[:8]
    nbrs = set()
    for wt in ("road", "pass"):
        nbrs.update(neighbors_via("leon", wt))
    nbrs = list(nbrs)
    for i, nbr in enumerate(nbrs):
        if i < len(blockers):
            s.lords[blockers[i]].cylinder = Cylinder(
                kind="locale", locale_id=nbr)
            s.lords[blockers[i]].in_stronghold = False
    atk = BattleSide(side="christian", role="attacker",
                     lord_ids=["alfonso"], forces={"knights": 1})
    dfd = BattleSide(side="muslim", role="defender",
                     lord_ids=["al_mutamid"], forces={})
    result = BattleResult(engagement="battle", attacker=atk, defender=dfd,
                          winner="christian")
    summary = apply_retreat_aftermath(s, result)
    entry = summary["losers"][0]
    assert entry["fate"] == "removed"
    assert s.lords["al_mutamid"].cylinder.kind == "removed"


# ---------------------------------------------------------------------------
# Bug S: Avoid destination check mirrors trigger (Bypassed enemy OK)
# ---------------------------------------------------------------------------


def test_bug_s_avoid_destination_allows_bypassed_enemy() -> None:
    """A destination containing only a Bypassed enemy Lord should NOT
    block Avoid Battle — matches the trigger's filter."""
    from almoravid.map import neighbors_via
    s = load_scenario("scenario_a_toledo_beset", seed=11)
    # Pick sevilla as the Approach Locale and find a road neighbor
    # to use as the Avoid target.
    nbrs = [n for n in neighbors_via("sevilla", "road") if n != "cordoba"]
    target = nbrs[0]
    # Park a Christian Lord at `target`, then mark them Bypassed by
    # adding a bypass marker on the locale (representing they were
    # Bypassed earlier).
    christian_at_target = next(
        lid for lid, l in s.lords.items() if l.side == "christian")
    s.lords[christian_at_target].cylinder = Cylinder(
        kind="locale", locale_id=target)
    # Bug S regression: is_bypassed requires the Lord to be
    # in_stronghold AND the opposing-side bypass flag set.
    s.lords[christian_at_target].in_stronghold = True
    # bypass_green is the Muslim-Bypassed-Christian flag in our scheme.
    s.locales[target].bypass_green = True
    s.pending = PendingDecision(
        kind="march_arrival_response", waiting_on="muslim",
        payload={
            "locale_id": "sevilla", "from_locale_id": "cordoba",
            "via_way_type": "road",
            "active_lord_id": "alfonso", "active_side": "christian",
            "defender_lord_ids": ["al_mutamid"],
        },
    )
    s.meta.active_player = "muslim"
    s.lords["al_mutamid"].cylinder = Cylinder(kind="locale",
                                              locale_id="sevilla")
    s.lords["al_mutamid"].in_stronghold = False
    s.lords["al_mutamid"].assets = {}  # Unladen
    res = apply_action(s, {"type": "respond_avoid_battle", "side": "muslim",
                           "target_locale_id": target, "way_type": "road"})
    assert res["avoided_to"] == target


# ---------------------------------------------------------------------------
# Bug T: M7 boost cap binds — second-Round consultations beyond cap skip
# ---------------------------------------------------------------------------


def test_bug_t_m7_cap_binds_after_two_lords_worth() -> None:
    """A Muslim BattleSide with three Lords contributing 4+3+2 MaA
    units should cap M7 at 4+3=7 boost consultations. The 8th and
    later consultations get NO +1 Armor."""
    s = load_scenario("scenario_a_toledo_beset", seed=99)
    # Synthesize three Muslim Lords with MaA counts of 4, 3, 2.
    # Reuse existing Muslim Lords' state.
    muslims = [lid for lid, l in s.lords.items() if l.side == "muslim"][:3]
    for lid, n in zip(muslims, [4, 3, 2]):
        s.lords[lid].forces = {"men_at_arms": n}
        s.lords[lid].cylinder = Cylinder(kind="locale", locale_id="sevilla")
        s.lords[lid].in_stronghold = False
    s.decks.this_levy_events["muslim"] = ["M7"]
    dfd = BattleSide(side="muslim", role="defender",
                     lord_ids=muslims, forces={"men_at_arms": 9})
    init_m7_cap(s, dfd)
    # Cap = 4 + 3 = 7
    assert dfd.m7_boosts_remaining == 7


def test_bug_t_m7_cap_zero_when_not_held() -> None:
    s = load_scenario("scenario_a_toledo_beset", seed=99)
    dfd = BattleSide(side="muslim", role="defender",
                     lord_ids=["al_mutamid"], forces={"men_at_arms": 5})
    init_m7_cap(s, dfd)  # M7 not held -> no init
    assert dfd.m7_boosts_remaining == 0


def test_bug_t_m7_cap_zero_for_christian_side() -> None:
    s = load_scenario("scenario_a_toledo_beset", seed=99)
    s.decks.this_levy_events["muslim"] = ["M7"]
    atk = BattleSide(side="christian", role="attacker",
                     lord_ids=["alfonso"], forces={"knights": 4})
    init_m7_cap(s, atk)
    assert atk.m7_boosts_remaining == 0
