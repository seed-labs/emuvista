#!/usr/bin/env python3
"""Extend H16 with an HTTP tool-service and a browser-free social media agent."""

import argparse
import json
import os
import shutil
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "H16_socialmedia"))
from socialmedia import build_scenario, configure_bundle, copy_application_image  # isort: skip

# H16 initializes the local SeedEmu and service import paths.
from seedemu.compiler import Docker, Platform


def generate(output: Path, platform: str) -> None:
    # Capture the build host's socket group as the Compose default. An explicit
    # DOCKER_GID can override it during generation or later when starting Compose.
    docker_gid = os.environ.get("DOCKER_GID")
    if not docker_gid:
        try:
            docker_gid = str(Path("/var/run/docker.sock").stat().st_gid)
        except FileNotFoundError:
            docker_gid = None
    if docker_gid is not None and not (docker_gid.isascii() and docker_gid.isdecimal()):
        raise ValueError("DOCKER_GID must be a numeric group ID")
    socket_group = (
        "${DOCKER_GID:-" + docker_gid + "}"
        if docker_gid is not None
        else "${DOCKER_GID:?Set DOCKER_GID to the deployment host Docker socket group}"
    )
    emu, mastodon = build_scenario()
    emu.render()
    compiler = Docker(platform=Platform.AMD64 if platform == "amd" else Platform.ARM64)
    configure_bundle(mastodon, compiler)
    compiler.attachCustomContainer(
        compose_entry=f"""    tool-service:
        build: ./tool-service
        init: true
        group_add: ["{socket_group}"]
        volumes:
            - /var/run/docker.sock:/var/run/docker.sock
        environment:
            DOCKER_HOST: unix:///var/run/docker.sock
""",
        asn=151,
        net="net0",
        ip_address="10.151.0.81",
        node_name="tool-service",
        show_on_map=True,
    )
    compiler.attachCustomContainer(
        compose_entry=f"""    socialmedia-agent:
        build: ./socialmedia-agent
        volumes:
            - type: bind
              source: {json.dumps(str(HERE / ".env"))}
              target: /opt/.env
              read_only: true
              bind:
                  create_host_path: false
        init: true
        depends_on:
            tool-service:
                condition: service_healthy
        extra_hosts:
            - "host.docker.internal:host-gateway"
""",
        asn=151,
        net="net0",
        ip_address="10.151.0.80",
        port_forwarding="127.0.0.1:18089:8089/tcp",
        env=[
            "TOOL_SERVICE_URL=http://10.151.0.81:8000/api/v1",
        ],
        node_name="socialmedia-agent",
        show_on_map=True,
    )
    emu.compile(compiler, str(output), override=True)
    copy_application_image(output)
    context = output / "socialmedia-agent"
    context.mkdir(exist_ok=True)
    for name in ("Dockerfile", "start.sh"):
        shutil.copyfile(HERE / "container" / name, context / name)
    # Custom containers are outside CAService's node trust installation.
    shutil.copyfile(
        HERE.parent / "H16_socialmedia/runtime/h14-ca/.step/certs/root_ca.crt",
        context / "h14-root-ca.crt",
    )
    shutil.copytree(
        HERE / "agent",
        context / "agent",
        dirs_exist_ok=True,
        ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
    )
    service = HERE.parents[1] / "tool-service"
    target = output / "tool-service"
    target.mkdir(exist_ok=True)
    for name in ("Dockerfile", "pyproject.toml", "README.md"):
        shutil.copyfile(service / name, target / name)
    shutil.copytree(
        service / "seedemu_tool_service",
        target / "seedemu_tool_service",
        dirs_exist_ok=True,
        ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
    )
    print(f"Generated {output}; the agent discovers tools from tool-service.")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=HERE / "output")
    parser.add_argument("--platform", choices=["amd", "arm"], default="amd")
    args = parser.parse_args()
    generate(args.output.resolve(), args.platform)


if __name__ == "__main__":
    main()
