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
        parts.append(f"SeatMarkers({','.join(loc.seat_marker_lord_ids)})")
    return " ".join(parts)


# ---------------------------------------------------------------------------
# Summary view — LLM-budget-friendly
# ---------------------------------------------------------------------------

def render_sagrajas(state: GameState) -> str:
    """Battle-only Sagrajas minigame view (Background Book pp.44-47): role,
    Attacker/Defender, each side's Lords + Forces + Capabilities, the held
    Battle Events, and the pending decision -- so an agent never inspects
    raw objects to understand the battle."""
    role = state.meta.sagrajas_role
    lines = ["=== Battle of Sagrajas — battle-only minigame "
             "(Almoravid Background Book) ===",
             f"Scenario {state.meta.scenario_letter}  |  Active: "
             f"{state.meta.active_player}",
             "A single self-contained Battle (Rules 4.4). Whoever wins the "
             "Battle wins the game."]
    if role is None:
        lines.append("DECISION: the Christian player chooses to ATTACK "
                     "(historical) or DEFEND. Legal actions: sagrajas_attack, "
                     "sagrajas_defend.")
        atk_side = None
    else:
        atk_side = "christian" if role == "attack" else "muslim"
        def_side = "muslim" if role == "attack" else "christian"
        marshal = "alfonso" if role == "attack" else "yusuf"
        if state.meta.phase == "ended":
            lines.append(f"RESULT: winner={state.score.winner} "
                         f"({state.score.victory_reason}).")
        else:
            lines.append(f"ROLE: Christians {role.upper()}  ->  ATTACKER = "
                         f"{atk_side} (Marshal {marshal} at Front center, "
                         f"4.4.1), DEFENDER = {def_side}. "
                         f"Legal action: resolve_battle.")
    held = state.decks.this_levy_events
    sidewide = [c.card_id for c in state.decks.capabilities_in_play
                if c.scope == "side_wide"]
    for sd in ("christian", "muslim"):
        on_map = [(lid, lord) for lid, lord in state.lords.items()
                  if lord.side == sd and lord.cylinder.kind == "locale"]
        tag = ""
        if atk_side is not None:
            tag = " (ATTACKER)" if sd == atk_side else " (DEFENDER)"
        lines.append(f"\n{sd.capitalize()} army{tag}:")
        for lid, lord in on_map:
            caps = ",".join(lord.capabilities) if lord.capabilities else "-"
            lines.append(f"  {lord.name} [{lid}]  forces=[{_forces_short(lord.forces)}]"
                         f"  caps={caps}")
        h = held.get(sd, [])
        if h:
            lines.append(f"  Held Battle Events: {', '.join(h)}")
    if sidewide:
        lines.append(f"\nSide-wide capabilities in play: {', '.join(sorted(sidewide))}")
    lines.append("\nCard key: C4/C5 Arqueros & M4/M5 Alrama = Bowmen; "
                 "C7 Jabalinas & M3 Harbah = Javelins (up to 4 Unarmored, "
                 "1 Round); C8 Cantador (+1 Melee R1, up to 4 K/S); C9 Slingers; "
                 "C18 Milites & C22 Bishoprics = added units; M6 Feigned Retreat; "
                 "M7 Spear Wall; M10 Andalusians (Light Horse Evade); M15 Saqalibah.")
    return "\n".join(lines)


def render_summary(state: GameState) -> str:
    if state.meta.phase == "battle" or state.meta.scenario_letter == "S":
        return render_sagrajas(state)
    box = state.calendar.current_box
    season = state.calendar.boxes[box - 1].season
    turn_type = state.calendar.boxes[box - 1].turn_type
    year = _year_for_box(box)
    # Playtest F6: the running state.score tracker can lag the board
    # (it doesn't reflect Taifa-status VP, the Taifas box, etc.). Show
    # the AUTHORITATIVE board VP (recomputed via compute_final_vp, the
    # same function the final verdict uses) as the primary figure.
    try:
        from almoravid.campaign import compute_final_vp
        _cvp, _mvp = compute_final_vp(state)
        _vp = f"VP (board): C {_cvp:g} / M {_mvp:g}"
    except Exception:
        _vp = f"VP: C {state.score.christian:g} / M {state.score.muslim:g}"
    header = (
        f"=== Almoravid — Scenario {state.meta.scenario_letter} "
        f"({state.meta.scenario_id}) ===\n"
        f"Box {box} ({_SEASON_SHORT[season]} {year} {turn_type})  |  "
        f"Active: {state.meta.active_player}  |  "
        f"{_vp}"
    )

    lines = [header, ""]
    # Phase 7b: show the final verdict once the scenario has ended.
    if state.meta.phase == "ended" and state.score.winner is not None:
        lines.append(
            f"GAME OVER — winner: {state.score.winner.upper()}  "
            f"(final VP: C {state.score.christian_final} / "
            f"M {state.score.muslim_final})"
        )
        if state.score.victory_reason:
            lines.append(f"  {state.score.victory_reason}")
        lines.append("")

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
            lord for lord in state.lords.values()
            if lord.side == side and lord.cylinder.kind == "locale"
        ]
        if lords_on_map:
            lines.append(f"{side.title()} Lords on map:")
            for lord in lords_on_map:
                vassal_ready = sum(1 for v in lord.vassals if v.ready)
                lines.append(
                    f"  {lord.name} {_cylinder_short(lord)}  "
                    f"forces=[{_forces_short(lord.forces)}]  "
                    f"assets=[{_assets_short(lord.assets)}]  "
                    f"V={vassal_ready}/{len(lord.vassals)}  "
                    f"caps={','.join(lord.capabilities) or '—'}"
                )

    # Lords elsewhere (calendar / set_aside / removed)
    elsewhere = [lord for lord in state.lords.values() if lord.cylinder.kind != "locale"]
    if elsewhere:
        lines.append("")
        lines.append("Lords elsewhere:")
        for lord in sorted(elsewhere, key=lambda x: (x.side, x.cylinder.kind, x.name)):
            lines.append(
                f"  {_SIDE_SHORT[lord.side]} {lord.name}: {_cylinder_short(lord)}"
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
    if state.meta.phase == "battle" or state.meta.scenario_letter == "S":
        return render_sagrajas(state)
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
    for lid, lord in sorted(state.lords.items(), key=lambda kv: (kv[1].side, kv[1].name)):
        out.append(
            f"  {_SIDE_SHORT[lord.side]} {lord.name} ({lid}) "
            f"F{lord.fealty}/S{lord.service_rating}/L{lord.lordship_rating}/C{lord.command_rating}  "
            f"{_cylinder_short(lord)}"
        )
        if lord.forces:
            out.append(f"      forces: {_forces_short(lord.forces)}")
        if lord.assets:
            out.append(f"      assets: {_assets_short(lord.assets)}")
        if lord.capabilities:
            out.append(f"      caps:   {','.join(lord.capabilities)}")
        if lord.vassals:
            out.append(
                "      vassals: " + ", ".join(
                    f"{v.name}{'[r]' if v.ready else '[d]'}" for v in lord.vassals
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
    lord = state.lords[lord_id]
    out = [
        f"=== Lord: {lord.name} ({lord_id}) ===",
        f"Side: {lord.side}  |  Marshal: —  |  Taifa Lord: {lord.is_taifa}"
        + (f" ({lord.home_taifa})" if lord.home_taifa else ""),
        f"Ratings: Fealty {lord.fealty}  Service {lord.service_rating}  "
        f"Lordship {lord.lordship_rating}  Command {lord.command_rating}",
        f"Seats (printed): {', '.join(lord.seats) if lord.seats else '—'}",
        f"Cylinder: {_cylinder_short(lord)}",
        f"In Stronghold: {lord.in_stronghold}",
        "",
        f"Forces: {_forces_short(lord.forces)}",
        f"Assets: {_assets_short(lord.assets)}",
        f"Capabilities (this_lord): {', '.join(lord.capabilities) or '—'}",
    ]
    if lord.vassals:
        out.append("")
        out.append("Vassals:")
        for v in lord.vassals:
            ready = "ready" if v.ready else "Disbanded"
            out.append(f"  {v.name} — {_forces_short(v.forces)} — svc {v.service_cost} — {ready}")
    if lord.routed_units:
        out.append("")
        out.append(f"Routed units (this engagement): {_forces_short(lord.routed_units)}")
    out.append("")
    out.append("Per-card / per-Levy flags:")
    out.append(f"  moved_fought={lord.moved_fought}  just_arrived_this_levy={lord.just_arrived_this_levy}")
    out.append(f"  lordship_used={lord.lordship_used}  first_march_used_this_card={lord.first_march_used_this_card}")
    out.append(f"  raiders_used_this_card={lord.raiders_used_this_card}")
    return "\n".join(out)


def _render_focus_locale(state: GameState, loc_id: str) -> str:
    loc = state.locales[loc_id]
    out = [
        f"=== Locale: {loc.name} ({loc_id}) ===",
        f"Territory: {loc.territory}",
        f"Base type: {loc.base_type}"
        + (f" (Cap {state.locales[loc_id]})" if False else ""),
        f"Gardens: {loc.has_gardens}  |  Port: {loc.has_port}  |  Reconquista target: {loc.is_reconquista_target}",
        f"Printed seats: {', '.join(loc.printed_seat_lord_ids) or '—'}  |  "
        f"Seat markers: {', '.join(loc.seat_marker_lord_ids) or '—'}",
    ]
    markers = _locale_markers_short(loc)
    if markers:
        out.append(f"Markers: {markers}")
    # Lords currently here
    here = [lord for lord in state.lords.values() if lord.cylinder.kind == "locale" and lord.cylinder.locale_id == loc_id]
    if here:
        out.append("")
        out.append("Lords here:")
        for lord in here:
            out.append(f"  {_SIDE_SHORT[lord.side]} {lord.name}  forces=[{_forces_short(lord.forces)}]")
    # Adjacent locales (via Ways)
    from almoravid.static_data import neighbors
    nbrs = neighbors(loc_id)
    if nbrs:
        out.append("")
        out.append("Neighbors:")
        for nid, way_type in nbrs:
            out.append(f"  {nid} ({way_type})")
    return "\n".join(out)
