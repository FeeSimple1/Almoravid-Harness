"""Almoravid CLI entrypoint."""

from __future__ import annotations

import json
from pathlib import Path

import typer

from almoravid import __version__
from almoravid.scenarios import list_scenarios, load_scenario, load_scenario_raw

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
    """Print a scenario's raw JSON."""
    data = load_scenario_raw(name)
    typer.echo(json.dumps(data, indent=2))


@app.command(name="new-game")
def new_game(scenario: str, seed: int = 0) -> None:
    """Create a new GameState from a scenario and print summary stats."""
    state = load_scenario(scenario, seed=seed)
    typer.echo(f"Scenario: {state.meta.scenario_letter} ({state.meta.scenario_id})")
    typer.echo(f"Active player: {state.meta.active_player}")
    typer.echo(f"Current Calendar box: {state.calendar.current_box}")
    typer.echo(f"Lords: {len(state.lords)} ({sum(1 for l in state.lords.values() if l.cylinder.kind == 'locale')} mustered)")
    typer.echo(f"Locales: {len(state.locales)}")
    typer.echo(f"Taifas: {len(state.taifas)}")
    typer.echo(f"Ways: {len(state.ways)}")
    typer.echo(f"VP: Christian {state.score.christian} / Muslim {state.score.muslim}")


@app.command(name="legal-moves")
def legal_moves(state_file: Path) -> None:
    raise NotImplementedError("Phase 2: legal_moves.py")


@app.command()
def do(state_file: Path, action: str) -> None:
    raise NotImplementedError("Phase 2: actions.py")


@app.command(name="generate-schema")
def generate_schema() -> None:
    from almoravid.state import GameState
    schema_path = Path(__file__).parent / "data" / "schema" / "state.schema.json"
    schema = GameState.model_json_schema()
    schema_path.write_text(json.dumps(schema, indent=2) + "\n")
    typer.echo(f"Wrote {schema_path}")


if __name__ == "__main__":
    app()
