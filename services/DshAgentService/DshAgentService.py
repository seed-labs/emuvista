"""Declare DSH agents and bind them to SEED nodes."""
from pathlib import Path, PurePosixPath
import re

from seedemu.core import Service

from ._constants import RUNTIME_IMAGE
from .DshAgentServer import DshAgentServer


class DshAgentService(Service):
    def __init__(self, *, runtime_image=None, state_root=None):
        super().__init__()
        self.addDependency("Base", False, False)
        self.addDependency("Routing", False, False)
        self.runtime_image = RUNTIME_IMAGE if runtime_image is None else runtime_image
        if not isinstance(self.runtime_image, str) or not re.fullmatch(r"[A-Za-z0-9._/@:-]+", self.runtime_image) or self.runtime_image.startswith(("-", "/")):
            raise ValueError("Invalid Docker runtime image")
        self.state_root = PurePosixPath("/var/lib/dshagent" if state_root is None else state_root)
        if not self.state_root.is_absolute() or ".." in self.state_root.parts:
            raise ValueError("state_root must be an absolute container path without '..'")

    def getName(self):
        return "DshAgentService"

    def install(self, name, *, bundles=(), config=None):
        if not isinstance(name, str) or not re.fullmatch(r"[a-zA-Z0-9_-]{1,48}", name):
            raise ValueError("Invalid DSH agent instance name")
        targets = self.getPendingTargets()
        if name in targets:
            raise ValueError(f"Duplicate DSH agent instance: {name}")
        server = DshAgentServer(name, tuple(Path(p).resolve() for p in bundles),
                                Path(config).resolve() if config is not None else None,
                                self.runtime_image, str(self.state_root / name))
        targets[name] = server
        return server

    def configure(self, emulator):
        occupied = {}
        for name in self.getPendingTargets():
            node = emulator.getBindingFor(name)
            key = node.getAsn(), node.getName()
            if key in occupied:
                raise ValueError(f"Agents {occupied[key]} and {name} are both bound to AS{key[0]}/{key[1]}")
            occupied[key] = name
        super().configure(emulator)

    def print(self, indent):
        return " " * indent + "DshAgentService layer\n"


def dshagent(*, runtime_image=None, state_root=None):
    return DshAgentService(runtime_image=runtime_image, state_root=state_root)
