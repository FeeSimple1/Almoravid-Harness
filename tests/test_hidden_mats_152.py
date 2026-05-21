"""1.5.2 Hidden Mats Option — redacted opponent view (opt-in fog of war)."""
from __future__ import annotations

from almoravid.scenarios import load_scenario
from almoravid.views import redacted_view
from almoravid.state import Cylinder, PendingDecision


def test_off_by_default_full_view() -> None:
    s = load_scenario("scenario_a_toledo_beset")
    assert s.meta.hidden_mats is False
    v = redacted_view(s, "christian")
    # Full view: an on-map Muslim Lord's forces are visible.
    ml = next(l for l in s.lords.values()
              if l.side == "muslim" and l.cylinder.kind == "locale")
    assert v["lords"][ml.id]["forces"] == ml.forces
    assert "hidden_mat" not in v["lords"][ml.id]


def test_hidden_opponent_mats_when_enabled() -> None:
    s = load_scenario("scenario_a_toledo_beset")
    s.meta.hidden_mats = True
    ml = next(l for l in s.lords.values()
              if l.side == "muslim" and l.cylinder.kind == "locale")
    cl = next(l for l in s.lords.values()
              if l.side == "christian" and l.cylinder.kind == "locale")
    v = redacted_view(s, "christian")   # Christian viewer hides Muslim mats
    assert v["lords"][ml.id]["forces"] is None
    assert v["lords"][ml.id]["assets"] is None
    assert v["lords"][ml.id]["capabilities"] is None
    assert v["lords"][ml.id]["hidden_mat"] is True
    # Viewer's OWN Lords stay fully visible.
    assert v["lords"][cl.id]["forces"] == cl.forces
    assert "hidden_mat" not in v["lords"][cl.id]
    # Position/identity of the hidden Lord remain public.
    assert v["lords"][ml.id]["cylinder"]["locale_id"] == ml.cylinder.locale_id


def test_lord_in_battle_is_revealed() -> None:
    s = load_scenario("scenario_a_toledo_beset")
    s.meta.hidden_mats = True
    ml = next(l for l in s.lords.values()
              if l.side == "muslim" and l.cylinder.kind == "locale")
    loc = ml.cylinder.locale_id
    s.pending = PendingDecision(
        kind="march_arrival_response", waiting_on="muslim",
        payload={"locale_id": loc, "active_side": "christian",
                 "defender_lord_ids": [ml.id]})
    v = redacted_view(s, "christian")
    # In Battle -> mat face-up -> forces revealed.
    assert v["lords"][ml.id]["forces"] == ml.forces
    assert "hidden_mat" not in v["lords"][ml.id]


def test_opponent_pending_draw_hidden() -> None:
    s = load_scenario("scenario_a_toledo_beset")
    s.meta.hidden_mats = True
    s.decks.pending_draw = {"christian": ["C1"], "muslim": ["M1"]}
    v = redacted_view(s, "christian")
    assert v["decks"]["pending_draw"]["muslim"] is None
    assert v["decks"]["pending_draw"]["christian"] == ["C1"]
