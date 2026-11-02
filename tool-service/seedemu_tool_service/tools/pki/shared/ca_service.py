"""Helpers for binding PKI operations to the configured SEEDEmu CA Service."""

from pathlib import Path
from seedemu_tool_service.backends import RuntimeBackend
from seedemu_tool_service.tools.pki.shared.runtime import NodeObservation, observe


def inspect_ca_service(
    backend: RuntimeBackend, source: str, config_path: str
) -> NodeObservation:
    return observe(
        backend,
        source,
        Path(__file__).parents[1] / "ca_service" / "probe.py",
        {"action": "service", "config_path": config_path},
    )


def ca_directory_urls(observation: NodeObservation) -> set[str]:
    urls: set[str] = set()
    for item in observation.data.get("acme_directory_urls", []):
        if isinstance(item, dict) and isinstance(item.get("directory_url"), str):
            urls.add(item["directory_url"])
    return urls
