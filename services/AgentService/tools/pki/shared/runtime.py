"""Run bounded, fixed Python probes in a node, never interpolating caller input."""

import json
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from ..execution import RuntimeBackend


class NodeObservation(BaseModel):
    source: str
    successful: bool
    data: dict[str, Any] = Field(default_factory=dict)
    exit_code: int
    error: str | None = None


_RUNNER = """
import json, sys
try:
    data = probe(json.loads(sys.argv[1]))
    print(json.dumps({"data": data}))
except Exception as error:
    # Do not expose config contents, credentials, or arbitrary exception messages.
    category = str(error) if type(error).__name__ == "ProbeError" else type(error).__name__
    print(json.dumps({"error": category}))
    sys.exit(1)
"""


def observe(
    backend: RuntimeBackend, source: str, script: Path, arguments: dict[str, Any]
) -> NodeObservation:
    result = backend.execute(
        source,
        ["timeout", "45", "python3", "-c", script.read_text() + _RUNNER, json.dumps(arguments)],
    )
    try:
        payload = json.loads(result.stdout)
        data = payload.get("data", {})
        if not isinstance(data, dict):
            raise ValueError("Invalid probe data")
        error = payload.get("error")
    except (ValueError, AttributeError):
        data, error = {}, "Invalid probe response; ensure python3 is installed in the node"
    return NodeObservation(
        source=source,
        successful=result.exit_code == 0 and error is None,
        data=data,
        exit_code=result.exit_code,
        error=error,
    )
