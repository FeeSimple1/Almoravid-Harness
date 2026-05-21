"""Regression (deep-test SMOKE find): M15 Parias Revolt must respect
Jihad eligibility (1.4.4) — never stack Jihad on a Christian-Conquered
Locale (1.3.1: a Locale never holds both Conquered and Jihad)."""
from __future__ import annotations

from almoravid.scenarios import load_scenario
from almoravid.events import resolve_event


def _parias_taifa(s):
    return next((t for t in s.taifas.values() if t.status == "parias"), None)


def test_m15_does_not_stack_jihad_on_conquered_locale() -> None:
    s = load_scenario("scenario_a_toledo_beset")
    # Make Toledo Parias and give its first locale a Christian Conquered
    # marker (so it is NOT Jihad-eligible), plus an eligible bare locale.
    t = s.taifas["toledo"]
    t.status = "parias"
    conq = t.locale_ids[0]
    s.locales[conq].conquered_markers = 1
    s.locales[conq].jihad_markers = 0
    # Target the Conquered locale explicitly — M15 must NOT place there.
    resolve_event(s, "muslim", "M15", {"locale_id": conq})
    assert not (s.locales[conq].conquered_markers
                and s.locales[conq].jihad_markers), \
        "M15 stacked Jihad on a Conquered Locale (1.3.1 violation)"
    # No Locale anywhere should hold both markers.
    for lid, loc in s.locales.items():
        assert not (loc.conquered_markers and loc.jihad_markers), lid


def test_m15_noop_when_no_eligible_parias_locale() -> None:
    s = load_scenario("scenario_a_toledo_beset")
    # No Parias Taifa -> no eligible locale -> no-op (no crash).
    for t in s.taifas.values():
        if t.status == "parias":
            t.status = "independent"
    r = resolve_event(s, "muslim", "M15", {})
    assert r is not None
