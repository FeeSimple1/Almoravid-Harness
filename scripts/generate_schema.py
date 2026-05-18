"""Regenerate `state.schema.json` from the pydantic GameState model."""

from __future__ import annotations

import json
import sys
from pathlib import Path

# Allow running this script without installing the package
REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "src"))

from almoravid.state import GameState  # noqa: E402


def main() -> None:
    schema = GameState.model_json_schema()
    out = REPO_ROOT / "src" / "almoravid" / "data" / "schema" / "state.schema.json"
    out.write_text(json.dumps(schema, indent=2) + "\n")
    print(f"Wrote {out} ({out.stat().st_size} bytes, {len(schema.get('$defs', {}))} defs)")


if __name__ == "__main__":
    main()
