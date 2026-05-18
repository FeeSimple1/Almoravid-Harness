"""Almoravid CLI entrypoint.

Phase 0: only `version` and `scenarios` are functional. All gameplay
commands raise NotImplementedError tagged with the phase that will
implement them.
"""

from __future__ import annotations

import json
from pathlib import Path

import typer

from almoravid import __version__
from almoravid.scenarios import list_scenarios, load_scenario_raw

app = typer.Typer(
    name="almoravid",
    help="Almoravid Harness CLI.",
    no_args_is_help=True,
    add_completion=False,
)


@app.command()
def version() -> None:
    """Print the harness version."""
    typer.echo(__version__)


@app.command()
def scenarios() -> None:
    """List bundled scenarios."""
    for name in list_scenarios():
        typer.echo(name)


@app.command(name="scenario-show")
def scenario_show(name: str) -> None:
    """Print a scenario's raw JSON (Phase 0: raw loader only)."""
    data = load_scenario_raw(name)
    typer.echo(json.dumps(data, indent=2))


@app.command(name="new-game")
def new_game(scenario: str, seed: int = 0) -> None:
    """Create a new game state from a scenario.

    Phase 1: scenario -> GameState conversion (static_data.py / scenarios.py).
    """
    raise NotImplementedError(
        "Phase 1: scenario loader produces GameState. "
        "See BRIEF.md 'Project Layout' for the build order."
    )


@app.command(name="legal-moves")
def legal_moves(state_file: Path) -> None:
    """List legal moves for the side whose turn it is.

    Phase 2: legal-moves enumeration (legal_moves.py).
    """
    raise NotImplementedError("Phase 2: see legal_moves.py (not yet created).")


@app.command()
def do(state_file: Path, action: str) -> None:
    """Execute an action against the state.

    Phase 2: action dispatcher (actions.py).
    """
    raise NotImplementedError("Phase 2: see actions.py (not yet created).")


@app.command(name="generate-schema")
def generate_schema() -> None:
    """Regenerate state.schema.json from the pydantic GameState model.

    Mirrors `scripts/generate_schema.py` for convenience.
    """
    from almoravid.state import GameState

    schema_path = Path(__file__).parent / "data" / "schema" / "state.schema.json"
    schema = GameState.model_json_schema()
    schema_path.write_text(json.dumps(schema, indent=2) + "\n")
    typer.echo(f"Wrote {schema_path}")


if __name__ == "__main__":
    app()
