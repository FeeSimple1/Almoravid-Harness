"""Residual multi-Lord Array choices (DECISION-006 -> DECISION-007):

1. Flanking absorb-before-opposed (4.4.2 APPLY HITS): "A Player with a
   Flanking Lord selects either the Flanking or directly opposed Lord to
   take Hits." Exposed via array_flank_absorb = 'opposed' (default) |
   'flanking'.
2. Storm REPOSITION (4.4.1): the optional "may add one Lord from Reserve"
   commitment (reposition_attacker / reposition_defender) and WHICH Reserve
   Advances (array_reserve_priority).
"""

from __future__ import annotations

from almoravid.actions import apply_action
from almoravid.battle import BattleSide, LordPosition, _resolve_step
from almoravid.scenarios import load_scenario


def _lp(lord_id, position, forces):
    return LordPosition(lord_id=lord_id, position=position, forces=dict(forces))


def _two_lord_battle(seed=7):
    """Attacker: 1 Front-center striker + 1 Reserve (so only center Strikes).
    Defender: Front-center (directly opposed) + Front-left (a Flanking Lord,
    since the Attacker has no left). Both arrays non-None -> per-pair path."""
    s = load_scenario("scenario_a_toledo_beset", seed=seed)
    chr_ = [lid for lid, lo in s.lords.items() if lo.side == "christian"][:2]
    mus = [lid for lid, lo in s.lords.items() if lo.side == "muslim"][:2]
    atk = BattleSide(side="christian", role="attacker", lord_ids=chr_,
                     forces={"knights": 12})
    atk.array = [_lp(chr_[0], "front_center", {"knights": 12}),
                 _lp(chr_[1], "reserve", {"knights": 12})]
    dfd = BattleSide(side="muslim", role="defender", lord_ids=mus,
                     forces={"sergeants": 6})
    dfd.array = [_lp(mus[0], "front_center", {"sergeants": 3}),
                 _lp(mus[1], "front_left", {"sergeants": 3})]
    return s, atk, dfd, chr_, mus


def test_flank_absorb_opposed_default_hits_directly_opposed() -> None:
    s, atk, dfd, chr_, mus = _two_lord_battle()
    # Default policy "opposed": the directly-opposed center Lord takes Hits.
    _resolve_step(s, "2.b", "attacker", "melee", "horse", atk, dfd,
                  round_index=1)
    center = next(lp for lp in dfd.array if lp.lord_id == mus[0])
    left = next(lp for lp in dfd.array if lp.lord_id == mus[1])
    assert sum(center.forces.values()) < 3      # center absorbed the Hits
    assert sum(left.forces.values()) == 3       # flanker untouched


def test_flank_absorb_flanking_redirects_to_flanking_lord() -> None:
    s, atk, dfd, chr_, mus = _two_lord_battle()
    s.meta.array_flank_absorb["muslim"] = "flanking"
    _resolve_step(s, "2.b", "attacker", "melee", "horse", atk, dfd,
                  round_index=1)
    center = next(lp for lp in dfd.array if lp.lord_id == mus[0])
    left = next(lp for lp in dfd.array if lp.lord_id == mus[1])
    assert sum(center.forces.values()) == 3     # directly-opposed Lord spared
    assert sum(left.forces.values()) < 3        # Flanking Lord absorbed


def test_flank_absorb_no_redirect_without_flanking_lord() -> None:
    """If the side has no Flanking Lord, 'flanking' is a no-op (Hits land on
    the directly-opposed Lord)."""
    s, atk, dfd, chr_, mus = _two_lord_battle()
    # Move the would-be flanker to Reserve so it is not Flanking.
    next(lp for lp in dfd.array if lp.lord_id == mus[1]).position = "reserve"
    s.meta.array_flank_absorb["muslim"] = "flanking"
    _resolve_step(s, "2.b", "attacker", "melee", "horse", atk, dfd,
                  round_index=1)
    center = next(lp for lp in dfd.array if lp.lord_id == mus[0])
    assert sum(center.forces.values()) < 3      # opposed Lord still takes Hits


def test_set_array_tactics_flank_absorb_validates() -> None:
    import pytest

    from almoravid.actions import IllegalAction
    s = load_scenario("scenario_a_toledo_beset", seed=1)
    r = apply_action(s, {"type": "set_array_tactics", "side": "muslim",
                         "flank_absorb": "flanking"})
    assert r["flank_absorb"] == "flanking"
    assert s.meta.array_flank_absorb["muslim"] == "flanking"
    with pytest.raises(IllegalAction):
        apply_action(s, {"type": "set_array_tactics", "side": "muslim",
                         "flank_absorb": "sideways"})


# ---------------------------------------------------------------------------
# Storm REPOSITION (4.4.1)
# ---------------------------------------------------------------------------

def test_storm_reserve_pick_honours_priority() -> None:
    from almoravid.battle import _storm_reserve_pick
    assert _storm_reserve_pick(["a", "b", "c"], []) == 0          # legacy
    assert _storm_reserve_pick(["a", "b", "c"], ["c"]) == 2       # chosen
    assert _storm_reserve_pick(["a", "b", "c"], ["z", "b"]) == 1  # first present
    assert _storm_reserve_pick(["a", "b"], ["z"]) == 0            # none present


def _storm_ss(seed=7):
    from almoravid.battle import _storm_setup
    s = load_scenario("scenario_a_toledo_beset", seed=seed)
    chr_ = [lid for lid, lo in s.lords.items() if lo.side == "christian"][:1]
    mus = [lid for lid, lo in s.lords.items() if lo.side == "muslim"][:3]
    atk = BattleSide(side="christian", role="attacker", lord_ids=chr_,
                     forces={"knights": 1})
    dfd = BattleSide(side="muslim", role="defender", lord_ids=mus,
                     forces={"sergeants": 3})
    ss, _ = _storm_setup(s, atk, dfd)
    ss["capacity"] = 5            # allow the optional Reserve commit
    return s, atk, dfd, ss, mus


def test_storm_reposition_advances_priority_reserve() -> None:
    from almoravid.battle import _storm_run_round
    s, atk, dfd, ss, mus = _storm_ss()
    # d_front = [mus0]; d_reserve = [mus1, mus2]. Prefer mus2 to Advance.
    assert ss["d_front"] == [mus[0]]
    assert set(ss["d_reserve"]) == {mus[1], mus[2]}
    s.meta.array_reserve_priority["muslim"] = [mus[2]]
    _storm_run_round(s, atk, dfd, ss, 2)
    assert mus[2] in ss["d_front"]      # the chosen Reserve Advanced
    assert mus[1] in ss["d_reserve"]    # the other stayed (one per Round)


def test_storm_reposition_optional_commit_can_be_declined() -> None:
    from almoravid.battle import _storm_run_round
    s, atk, dfd, ss, mus = _storm_ss()
    ss["reposition_defender"] = False   # decline the optional "may add"
    _storm_run_round(s, atk, dfd, ss, 2)
    # Front not yet wiped, so with the option declined no Reserve Advances.
    assert ss["d_front"] == [mus[0]]
    assert set(ss["d_reserve"]) == {mus[1], mus[2]}


def test_storm_reposition_attacker_priority_and_optionality() -> None:
    """The Attacker side (storming) reposes symmetrically: its optional
    commit honours reposition_attacker, and array_reserve_priority picks
    which Attacker Reserve Advances."""
    from almoravid.battle import _storm_run_round, _storm_setup
    s = load_scenario("scenario_a_toledo_beset", seed=7)
    chr_ = [lid for lid, lo in s.lords.items() if lo.side == "christian"][:3]
    mus = [lid for lid, lo in s.lords.items() if lo.side == "muslim"][:1]
    atk = BattleSide(side="christian", role="attacker", lord_ids=chr_,
                     forces={"knights": 3})
    dfd = BattleSide(side="muslim", role="defender", lord_ids=mus,
                     forces={"sergeants": 1})
    ss, _ = _storm_setup(s, atk, dfd)
    ss["capacity"] = 5
    assert ss["a_front"] == [chr_[0]]
    s.meta.array_reserve_priority["christian"] = [chr_[2]]
    _storm_run_round(s, atk, dfd, ss, 2)
    assert chr_[2] in ss["a_front"]     # chosen Attacker Reserve Advanced
    assert chr_[1] in ss["a_reserve"]

    # And with the option declined, no Attacker Reserve Advances.
    s2 = load_scenario("scenario_a_toledo_beset", seed=7)
    atk2 = BattleSide(side="christian", role="attacker", lord_ids=chr_,
                      forces={"knights": 3})
    dfd2 = BattleSide(side="muslim", role="defender", lord_ids=mus,
                      forces={"sergeants": 1})
    ss2, _ = _storm_setup(s2, atk2, dfd2)
    ss2["capacity"] = 5
    ss2["reposition_attacker"] = False
    _storm_run_round(s2, atk2, dfd2, ss2, 2)
    assert ss2["a_front"] == [chr_[0]]
