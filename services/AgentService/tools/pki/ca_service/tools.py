"""Runtime tools; configuration changes explicitly require a later CA restart."""

from pathlib import Path

from ..execution import RuntimeBackend
from ..shared.runtime import NodeObservation, observe


class CAServiceTools:
    def __init__(self, backend: RuntimeBackend) -> None:
        self._backend = backend

    def _inspect_ca(self, action: str, source: str, **arguments: object) -> NodeObservation:
        return observe(
            self._backend,
            source,
            Path(__file__).with_name("probe.py"),
            {"action": action, **arguments},
        )

    def inspect_ca_service(self, source: str, config_path: str) -> NodeObservation:
        return self._inspect_ca("service", source, config_path=config_path)

    def inspect_ca_events(self, source: str, log_path: str, limit: int) -> NodeObservation:
        return self._inspect_ca("events", source, log_path=log_path, limit=limit)
