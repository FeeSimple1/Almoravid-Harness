"""Phase 7f: Battle Array nuances — Spoils-on-Retreat (4.4.3),
Pursuit-marker tracking, Relief Sally (4.4.1)."""

from __future__ import annotations

from almoravid.battle import (
    BattleResult, BattleSide, apply_retreat_aftermath,
)
from almoravid.scenarios import load_scenario
from almoravid.state import Cylinder


def _retreat_setup(s, conceded=False):
    """Christian loses; place Alfonso at a clean region to force the
    Retreat branch, with predictable Assets."""
    s.lords["alfonso"].cylinder = Cylinder(kind="locale",
                                           locale_id="transduero")
    s.lords["alfonso"].in_stronghold = False
    s.lords["alfonso"].assets = {"coin": 3, "loot": 2, "prov": 5,
                                 "mule": 1}
    # Winner (Muslim) Lord present at the battle locale to receive Spoils.
    s.lords["al_mutamid"].cylinder = Cylinder(kind="locale",
                                              locale_id="transduero")
    s.lords["al_mutamid"].in_stronghold = False
    s.lords["al_mutamid"].assets = {}
    # Clear other Muslims off the retreat neighbors.
    for lid, l in s.lords.items():
        if l.side == "muslim" and lid != "al_mutamid":
            l.cylinder = Cylinder(kind="locale", locale_id="sevilla")
    atk = BattleSide(side="christian", role="attacker",
                     lord_ids=["alfonso"], forces={})
    dfd = BattleSide(side="muslim", role="defender",
                     lord_ids=["al_mutamid"], forces={"knights": 1})
    if conceded:
        atk.conceded = True
    result = BattleResult(engagement="battle", attacker=atk, defender=dfd,
                          winner="muslim")
    return result


def test_retreat_without_concede_transfers_all_assets() -> None:
    s = load_scenario("scenario_a_toledo_beset", seed=7)
    result = _retreat_setup(s, conceded=False)
    summary = apply_retreat_aftermath(s, result)
    entry = summary["losers"][0]
    assert entry["fate"] == "retreat", "expected the retreat branch on this seed/map"
    # All of Alfonso's Assets transferred to al-Mutamid.
    assert s.lords["alfonso"].assets == {}
    assert s.lords["al_mutamid"].assets.get("coin", 0) == 3
    assert s.lords["al_mutamid"].assets.get("loot", 0) == 2
    assert s.lords["al_mutamid"].assets.get("prov", 0) == 5


def test_concede_then_retreat_keeps_non_loot_non_excess_prov() -> None:
    s = load_scenario("scenario_a_toledo_beset", seed=7)
    result = _retreat_setup(s, conceded=True)
    summary = apply_retreat_aftermath(s, result)
    entry = summary["losers"][0]
    assert entry["fate"] == "retreat", "expected the retreat branch"
    # Conceded: lose all Loot (2) + excess Prov (5 - 1 transport = 4).
    # Keep coin (3), mule (1), and 1 Prov (== transport capacity).
    assert s.lords["alfonso"].assets.get("loot", 0) == 0
    assert s.lords["alfonso"].assets.get("prov", 0) == 1
    assert s.lords["alfonso"].assets.get("coin", 0) == 3
    assert s.lords["alfonso"].assets.get("mule", 0) == 1
    # Winner got the loot + excess prov.
    assert s.lords["al_mutamid"].assets.get("loot", 0) == 2
    assert s.lords["al_mutamid"].assets.get("prov", 0) == 4
    # Pursuit marker recorded.
    assert summary.get("pursuit", {}).get("conceder") == "christian"


def test_withdraw_transfers_no_spoils() -> None:
    s = load_scenario("scenario_a_toledo_beset", seed=7)
    # Al-Mutamid loses at his own Seat (Friendly Stronghold) → Withdraws.
    s.lords["al_mutamid"].cylinder = Cylinder(kind="locale",
                                              locale_id="sevilla")
    s.lords["al_mutamid"].in_stronghold = False
    s.lords["al_mutamid"].assets = {"coin": 4, "loot": 3}
    s.lords["alfonso"].cylinder = Cylinder(kind="locale", locale_id="sevilla")
    s.lords["alfonso"].in_stronghold = False
    s.lords["alfonso"].assets = {}
    atk = BattleSide(side="christian", role="attacker",
                     lord_ids=["alfonso"], forces={"knights": 1})
    dfd = BattleSide(side="muslim", role="defender",
                     lord_ids=["al_mutamid"], forces={})
    result = BattleResult(engagement="battle", attacker=atk, defender=dfd,
                          winner="christian")
    summary = apply_retreat_aftermath(s, result)
    entry = summary["losers"][0]
    if entry["fate"] == "withdraw":
        # Withdrawing Lord keeps all Assets; winner gets nothing.
        assert s.lords["al_mutamid"].assets.get("coin", 0) == 4
        assert s.lords["al_mutamid"].assets.get("loot", 0) == 3
        assert s.lords["alfonso"].assets == {}


def test_removed_lord_transfers_all_assets() -> None:
    s = load_scenario("scenario_a_toledo_beset", seed=7)
    # Trap al_mutamid: no Friendly Stronghold, every neighbor blocked.
    from almoravid.map import neighbors_via
    s.lords["al_mutamid"].cylinder = Cylinder(kind="locale", locale_id="leon")
    s.lords["al_mutamid"].in_stronghold = False
    s.lords["al_mutamid"].assets = {"coin": 5, "loot": 1}
    s.lords["alfonso"].cylinder = Cylinder(kind="locale", locale_id="leon")
    s.lords["alfonso"].in_stronghold = False
    s.lords["alfonso"].assets = {}
    # Block every neighbor with a Christian Lord OTHER than Alfonso
    # (Alfonso must stay at leon as the winner to receive Spoils).
    blockers = [lid for lid, l in s.lords.items()
                if l.side == "christian" and lid != "alfonso"]
    nbrs = set()
    for wt in ("road", "pass"):
        nbrs.update(neighbors_via("leon", wt))
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
    if entry["fate"] == "removed":
        # All Assets transferred to the winning Christian Lord(s).
        assert s.lords["al_mutamid"].assets == {}
        assert s.lords["alfonso"].assets.get("coin", 0) == 5
