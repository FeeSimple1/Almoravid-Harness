"""Almoravid CLI entrypoint.

State-file flow (mirrors the Nevsky harness):

  almoravid new <scenario> --output state.json [--seed N]   # initialize
  almoravid state <state.json>                              # one-line summary
  almoravid view <state.json> [--mode {summary|verbose|focus} [--focus-target ID]]
  almoravid legal <state.json>                              # JSON-per-line
  almoravid do <state.json> <action.json> [--output new_state.json]
  almoravid pending <state.json>                            # owed response (if any)
  almoravid history <state.json> [--tail N]
  almoravid scenarios                                       # list bundled scenarios

State persistence is GameState.model_dump_json / model_validate_json.
Actions are JSON files (not shell strings) to dodge quoting issues.
`do` defaults to overwriting state_file; --output writes a fresh copy.

Exit codes:
  0  success
  1  bad usage (unknown command, malformed args, etc.)
  2  IllegalAction or parse failure (do-able, not a harness bug)
"""

from __future__ import annotations

import json
from pathlib import Path

import typer

from almoravid import __version__
from almoravid.actions import IllegalAction, apply_action
from almoravid.legal_moves import legal_moves
from almoravid.scenarios import list_scenarios, load_scenario, load_scenario_raw
from almoravid.state import GameState

app = typer.Typer(
    name="almoravid",
    help="Almoravid Harness CLI.",
    no_args_is_help=True,
    add_completion=False,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _read_state(path: Path) -> GameState:
    return GameState.model_validate_json(path.read_text(encoding="utf-8"))


def _write_state(state: GameState, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(state.model_dump_json(indent=2) + "\n", encoding="utf-8")


# ---------------------------------------------------------------------------
# Inspection commands
# ---------------------------------------------------------------------------


@app.command()
def version() -> None:
    """Print the harness version."""
    typer.echo(__version__)


@app.command()
def scenarios() -> None:
    """List bundled scenarios (no state needed)."""
    for name in list_scenarios():
        typer.echo(name)


@app.command(name="scenario-show")
def scenario_show(name: str) -> None:
    """Print a scenario's raw JSON (the setup file, not a live state)."""
    data = load_scenario_raw(name)
    typer.echo(json.dumps(data, indent=2))


# ---------------------------------------------------------------------------
# State lifecycle
# ---------------------------------------------------------------------------


@app.command()
def new(
    scenario: str = typer.Argument(...,
        help="Scenario id (run `almoravid scenarios` to list)."),
    output: Path = typer.Option(...,
        "--output", "-o",
        help="Path to write the new state JSON file."),
    seed: int = typer.Option(0, "--seed",
        help="RNG seed; stored in state for determinism."),
) -> None:
    """Initialize a state file from a scenario."""
    try:
        state = load_scenario(scenario, seed=seed)
    except FileNotFoundError as e:
        typer.echo(f"error: {e}", err=True)
        raise typer.Exit(code=1)
    _write_state(state, output)
    typer.echo(f"wrote {output}")


@app.command()
def state(
    state_file: Path = typer.Argument(..., exists=True, dir_okay=False),
) -> None:
    """One-line summary: scenario, box, phase, active, VPs."""
    s = _read_state(state_file)
    box = s.calendar.current_box
    season = s.calendar.boxes[box - 1].season
    typer.echo(
        f"Scenario {s.meta.scenario_letter} ({s.meta.scenario_id})  "
        f"box {box} {season}  "
        f"phase={s.meta.phase}"
        + (f" levy={s.meta.levy_step}" if s.meta.levy_step else "")
        + (f" camp={s.meta.campaign_step}" if s.meta.campaign_step else "")
        + f"  active={s.meta.active_player}  "
        f"VP=C{s.score.christian:g}/M{s.score.muslim:g}"
    )


@app.command()
def view(
    state_file: Path = typer.Argument(..., exists=True, dir_okay=False),
    mode: str = typer.Option("summary", "--mode", "-m",
        help="summary | verbose | focus"),
    focus_target: str = typer.Option("", "--focus-target",
        help="Lord or Locale id (required for --mode focus)."),
) -> None:
    """Render a state file."""
    from almoravid.render import render_focus, render_summary, render_verbose
    s = _read_state(state_file)
    if mode == "summary":
        typer.echo(render_summary(s))
    elif mode == "verbose":
        typer.echo(render_verbose(s))
    elif mode == "focus":
        if not focus_target:
            typer.echo("error: --focus-target required for --mode focus",
                       err=True)
            raise typer.Exit(code=1)
        try:
            typer.echo(render_focus(s, focus_target))
        except ValueError as e:
            typer.echo(f"error: {e}", err=True)
            raise typer.Exit(code=1)
    else:
        typer.echo(f"error: unknown mode {mode!r}; use summary | verbose | focus",
                   err=True)
        raise typer.Exit(code=1)


@app.command()
def legal(
    state_file: Path = typer.Argument(..., exists=True, dir_okay=False),
) -> None:
    """Emit one JSON action per line for every legal move in this state."""
    s = _read_state(state_file)
    for m in legal_moves(s):
        typer.echo(json.dumps(m, sort_keys=True))


# Keep the old name as an alias for tests + back-compat
@app.command(name="legal-moves", hidden=True)
def legal_moves_alias(
    state_file: Path = typer.Argument(..., exists=True, dir_okay=False),
) -> None:
    legal(state_file)


@app.command()
def do(
    state_file: Path = typer.Argument(..., exists=True, dir_okay=False),
    action_file: Path = typer.Argument(..., exists=True, dir_okay=False),
    output: Path | None = typer.Option(None, "--output", "-o",
        help="Write post-action state here (default: overwrite state_file)."),
) -> None:
    """Apply one action to a state, write the resulting state back."""
    s = _read_state(state_file)
    try:
        action = json.loads(action_file.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        typer.echo(f"error: action_file is not valid JSON: {e}", err=True)
        raise typer.Exit(code=2)
    try:
        result = apply_action(s, action)
    except IllegalAction as e:
        typer.echo(f"illegal_action[{e.code}]: {e}", err=True)
        raise typer.Exit(code=2)
    target = output if output is not None else state_file
    _write_state(s, target)
    typer.echo(f"OK: {json.dumps(result, sort_keys=True)}")


@app.command()
def pending(
    state_file: Path = typer.Argument(..., exists=True, dir_okay=False),
) -> None:
    """Report the PendingDecision (if any) — what response is owed."""
    s = _read_state(state_file)
    if s.pending is None:
        typer.echo("none")
    else:
        typer.echo(json.dumps(s.pending.model_dump(), indent=2))


@app.command()
def history(
    state_file: Path = typer.Argument(..., exists=True, dir_okay=False),
    tail: int = typer.Option(20, "--tail", "-n",
        help="Show last N entries (default 20; 0 = all)."),
) -> None:
    """Print the recent action history."""
    s = _read_state(state_file)
    entries = s.history if tail == 0 else s.history[-tail:]
    for h in entries:
        typer.echo(
            f"T{h.turn_index} {h.actor:>9s}  {h.action}: {h.summary}"
        )


# ---------------------------------------------------------------------------
# Maintenance commands
# ---------------------------------------------------------------------------


@app.command(name="generate-schema")
def generate_schema() -> None:
    """Regenerate state.schema.json from the pydantic GameState model."""
    schema_path = (Path(__file__).parent
                   / "data" / "schema" / "state.schema.json")
    schema = GameState.model_json_schema()
    schema_path.write_text(json.dumps(schema, indent=2) + "\n")
    typer.echo(f"wrote {schema_path}")


if __name__ == "__main__":
    app()
