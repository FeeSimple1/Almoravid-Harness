"""4.3.5/4.3.6 DEPART: marching the last besieging Lord out of a
Bypassed/Besieged Stronghold's Locale removes that side's Siege/Bypass
markers there ("becomes free of Enemy Lords ... remove markers")."""
from __future__ import annotations

from almoravid.actions import apply_action
from almoravid.map import neighbors_via
from almoravid.scenarios import load_scenario
from almoravid.state import Cylinder


def test_march_away_removes_orphaned_bypass_marker() -> None:
    s = load_scenario("scenario_a_toledo_beset", seed=2)
    # Pick a Muslim (enemy) Stronghold the Christian is Bypassing alone.
    from almoravid.effective import is_friendly_locale
    here = next(lid for lid, l in s.locales.items()
                if l.base_type != "region"
                and not is_friendly_locale(s, lid, "christian")
                and neighbors_via(lid, "road"))
    al = s.lords["alfonso"]
    al.cylinder = Cylinder(kind="locale", locale_id=here)
    al.in_stronghold = False
    al.assets = {}
    al.forces = {"knights": 1}
    s.locales[here].bypass_yellow = True
    # No other Christian Lord here.
    target = neighbors_via(here, "road")[0]
    s.meta.phase = "campaign"
    s.meta.campaign_step = "activation"
    s.meta.active_player = "christian"
    s.meta.active_lord_id = "alfonso"
    s.meta.actions_remaining = 3
    apply_action(s, {"type": "cmd_march", "side": "christian",
                     "target_locale_id": target, "way_type": "road"})
    assert s.locales[here].bypass_yellow is False


def test_march_away_leaves_marker_if_ally_remains() -> None:
    s = load_scenario("scenario_a_toledo_beset", seed=2)
    from almoravid.effective import is_friendly_locale
    here = next(lid for lid, l in s.locales.items()
                if l.base_type != "region"
                and not is_friendly_locale(s, lid, "christian")
                and neighbors_via(lid, "road"))
    al = s.lords["alfonso"]
    al.cylinder = Cylinder(kind="locale", locale_id=here)
    al.in_stronghold = False
    al.assets = {}
    al.forces = {"knights": 1}
    ally = s.lords["alvar_fanez"]
    ally.cylinder = Cylinder(kind="locale", locale_id=here)
    ally.in_stronghold = False
    s.locales[here].bypass_yellow = True
    target = neighbors_via(here, "road")[0]
    s.meta.phase = "campaign"
    s.meta.campaign_step = "activation"
    s.meta.active_player = "christian"
    s.meta.active_lord_id = "alfonso"
    s.meta.actions_remaining = 3
    apply_action(s, {"type": "cmd_march", "side": "christian",
                     "target_locale_id": target, "way_type": "road"})
    # alvar_fanez still Bypassing here -> marker stays.
    assert s.locales[here].bypass_yellow is True
