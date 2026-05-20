"""FIX-E / E4 Feed all Moved/Fought (both sides), E5 Sharing, E6 Greed
mule-discard (rule 4.8.1)."""

from __future__ import annotations

from almoravid.campaign import (
    _feed_all_moved_fought, _feed_consume_own,
)
from almoravid.scenarios import load_scenario


def _sm_box(s, lid):
    return next(sm.box for sm in s.calendar.service_markers
               if sm.lord_id == lid)


def test_e4_feeds_all_moved_fought_lords_both_sides() -> None:
    """Every Lord marked Moved/Fought Feeds, not only the active one."""
    s = load_scenario("scenario_a_toledo_beset", seed=1)
    # Two Christian Lords at different Locales, both Moved/Fought, each
    # with exactly enough Provender.
    s.lords["alvar_fanez"].moved_fought = True
    s.lords["alvar_fanez"].forces = {"knights": 6}     # need 1
    s.lords["alvar_fanez"].assets = {"prov": 1}
    s.lords["sancho"].moved_fought = True
    s.lords["sancho"].forces = {"knights": 6}          # need 1
    s.lords["sancho"].assets = {"prov": 1}
    out = _feed_all_moved_fought(s)
    fed_ids = {e["lord_id"] for e in out["fed"]}
    assert "alvar_fanez" in fed_ids and "sancho" in fed_ids
    assert s.lords["alvar_fanez"].assets.get("prov", 0) == 0
    assert s.lords["sancho"].assets.get("prov", 0) == 0
    assert out["unfed"] == []


def test_e5_sharing_feeds_short_lord_from_same_locale_ally() -> None:
    """A Lord short on his own Provender is fed by a same-side Lord in
    the same Locale (mandatory Sharing); no Unfed penalty results."""
    s = load_scenario("scenario_a_toledo_beset", seed=1)
    # sahagun holds alfonso, garcia_ordonez, pedro_ansurez (all Christian).
    s.lords["alfonso"].moved_fought = True
    s.lords["alfonso"].forces = {"knights": 6}    # need 1
    s.lords["alfonso"].assets = {}                # no own Provender -> short 1
    # Ally at same Locale has spare Provender to share.
    s.lords["garcia_ordonez"].moved_fought = False
    s.lords["garcia_ordonez"].assets = {"prov": 2}
    before = _sm_box(s, "alfonso")
    out = _feed_all_moved_fought(s)
    assert any(sh["to"] == "alfonso" for sh in out["shared"])
    assert "alfonso" not in out["unfed"]
    assert _sm_box(s, "alfonso") == before          # not shifted (fed)
    assert s.lords["garcia_ordonez"].assets.get("prov", 0) == 1  # gave 1


def test_e5_unfed_when_no_sharing_available() -> None:
    """If no ally can share, the short Lord is Unfed (Service -1)."""
    s = load_scenario("scenario_a_toledo_beset", seed=1)
    s.lords["alvar_fanez"].moved_fought = True
    s.lords["alvar_fanez"].forces = {"knights": 6}   # need 1
    s.lords["alvar_fanez"].assets = {}               # short, alone at toledo
    before = _sm_box(s, "alvar_fanez")
    out = _feed_all_moved_fought(s)
    assert "alvar_fanez" in out["unfed"]
    assert _sm_box(s, "alvar_fanez") == before - 1


def test_e6_greed_discards_excess_mules_to_avoid_unfed() -> None:
    """With the Greed option, a Lord discards Mules in excess of feeding
    capacity so his available Provender/Loot fully Feeds him."""
    s = load_scenario("scenario_a_toledo_beset", seed=1)
    lord = s.lords["alvar_fanez"]
    lord.forces = {"knights": 5}              # 5 units
    lord.assets = {"mule": 2, "loot": 1}      # 7 units+mules -> need 2; only 1 Asset
    # Without discard: need 2, have 1 -> short 1.
    r_keep = _feed_consume_own(s, "alvar_fanez", discard_excess_mules=False)
    assert r_keep["short"] == 1
    # Reset and try WITH Greed discard.
    s2 = load_scenario("scenario_a_toledo_beset", seed=1)
    lord2 = s2.lords["alvar_fanez"]
    lord2.forces = {"knights": 5}
    lord2.assets = {"mule": 2, "loot": 1}
    r_disc = _feed_consume_own(s2, "alvar_fanez", discard_excess_mules=True)
    # capacity = 1 Asset -> can feed 6 units+mules; units=5 -> keep 1 mule,
    # discard 1 -> 6 units+mules -> need 1 -> fed by the 1 Loot, short 0.
    assert r_disc["mules_discarded"] == 1
    assert r_disc["short"] == 0
    assert s2.lords["alvar_fanez"].assets.get("mule", 0) == 1
