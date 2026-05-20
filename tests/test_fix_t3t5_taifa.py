"""FIX-D / T3 forced-Conquest via _conquer_stronghold (1.4.3/1.4.4) and
T5 Parias Coin on Independent->Parias in non-Disband paths (1.4.3)."""

from __future__ import annotations

from almoravid.campaign import adjust_taifa_status
from almoravid.scenarios import load_scenario


def test_t5_parias_coin_awarded_on_independent_to_parias() -> None:
    """A non-Disband Independent->Parias transition awards Parias Coin
    (= 4 for a non-Sevilla Taifa Lord) to an Unbesieged Christian Lord."""
    s = load_scenario("scenario_a_toledo_beset", seed=1)
    assert s.taifas["zaragoza"].status == "independent"
    coin_before = sum(l.assets.get("coin", 0)
                      for l in s.lords.values() if l.side == "christian")
    r = adjust_taifa_status(s, "zaragoza", "parias")
    coin_after = sum(l.assets.get("coin", 0)
                     for l in s.lords.values() if l.side == "christian")
    assert r.get("parias_coin") is not None
    assert coin_after - coin_before == 4   # non-Sevilla Taifa Lord


def test_t5_sevilla_parias_coin_is_six() -> None:
    s = load_scenario("scenario_a_toledo_beset", seed=1)
    s.taifas["sevilla"].status = "independent"
    coin_before = sum(l.assets.get("coin", 0)
                      for l in s.lords.values() if l.side == "christian")
    adjust_taifa_status(s, "sevilla", "parias")
    coin_after = sum(l.assets.get("coin", 0)
                     for l in s.lords.values() if l.side == "christian")
    assert coin_after - coin_before == 6   # al-Mutamid (Sevilla)


def test_t3_forced_jihad_removes_christian_conquered_marker() -> None:
    """T3: Independent->Reconquista forced Muslim Conquest now routes
    through _conquer_stronghold, so a pre-existing Christian Conquered
    marker at the Muslim Lord's Stronghold is removed when Jihad is
    placed (1.4.4 eligibility), not stacked alongside it."""
    s = load_scenario("scenario_a_toledo_beset", seed=1)
    # Al-Mustain is at zaragoza (a City, his Seat).
    assert s.lords["al_mustain"].cylinder.locale_id == "zaragoza"
    loc = s.locales["zaragoza"]
    loc.conquered_markers = 1          # stray Christian Conquered marker
    loc.jihad_markers = 0
    adjust_taifa_status(s, "zaragoza", "reconquista")
    assert loc.jihad_markers == 3      # City value; Jihad placed
    assert loc.conquered_markers == 0  # Christian Conquered removed (T3)


def test_t5_not_double_awarded_when_suppressed() -> None:
    """award_parias_coin=False suppresses the auto-award (Disband path
    handles it with the player's distribution)."""
    s = load_scenario("scenario_a_toledo_beset", seed=1)
    coin_before = sum(l.assets.get("coin", 0)
                      for l in s.lords.values() if l.side == "christian")
    r = adjust_taifa_status(s, "zaragoza", "parias", award_parias_coin=False)
    coin_after = sum(l.assets.get("coin", 0)
                     for l in s.lords.values() if l.side == "christian")
    assert "parias_coin" not in r
    assert coin_after == coin_before
