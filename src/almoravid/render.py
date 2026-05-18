"""State rendering for LLM consumption and human inspection.

Three view modes:
  - render_summary(state): compact header view, single-screen, LLM-
    budget-friendly. Designed to be the per-turn context an LLM seat
    receives.
  - render_verbose(state): full state, every Lord and every marker.
  - render_focus(state, target): deep dive on one Lord or Locale.

Per BRIEF: the harness encodes rules; the LLM picks among legal moves.
This module is the canonical "what does the state look like" view.
"""

from __future__ import annotations

from almoravid.state import GameState, Locale, Lord


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_SEASON_SHORT = {"spring": "Sp", "summer": "Su", "autumn": "Au", "winter": "Wi"}
_SIDE_SHORT = {"christian": "C", "muslim": "M"}


def _year_for_box(box: int) -> int:
    """Return 1085 or 1086 based on Calendar box (1-8 -> 1085, 9-16 -> 1086)."""
    return 1085 if box <= 8 else 1086


def _forces_short(forces: dict) -> str:
    """Compact force-count string like '1K 1S 2L 1M 1Sf'."""
    if not forces:
        return "—"
    short = {
        "knights": "K", "sergeants": "S", "light_horse": "L",
        "african_horse": "AH", "men_at_arms": "MA",
        "african_foot": "AF", "militia": "Mi", "serfs": "Sf",
    }
    parts = []
    for k, v in forces.items():
        if v:
            parts.append(f"{v}{short.get(k, k)}")
    return " ".join(parts) if parts else "—"


def _assets_short(assets: dict) -> str:
    if not assets:
        return "—"
    short = {"coin": "Co", "loot": "Lt", "prov": "Pv", "cart": "Ct", "mule": "Mu"}
    return " ".join(f"{v}{short.get(k, k)}" for k, v in assets.items() if v)


def _cylinder_short(lord: Lord) -> str:
    c = lord.cylinder
    if c.kind == "locale":
        return f"@{c.locale_id}"
    if c.kind == "calendar":
        return f"cal:{c.box}"
    if c.kind == "set_aside":
        return "aside"
    if c.kind == "removed":
        return "removed"
    if c.kind == "mat":
        return "mat"
    return c.kind


def _locale_markers_short(loc: Locale) -> str:
    """One-line summary of overlay markers, or empty if none."""
    parts = []
    if loc.conquered_markers:
        parts.append(f"Conq×{loc.conquered_markers}")
    if loc.jihad_markers:
        parts.append(f"Jihad×{loc.jihad_markers}")
    if loc.ravaged != "none":
        parts.append(f"Ravaged({loc.ravaged})")
    if loc.siege_yellow:
        parts.append(f"Siege-Y×{loc.siege_yellow}")
    if loc.siege_green:
        parts.append(f"Siege-G×{loc.siege_green}")
    if loc.bypass_yellow:
        parts.append("Bypass-Y")
    if loc.bypass_green:
        parts.append("Bypass-G")
    if loc.seat_marker_lord_ids:
        parts.append(f"Seats({','.join(loc.seat_marker_lord_ids)})")
    return " ".join(parts)


# ---------------------------------------------------------------------------
# Summary view — LLM-budget-friendly
# ---------------------------------------------------------------------------

def render_summary(state: GameState) -> str:
    box = state.calendar.current_box
    season = state.calendar.boxes[box - 1].season
    turn_type = state.calendar.boxes[box - 1].turn_type
    year = _year_for_box(box)
    header = (
        f"=== Almoravid — Scenario {state.meta.scenario_letter} "
        f"({state.meta.scenario_id}) ===\n"
        f"Box {box} ({_SEASON_SHORT[season]} {year} {turn_type})  |  "
        f"Active: {state.meta.active_player}  |  "
        f"VP: C {state.score.christian} / M {state.score.muslim}"
    )

    lines = [header, ""]

    # Taifa status row
    t_parts = []
    for tid in ("toledo", "badajoz", "granada", "valencia", "zaragoza", "lerida", "sevilla"):
        if tid in state.taifas:
            t = state.taifas[tid]
            status_short = {"independent": "I", "parias": "P", "reconquista": "R", "kingdoms": "K"}[t.status]
            t_parts.append(f"{t.name[:3]}={status_short}")
    lines.append("Taifas: " + " ".join(t_parts))
    lines.append("")

    # Lords on map
    for side in ("christian", "muslim"):
        lords_on_map = [
            l for l in state.lords.values()
            if l.side == side and l.cylinder.kind == "locale"
        ]
        if lords_on_map:
            lines.append(f"{side.title()} Lords on map:")
            for l in lords_on_map:
                vassal_ready = sum(1 for v in l.vassals if v.ready)
                lines.append(
                    f"  {l.name} {_cylinder_short(l)}  "
                    f"forces=[{_forces_short(l.forces)}]  "
                    f"assets=[{_assets_short(l.assets)}]  "
                    f"V={vassal_ready}/{len(l.vassals)}  "
                    f"caps={','.join(l.capabilities) or '—'}"
                )

    # Lords elsewhere (calendar / set_aside / removed)
    elsewhere = [l for l in state.lords.values() if l.cylinder.kind != "locale"]
    if elsewhere:
        lines.append("")
        lines.append("Lords elsewhere:")
        for l in sorted(elsewhere, key=lambda x: (x.side, x.cylinder.kind, x.name)):
            lines.append(
                f"  {_SIDE_SHORT[l.side]} {l.name}: {_cylinder_short(l)}"
            )

    # Locales with active markers
    active_locales = [
        loc for loc in state.locales.values()
        if (loc.conquered_markers or loc.jihad_markers or loc.ravaged != "none"
            or loc.siege_yellow or loc.siege_green
            or loc.bypass_yellow or loc.bypass_green)
    ]
    if active_locales:
        lines.append("")
        lines.append("Locale markers:")
        for loc in sorted(active_locales, key=lambda x: x.name):
            lines.append(f"  {loc.name}: {_locale_markers_short(loc)}")

    # Held events and capabilities in play
    if state.decks.held:
        lines.append("")
        for side_str, cards in state.decks.held.items():
            if cards:
                lines.append(f"{side_str.title()} holds: {','.join(cards)}")
    if state.decks.capabilities_in_play:
        sw = [c for c in state.decks.capabilities_in_play if c.scope == "side_wide"]
        if sw:
            lines.append("Side-wide caps in play: " + ", ".join(
                f"{c.card_id}({c.owner_side[0]})" for c in sw
            ))

    if state.pending:
        lines.append("")
        lines.append(f"PENDING: {state.pending.kind} (waiting on {state.pending.waiting_on})")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Verbose view — every detail
# ---------------------------------------------------------------------------

def render_verbose(state: GameState) -> str:
    out = [render_summary(state), "", "=== Full state ===", ""]

    # Calendar full
    out.append("Calendar:")
    for box in state.calendar.boxes:
        sm = [s for s in state.calendar.service_markers if s.box == box.number]
        if box.cylinder_lord_ids or sm or box.decorations:
            parts = []
            if box.decorations:
                parts.append(",".join(box.decorations))
            if box.cylinder_lord_ids:
                parts.append(f"cyl=[{','.join(box.cylinder_lord_ids)}]")
            if sm:
                parts.append(f"svc=[{','.join(s.lord_id for s in sm)}]")
            out.append(
                f"  Box {box.number:>2} ({_SEASON_SHORT[box.season]} "
                f"{_year_for_box(box.number)} {box.turn_type[:3]}): "
                + "  ".join(parts)
            )
    if state.calendar.off_left or state.calendar.off_right:
        out.append(f"  Off-edge cylinders: L={state.calendar.off_left} R={state.calendar.off_right}")
    if state.calendar.off_left_service or state.calendar.off_right_service:
        out.append(f"  Off-edge service:   L={state.calendar.off_left_service} R={state.calendar.off_right_service}")

    # Lords full
    out.append("")
    out.append("Lords:")
    for lid, l in sorted(state.lords.items(), key=lambda kv: (kv[1].side, kv[1].name)):
        out.append(
            f"  {_SIDE_SHORT[l.side]} {l.name} ({lid}) "
            f"F{l.fealty}/S{l.service_rating}/L{l.lordship_rating}/C{l.command_rating}  "
            f"{_cylinder_short(l)}"
        )
        if l.forces:
            out.append(f"      forces: {_forces_short(l.forces)}")
        if l.assets:
            out.append(f"      assets: {_assets_short(l.assets)}")
        if l.capabilities:
            out.append(f"      caps:   {','.join(l.capabilities)}")
        if l.vassals:
            out.append(
                "      vassals: " + ", ".join(
                    f"{v.name}{'[r]' if v.ready else '[d]'}" for v in l.vassals
                )
            )

    # Locales with any markers
    out.append("")
    out.append("Locales (with markers only):")
    for loc in sorted(state.locales.values(), key=lambda x: (x.territory, x.name)):
        m = _locale_markers_short(loc)
        if m:
            out.append(f"  [{loc.territory}] {loc.name} ({loc.base_type}): {m}")

    # Decks
    out.append("")
    out.append("Decks:")
    out.append(f"  Held: {dict(state.decks.held)}")
    if state.decks.board_edge:
        out.append(f"  Board edge: {dict(state.decks.board_edge)}")
    if state.decks.capabilities_in_play:
        out.append(f"  Capabilities in play ({len(state.decks.capabilities_in_play)}):")
        for c in state.decks.capabilities_in_play:
            owner = f"{c.owner_side}/{c.owner_lord_id}" if c.owner_lord_id else c.owner_side
            out.append(f"    {c.card_id} [{c.scope}] -> {owner}")

    # History tail
    if state.history:
        out.append("")
        out.append("History (last 10):")
        for h in state.history[-10:]:
            out.append(f"  T{h.turn_index} {h.actor}: {h.action} — {h.summary}")

    return "\n".join(out)


# ---------------------------------------------------------------------------
# Focus view — one Lord or Locale
# ---------------------------------------------------------------------------

def render_focus(state: GameState, target: str) -> str:
    """Deep dive on one entity. Accepts a Lord id or a Locale id."""
    if target in state.lords:
        return _render_focus_lord(state, target)
    if target in state.locales:
        return _render_focus_locale(state, target)
    raise ValueError(
        f"Unknown focus target {target!r}. "
        f"Known lord ids: {sorted(state.lords)}. "
        f"Known locale ids: example {sorted(state.locales)[:5]}..."
    )


def _render_focus_lord(state: GameState, lord_id: str) -> str:
    l = state.lords[lord_id]
    out = [
        f"=== Lord: {l.name} ({lord_id}) ===",
        f"Side: {l.side}  |  Marshal: —  |  Taifa Lord: {l.is_taifa}"
        + (f" ({l.home_taifa})" if l.home_taifa else ""),
        f"Ratings: Fealty {l.fealty}  Service {l.service_rating}  "
        f"Lordship {l.lordship_rating}  Command {l.command_rating}",
        f"Seats (printed): {', '.join(l.seats) if l.seats else '—'}",
        f"Cylinder: {_cylinder_short(l)}",
        f"In Stronghold: {l.in_stronghold}",
        "",
        f"Forces: {_forces_short(l.forces)}",
        f"Assets: {_assets_short(l.assets)}",
        f"Capabilities (this_lord): {', '.join(l.capabilities) or '—'}",
    ]
    if l.vassals:
        out.append("")
        out.append("Vassals:")
        for v in l.vassals:
            ready = "ready" if v.ready else "Disbanded"
            out.append(f"  {v.name} — {_forces_short(v.forces)} — svc {v.service_cost} — {ready}")
    if l.routed_units:
        out.append("")
        out.append(f"Routed units (this engagement): {_forces_short(l.routed_units)}")
    out.append("")
    out.append("Per-card / per-Levy flags:")
    out.append(f"  moved_fought={l.moved_fought}  just_arrived_this_levy={l.just_arrived_this_levy}")
    out.append(f"  lordship_used={l.lordship_used}  first_march_used_this_card={l.first_march_used_this_card}")
    out.append(f"  raiders_used_this_card={l.raiders_used_this_card}")
    return "\n".join(out)


def _render_focus_locale(state: GameState, loc_id: str) -> str:
    loc = state.locales[loc_id]
    out = [
        f"=== Locale: {loc.name} ({loc_id}) ===",
        f"Territory: {loc.territory}",
        f"Base type: {loc.base_type}"
        + (f" (Cap {state.locales[loc_id]})" if False else ""),
        f"Gardens: {loc.has_gardens}  |  Port: {loc.has_port}  |  Reconquista target: {loc.is_reconquista_target}",
        f"Printed seats: {', '.join(loc.seat_marker_lord_ids) or '—'}",
    ]
    markers = _locale_markers_short(loc)
    if markers:
        out.append(f"Markers: {markers}")
    # Lords currently here
    here = [l for l in state.lords.values() if l.cylinder.kind == "locale" and l.cylinder.locale_id == loc_id]
    if here:
        out.append("")
        out.append("Lords here:")
        for l in here:
            out.append(f"  {_SIDE_SHORT[l.side]} {l.name}  forces=[{_forces_short(l.forces)}]")
    # Adjacent locales (via Ways)
    from almoravid.static_data import neighbors
    nbrs = neighbors(loc_id)
    if nbrs:
        out.append("")
        out.append("Neighbors:")
        for nid, way_type in nbrs:
            out.append(f"  {nid} ({way_type})")
    return "\n".join(out)
