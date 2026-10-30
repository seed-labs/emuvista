#!/usr/bin/env python3
# encoding: utf-8
"""H15 chat: a B00-style mini Internet carrying a Tinode chat service."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent


def _find_repo_root(start: Path) -> Path:
    """Walk up from this script until the emuvista repository root is found."""
    for candidate in (start, *start.parents):
        if (candidate / "services" / "ChatService").is_dir():
            return candidate
    raise FileNotFoundError(
        "Cannot find the emuvista repository root above {} "
        "(looked for a services/ChatService directory).".format(start)
    )


def _find_seed_root(repo_root: Path) -> Path:
    """Locate the SEED checkout, preferring an explicit SEEDEMU_ROOT."""
    candidates = []
    if os.environ.get("SEEDEMU_ROOT"):
        candidates.append(Path(os.environ["SEEDEMU_ROOT"]).expanduser())
    for ancestor in (repo_root, *repo_root.parents):
        candidates.append(ancestor / "seed-emulator")
        candidates.append(ancestor)
    for candidate in candidates:
        if (candidate / "seedemu" / "__init__.py").is_file():
            return candidate.resolve()
    raise FileNotFoundError("Cannot find Seed Emulator. Set SEEDEMU_ROOT to its repository path.")


# Both are discovered by walking upwards, so this example works at any depth
# under examples/ instead of depending on a fixed number of parent levels.
REPO_ROOT = _find_repo_root(SCRIPT_DIR)
SEED = _find_seed_root(REPO_ROOT)

for p in (str(SEED), str(REPO_ROOT)):
    if p not in sys.path:
        sys.path.insert(0, p)

# These imports require the repository paths added above.
from seedemu.compiler import Docker, Platform  # noqa: E402
from seedemu.core import Binding, Emulator, Filter  # noqa: E402

from examples.internet.B00_mini_internet import mini_internet  # noqa: E402
from services.ChatService import ChatService  # noqa: E402

TINODE_GRPC_VERSION = os.environ.get("TINODE_GRPC_VERSION")

SERVER_VNODE = "chat151"
SERVER_ASN = 151
CLIENT_VNODES = [
    ("cli152", 152),
    ("cli153", 153),
    ("cli154", 154),
    ("cli160", 160),
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build the H15 chat service example.")
    parser.add_argument("legacy_platform", nargs="?", choices=["amd"])
    parser.add_argument("--platform", choices=["amd"])
    parser.add_argument("--output", default=str(SCRIPT_DIR / "output"))
    parser.add_argument("--dumpfile")
    parser.add_argument("--override", dest="override", action="store_true", default=True)
    parser.add_argument("--no-override", dest="override", action="store_false")
    parser.add_argument("--skip-render", dest="render", action="store_false", default=True)
    parser.add_argument("--hosts-per-as", type=int, default=2)
    args = parser.parse_args()
    args.platform = args.platform or args.legacy_platform or "amd"
    return args


def resolve_platform(name: str) -> Platform:
    if name != "amd":
        raise ValueError("H15 supports only the amd platform.")
    return Platform.AMD64


def build_emulator(hosts_per_as: int = 2) -> Emulator:
    emu = mini_internet.build_emulator(hosts_per_as=hosts_per_as)

    chat = ChatService(
        tinode_grpc_version=TINODE_GRPC_VERSION,
    )

    chat.installServer(SERVER_VNODE)
    emu.addBinding(Binding(SERVER_VNODE, filter=Filter(asn=SERVER_ASN, nodeName="host_0")))

    for vnode, asn in CLIENT_VNODES:
        chat.installClient(vnode, server_vnode=SERVER_VNODE)
        emu.addBinding(Binding(vnode, filter=Filter(asn=asn, nodeName="host_0")))

    emu.addLayer(chat)
    return emu


def run(
    dumpfile=None,
    hosts_per_as=2,
    output=None,
    platform=Platform.AMD64,
    override=True,
    render=True,
):
    if platform != Platform.AMD64:
        raise ValueError("H15 currently uses the Tinode linux-amd64 release.")

    emu = build_emulator(hosts_per_as=hosts_per_as)
    if dumpfile is not None:
        emu.dump(dumpfile)
        print("Saved chat emulator to {}".format(dumpfile))
        return

    if render:
        emu.render()

    output_dir = Path(output or SCRIPT_DIR / "output").resolve()
    output_dir.parent.mkdir(parents=True, exist_ok=True)
    docker = Docker(internetMapEnabled=True, platform=platform)
    emu.compile(docker, str(output_dir), override=override)
    print("Generated H15 chat Docker output in {}".format(output_dir))


def main() -> int:
    args = parse_args()
    run(
        dumpfile=args.dumpfile,
        hosts_per_as=args.hosts_per_as,
        output=str(Path(args.output).resolve()),
        platform=resolve_platform(args.platform),
        override=args.override,
        render=args.render,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
