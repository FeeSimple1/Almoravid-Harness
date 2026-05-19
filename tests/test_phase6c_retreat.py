"""Phase 6c: Retreat aftermath Service-shift roll (rule 4.4.3).

Covers:
  - Losing Lord at a Friendly Stronghold Withdraws (no Service shift,
    no movement, in_stronghold flipped).
  - Losing Lord with no Stronghold but an adjacent clean Locale
    Retreats and rolls 1d6 for Service shift (1-2: 1 box, 3-4: 2,
    5-6: 3).
  - Losing Lord with neither option is permanently removed.
  - Defender cannot Retreat along the Way the Attackers came from
    (when approach context is provided).
  - Pattern 2 mirror: helper fires symmetrically for attacker-lost and
    defender-lost cases.
"""

from __future__ import annotations

from almoravid.battle import (
    BattleResult,
    BattleSide,
    apply_aftermath,
    apply_retreat_aftermath,
)
from almoravid.map import neighbors_via
from almoravid.scenarios import load_scenario
from almoravid.state import Cylinder


# ---------------------------------------------------------------------------
# Withdraw: Friendly Stronghold at Battle Locale, capacity available.
# ---------------------------------------------------------------------------


def test_loser_withdraws_into_friendly_stronghold() -> None:
    """Al-Mutamid loses at sevilla (his Seat — Friendly). He should
    Withdraw inside the City Stronghold, no Service shift, no move."""
    s = load_scenario("scenario_a_toledo_beset", seed=7)
    s.lords["al_mutamid"].cylinder = Cylinder(kind="locale",
                                              locale_id="sevilla")
    s.lords["al_mutamid"].in_stronghold = False
    # Synthetic result: Christian wins, Al-Mutamid (defender) loses.
    atk = BattleSide(side="christian", role="attacker",
                     lord_ids=["alfonso"], forces={"knights": 1})
    dfd = BattleSide(side="muslim", role="defender",
                     lord_ids=["al_mutamid"], forces={})
    result = BattleResult(engagement="battle", attacker=atk, defender=dfd,
                          winner="christian")
    box_before = next(sm.box for sm in s.calendar.service_markers
                      if sm.lord_id == "al_mutamid")
    summary = apply_retreat_aftermath(s, result)
    assert summary["losers"][0]["fate"] == "withdraw"
    assert s.lords["al_mutamid"].in_stronghold is True
    assert s.lords["al_mutamid"].cylinder.locale_id == "sevilla"
    box_after = next(sm.box for sm in s.calendar.service_markers
                     if sm.lord_id == "al_mutamid")
    assert box_after == box_before  # Withdraw does NOT shift Service.


# ---------------------------------------------------------------------------
# Retreat: no Stronghold available, neighbor clean; rolls 1d6.
# ---------------------------------------------------------------------------


def test_loser_retreats_to_neighbor_and_shifts_service() -> None:
    """Place loser in a non-Stronghold region (or unfriendly territory)
    where Withdraw is impossible but Retreat is."""
    s = load_scenario("scenario_a_toledo_beset", seed=7)
    # Put al_mutamid at jerez (next to sevilla) — Muslim-friendly Town
    # but al_mutamid's Friendly status depends on territory. Use a
    # non-stronghold region neighbor of huelva: 'algarve' if such a
    # region exists. Easier: park the Lord at leon (Christian, so
    # NOT Friendly for Muslim defender — Withdraw refused).
    s.lords["al_mutamid"].cylinder = Cylinder(kind="locale", locale_id="leon")
    s.lords["al_mutamid"].in_stronghold = False
    # Move all Christian Lords far away so the neighbor is clean.
    for lid, l in s.lords.items():
        if l.side == "christian":
            l.cylinder = Cylinder(kind="locale", locale_id="sevilla")
    atk = BattleSide(side="christian", role="attacker",
                     lord_ids=["alfonso"], forces={"knights": 1})
    dfd = BattleSide(side="muslim", role="defender",
                     lord_ids=["al_mutamid"], forces={})
    result = BattleResult(engagement="battle", attacker=atk, defender=dfd,
                          winner="christian")
    box_before = next(sm.box for sm in s.calendar.service_markers
                      if sm.lord_id == "al_mutamid")
    summary = apply_retreat_aftermath(s, result)
    entry = summary["losers"][0]
    assert entry["fate"] == "retreat"
    assert entry["service_shift_boxes"] in (1, 2, 3)
    assert entry["service_roll"] in range(1, 7)
    expected_map = {1: 1, 2: 1, 3: 2, 4: 2, 5: 3, 6: 3}
    assert entry["service_shift_boxes"] == expected_map[entry["service_roll"]]
    box_after = next(sm.box for sm in s.calendar.service_markers
                     if sm.lord_id == "al_mutamid")
    # box_after may be lower OR Lord may be off-edge (box_before
    # could be small enough). At least one of those must hold.
    moved_off = "al_mutamid" in s.calendar.off_left_service
    assert moved_off or box_after == box_before - entry["service_shift_boxes"]


def test_retreat_service_shift_is_deterministic_per_seed() -> None:
    """Same seed -> same roll outcome."""
    def _run():
        s = load_scenario("scenario_a_toledo_beset", seed=42)
        s.lords["al_mutamid"].cylinder = Cylinder(
            kind="locale", locale_id="leon")
        s.lords["al_mutamid"].in_stronghold = False
        for lid, l in s.lords.items():
            if l.side == "christian":
                l.cylinder = Cylinder(kind="locale", locale_id="sevilla")
        atk = BattleSide(side="christian", role="attacker",
                         lord_ids=["alfonso"], forces={"knights": 1})
        dfd = BattleSide(side="muslim", role="defender",
                         lord_ids=["al_mutamid"], forces={})
        result = BattleResult(engagement="battle", attacker=atk, defender=dfd,
                              winner="christian")
        return apply_retreat_aftermath(s, result)
    r1 = _run()
    r2 = _run()
    assert r1["losers"][0]["service_roll"] == r2["losers"][0]["service_roll"]


# ---------------------------------------------------------------------------
# Defender-blocked Way: cannot Retreat along the Way the Attackers used.
# ---------------------------------------------------------------------------


def test_defender_cannot_retreat_along_approach_way() -> None:
    """If approach_from_locale + way provided, defender Retreat skips
    that neighbor."""
    s = load_scenario("scenario_a_toledo_beset", seed=7)
    s.lords["al_mutamid"].cylinder = Cylinder(kind="locale", locale_id="leon")
    s.lords["al_mutamid"].in_stronghold = False
    for lid, l in s.lords.items():
        if l.side == "christian":
            l.cylinder = Cylinder(kind="locale", locale_id="sevilla")
    nbrs = neighbors_via("leon", "road")
    blocked_neighbor = nbrs[0]
    atk = BattleSide(side="christian", role="attacker",
                     lord_ids=["alfonso"], forces={"knights": 1})
    dfd = BattleSide(side="muslim", role="defender",
                     lord_ids=["al_mutamid"], forces={})
    result = BattleResult(engagement="battle", attacker=atk, defender=dfd,
                          winner="christian")
    summary = apply_retreat_aftermath(
        s, result,
        approach_from_locale=blocked_neighbor,
        approach_way_type="road",
    )
    entry = summary["losers"][0]
    if entry["fate"] == "retreat":
        assert entry["retreat_to"] != blocked_neighbor


# ---------------------------------------------------------------------------
# Pattern 2 mirror: attacker-lost case fires the helper too.
# ---------------------------------------------------------------------------


def test_attacker_loss_triggers_retreat_aftermath() -> None:
    s = load_scenario("scenario_a_toledo_beset", seed=7)
    s.lords["alfonso"].cylinder = Cylinder(kind="locale", locale_id="leon")
    s.lords["alfonso"].in_stronghold = False
    # Move Muslims far away so retreat target is clean.
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
    assert summary["losers"]
    assert summary["losers"][0]["lord_id"] == "alfonso"


# ---------------------------------------------------------------------------
# Stalemate winner=None: no aftermath fires.
# ---------------------------------------------------------------------------


def test_stalemate_winner_none_no_aftermath() -> None:
    s = load_scenario("scenario_a_toledo_beset", seed=7)
    atk = BattleSide(side="christian", role="attacker",
                     lord_ids=["alfonso"], forces={"knights": 1})
    dfd = BattleSide(side="muslim", role="defender",
                     lord_ids=["al_mutamid"], forces={"sergeants": 1})
    result = BattleResult(engagement="battle", attacker=atk, defender=dfd,
                          winner=None)
    summary = apply_retreat_aftermath(s, result)
    assert summary["losers"] == []


# ---------------------------------------------------------------------------
# Sally aftermath does NOT run this helper (handled by apply_sally_aftermath).
# ---------------------------------------------------------------------------


def test_sally_engagement_skipped_by_retreat_aftermath() -> None:
    s = load_scenario("scenario_a_toledo_beset", seed=7)
    atk = BattleSide(side="muslim", role="attacker",
                     lord_ids=["al_mutamid"], forces={})
    dfd = BattleSide(side="christian", role="defender",
                     lord_ids=["alfonso"], forces={"knights": 1})
    result = BattleResult(engagement="sally", attacker=atk, defender=dfd,
                          winner="christian")
    summary = apply_retreat_aftermath(s, result)
    assert summary["losers"] == []


# ---------------------------------------------------------------------------
# Integration via cmd_battle path.
# ---------------------------------------------------------------------------


def test_cmd_battle_emits_retreat_summary() -> None:
    """cmd_battle path now returns a retreat_summary key with one
    entry per losing Lord."""
    from almoravid.actions import apply_action
    from tests.test_battle import _activate_lord

    s = _activate_lord("scenario_a_toledo_beset", "alfonso", seed=3)
    # Park al_mutamid at the same Locale as Alfonso so cmd_battle works.
    here = s.lords["alfonso"].cylinder.locale_id
    s.lords["al_mutamid"].cylinder = Cylinder(kind="locale", locale_id=here)
    s.lords["al_mutamid"].in_stronghold = False
    # Boost Alfonso so the result is decisive.
    s.lords["alfonso"].forces = {"knights": 6, "men_at_arms": 4}
    s.lords["al_mutamid"].forces = {"sergeants": 1}
    res = apply_action(s, {"type": "cmd_battle", "side": "christian"})
    assert "retreat_summary" in res
    rs = res["retreat_summary"]
    assert rs["winner"] in ("christian", "muslim", None)
    assert isinstance(rs["losers"], list)
