"""1.4.3 / 3.3.1 — Taifa politics on PERMANENT combat removal.

Rule 1.4.3: "As Conquest of a Stronghold or Muster, Disband, or
removal of a Lord changes a Taifa's status (1.4.1), adjust its
status...". Rule 3.3 Important: whenever an Independent Taifa's Lord
Disbands (permanently or to the Calendar), his Taifa flips to Parias
with Parias Coin and a Christian VP. Combat removal ("as if Beyond
Service", 4.4.4/4.5.2) previously skipped this entirely
(maybe_recompute_taifa_status had zero callers)."""
from __future__ import annotations

from almoravid.battle import BattleResult, BattleSide, apply_battle_losses
from almoravid.campaign import combat_removal_politics
from almoravid.scenarios import load_scenario
from almoravid.state import Cylinder


def test_losses_zero_forces_removal_flips_taifa_to_parias() -> None:
    s = load_scenario("scenario_a_toledo_beset", seed=1)
    assert s.taifas["sevilla"].status == "independent"
    lord = s.lords["al_mutamid"]
    lord.cylinder = Cylinder(kind="locale", locale_id="toledo")
    lord.forces = {}
    lord.routed_units = {"militia": 1}
    s.lords["alfonso"].assets = {}
    coin0 = s.lords["alfonso"].assets.get("coin", 0)
    vp0 = s.score.christian
    atk = BattleSide(side="christian", role="attacker",
                     lord_ids=["alfonso"], forces={"knights": 1})
    dfd = BattleSide(side="muslim", role="defender",
                     lord_ids=["al_mutamid"], forces={})
    res = BattleResult(engagement="battle", attacker=atk, defender=dfd,
                       winner="christian")
    out = apply_battle_losses(s, res, {"losers": []})
    assert out["al_mutamid"].get("permanently_removed")
    assert s.taifas["sevilla"].status == "parias"
    # Parias Coin = 6 (al-Mutamid) to the first Unbesieged Christian.
    assert s.lords["alfonso"].assets.get("coin", 0) == coin0 + 6
    # +1 Christian VP for the Parias marker (5.1).
    assert s.score.christian == vp0 + 1.0


def test_removal_strips_seat_markers() -> None:
    s = load_scenario("scenario_a_toledo_beset", seed=1)
    lord = s.lords["al_mutamid"]
    lord.cylinder = Cylinder(kind="removed")
    s.locales["calatrava"].seat_marker_lord_ids.append("al_mutamid")
    combat_removal_politics(s, "al_mutamid")
    assert "al_mutamid" not in s.locales["calatrava"].seat_marker_lord_ids


def test_non_taifa_removal_no_status_change() -> None:
    s = load_scenario("scenario_a_toledo_beset", seed=1)
    statuses = {tid: t.status for tid, t in s.taifas.items()}
    s.lords["alvar_fanez"].cylinder = Cylinder(kind="removed")
    out = combat_removal_politics(s, "alvar_fanez")
    assert out is None
    assert {tid: t.status for tid, t in s.taifas.items()} == statuses


def test_already_parias_taifa_unchanged() -> None:
    s = load_scenario("scenario_a_toledo_beset", seed=1)
    s.taifas["sevilla"].status = "parias"
    s.lords["al_mutamid"].cylinder = Cylinder(kind="removed")
    vp0 = s.score.christian
    out = combat_removal_politics(s, "al_mutamid")
    assert out is None
    assert s.score.christian == vp0
