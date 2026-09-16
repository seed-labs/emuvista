"""Pytest configuration shared by Docker-backed DNS tests."""

from collections.abc import Callable
from typing import Any

import pytest


def pytest_configure(config: pytest.Config) -> None:
    """Show one PASSED/FAILED line per DNS test by default."""

    if config.option.verbose == 0:
        config.option.verbose = 1
    config.addinivalue_line(
        "markers",
        "docker_backend: requires a running Docker-backed SEED-Emulator deployment (B02a)",
    )


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    """Mark every test collected in this directory as a Docker-backend test."""

    for item in items:
        item.add_marker(pytest.mark.docker_backend)


def pytest_addoption(parser: pytest.Parser) -> None:
    """Add DNS-test-specific command-line options."""

    parser.addoption(
        "--show-dns-results",
        action="store_true",
        default=False,
        help="print DNS tool results while running tests",
    )


@pytest.fixture
def show_dns_result(
    pytestconfig: pytest.Config,
    capsys: pytest.CaptureFixture[str],
) -> Callable[[Any], None]:
    """Return a printer enabled by the --show-dns-results option."""

    def show(result: Any) -> None:
        if pytestconfig.getoption("show_dns_results"):
            with capsys.disabled():
                print(result.model_dump_json(indent=2))

    return show
