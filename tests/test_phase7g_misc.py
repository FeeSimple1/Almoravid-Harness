"""Phase 7g: Wastage (4.9.4), Encamp (4.3.6), Dinars + Taifas box,
C10/C25 box fidelity."""

from __future__ import annotations

import pytest

from almoravid.actions import IllegalAction, apply_action
from almoravid.campaign import _apply_wastage, compute_final_vp
from almoravid.events import resolve_event
from almoravid.scenarios import load_scenario
from almoravid.state import Cylinder


# ---------------------------------------------------------------------------
# Wastage (4.9.4)
# ---------------------------------------------------------------------------


def test_wastage_discards_one_excess_asset() -> None:
    s = load_scenario("scenario_a_toledo_beset", seed=1)
    lord = s.lords["alfonso"]
    lord.cylinder = Cylinder(kind="locale", locale_id="leon")
    lord.assets = {"coin": 3, "loot": 1}  # coin stack > 1
    out = _apply_wastage(s)
    me = next(e for e in out if e["lord_id"] == "alfonso")
    assert me["discarded_asset"] == "coin"
    assert s.lords["alfonso"].assets["coin"] == 2  # one discarded


def test_wastage_skips_lords_with_no_excess() -> None:
    s = load_scenario("scenario_a_toledo_beset", seed=1)
    for l in s.lords.values():
        if l.cylinder.kind == "locale":
            l.assets = {"coin": 1}  # no stack > 1
            l.capabilities = []
    out = _apply_wastage(s)
    assert out == []


# ---------------------------------------------------------------------------
# Encamp (4.3.6)
# ---------------------------------------------------------------------------


def test_encamp_replaces_bypass_with_siege() -> None:
    s = load_scenario("scenario_a_toledo_beset", seed=1)
    # Find a Muslim Stronghold locale to Bypass.
    loc_id = next(lid for lid, loc in s.locales.items()
                  if loc.base_type != "region")
    s.lords["alfonso"].cylinder = Cylinder(kind="locale", locale_id=loc_id)
    s.lords["alfonso"].in_stronghold = False
    s.locales[loc_id].bypass_yellow = True
    s.locales[loc_id].siege_yellow = 0
    s.meta.phase = "campaign"
    s.meta.campaign_step = "activation"
    s.meta.active_player = "christian"
    s.meta.active_lord_id = "alfonso"
    s.meta.actions_remaining = 2
    r = apply_action(s, {"type": "cmd_encamp", "side": "christian"})
    assert s.locales[loc_id].bypass_yellow is False
    assert s.locales[loc_id].siege_yellow == 1
    assert s.meta.actions_remaining == 0  # card ends
    assert r["encamped"] is True


def test_encamp_rejected_when_not_bypassing() -> None:
    s = load_scenario("scenario_a_toledo_beset", seed=1)
    loc_id = next(lid for lid, loc in s.locales.items()
                  if loc.base_type != "region")
    s.lords["alfonso"].cylinder = Cylinder(kind="locale", locale_id=loc_id)
    s.locales[loc_id].bypass_yellow = False
    s.meta.phase = "campaign"
    s.meta.campaign_step = "activation"
    s.meta.active_player = "christian"
    s.meta.active_lord_id = "alfonso"
    s.meta.actions_remaining = 2
    with pytest.raises(IllegalAction) as ei:
        apply_action(s, {"type": "cmd_encamp", "side": "christian"})
    assert ei.value.code == "not_bypassing"


# ---------------------------------------------------------------------------
# Dinars deposit + Taifas box
# ---------------------------------------------------------------------------


def test_dinars_deposit_moves_coin_to_box() -> None:
    s = load_scenario("scenario_a_toledo_beset", seed=1)
    taifa_lord = next((lid for lid, l in s.lords.items()
                       if l.is_taifa and l.side == "muslim"
                       and lid not in ("yusuf", "sir")), None)
    if taifa_lord is None:
        pytest.skip("no eligible Taifa Lord")
    s.lords[taifa_lord].cylinder = Cylinder(kind="locale", locale_id="sevilla")
    s.lords[taifa_lord].in_stronghold = False
    s.lords[taifa_lord].assets = {"coin": 4}
    box_before = s.taifas_box_coin
    r = apply_action(s, {"type": "dinars_deposit", "side": "muslim",
                         "lord_id": taifa_lord})
    assert r["deposited"] == 4
    assert s.taifas_box_coin == box_before + 4
    assert s.lords[taifa_lord].assets.get("coin", 0) == 0


# ---------------------------------------------------------------------------
# C10 Devaluation drains the Taifas box too
# ---------------------------------------------------------------------------


def test_c10_includes_taifas_box_coin() -> None:
    s = load_scenario("scenario_a_toledo_beset", seed=1)
    # Total Muslim coin = box(6) + lords. Zero lord coin to isolate box.
    for l in s.lords.values():
        if l.side == "muslim":
            l.assets.pop("coin", None)
    s.taifas_box_coin = 6
    r = resolve_event(s, "christian", "C10")
    import math
    assert r["coin_before"] == 6
    # ceil(6 * 2/3) = 4 remaining; 2 removed (from the box).
    assert r["coin_after"] == 4
    assert s.taifas_box_coin == 4


# ---------------------------------------------------------------------------
# C25 banks 1 VP in the Taifas box, counted at end of game
# ---------------------------------------------------------------------------


def test_c25_taifas_box_vp_counts_for_muslim() -> None:
    s = load_scenario("scenario_a_toledo_beset", seed=1)
    if "rodrigo_al_sayyid" not in s.lords:
        pytest.skip("rodrigo_al_sayyid not in scenario")
    s.lords["rodrigo_al_sayyid"].cylinder = Cylinder(
        kind="locale", locale_id="leon")
    s.lords["rodrigo_al_sayyid"].in_stronghold = False
    s.decks.this_levy_events["christian"] = ["C25"]
    # Zero the board so box VP is isolated.
    for loc in s.locales.values():
        loc.conquered_markers = 0
        loc.jihad_markers = 0
        loc.ravaged = "none"
    for t in s.taifas.values():
        t.status = "independent"
    s.taifas_box_vp = 0.0  # isolate the +1 banked by De Vivar Reconciliation
    apply_action(s, {"type": "play_de_vivar_reconcile", "side": "christian"})
    assert s.taifas_box_vp == 1.0
    cvp, mvp = compute_final_vp(s)
    assert mvp == 1.0  # box VP flows into Muslim total
