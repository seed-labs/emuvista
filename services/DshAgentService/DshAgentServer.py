"""Build an individual DSH agent on a SEED node."""
from copy import deepcopy
import json
from pathlib import Path
import re
import shlex

from seedemu.core import Server
import yaml

from ._constants import BASE, LABEL_KEY, VERSION

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
PACKAGE = re.compile(r"(?:@[a-z0-9][\w.-]*/)?[a-z0-9][\w.-]*")


def _mapping(value, source):
    if not isinstance(value, dict) or any(not isinstance(k, str) for k in value):
        raise ValueError(f"{source}: expected a mapping with string keys")
    return value


def _merge(base, override):
    result = deepcopy(base)
    for key, value in override.items():
        current = result.get(key)
        result[key] = _merge(current, value) if isinstance(current, dict) and isinstance(value, dict) else deepcopy(value)
    return result


def _yaml(path):
    try:
        return yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise ValueError(f"Cannot read configuration {path}") from exc


def _manifest(path):
    try:
        return _mapping(json.loads((path / "package.json").read_text()), path)
    except (OSError, ValueError) as exc:
        raise ValueError(f"Invalid package directory: {path}") from exc


class _Packages:
    def __init__(self, node):
        self.node = node
        self.paths = {}
        self.visiting = set()

    def stage(self, source, bundle=False):
        source = source.resolve()
        manifest = _manifest(source)
        name = manifest.get("name")
        if not isinstance(name, str) or not PACKAGE.fullmatch(name):
            raise ValueError(f"{source}: invalid npm package name")
        if source in self.visiting:
            raise ValueError(f"{source}: cyclic local dependencies")
        if name in self.paths:
            previous, destination = self.paths[name]
            if previous != source:
                raise ValueError(f"Multiple package sources for {name}: {previous} and {source}")
            return name, destination
        destination = f"{BASE}/packages/{name}"
        self.visiting.add(source)
        rewritten = False
        for section in ("dependencies", "optionalDependencies", "devDependencies"):
            for key, spec in manifest.get(section, {}).items():
                if isinstance(spec, str) and spec.startswith(("link:", "file:")):
                    target, path = self.stage(source / spec.split(":", 1)[1])
                    if key != target:
                        raise ValueError(f"{source}: local dependency {key} points to {target}")
                    manifest[section][key] = "link:" + path
                    rewritten = True

        self.paths[name] = source, destination
        self.visiting.remove(source)
        scripts = manifest.get("scripts", {})
        allowed = {"pnpm-lock.yaml", "tsconfig.json", "README.md", "LICENSE"}
        if bundle:
            patch = manifest.get("dsh", {}).get("bundle", {}).get("patch")
            if not isinstance(patch, str) or not (source / patch).resolve().is_relative_to(source):
                raise ValueError(f"{source}: expected a local DSH bundle patch")
            patch_source = (source / patch).resolve()
            if not patch_source.is_file():
                raise ValueError(f"{source}: missing bundle patch")
            self.node.importFile(str(patch_source), f"{destination}/{patch_source.relative_to(source)}")
        tree = ["src", "lib"] + ([] if "build" in scripts else ["dist"])
        for path in sorted(source.iterdir()):
            if path.is_symlink():
                continue
            if path.is_file() and (path.name in allowed or path.suffix in {".js", ".mjs", ".cjs", ".ts"}):
                self.node.importFile(str(path), f"{destination}/{path.name}")
            if path.is_dir() and path.name in tree:
                for child in sorted(path.rglob("*")):
                    if child.is_file() and not child.is_symlink() and child.resolve().is_relative_to(path) and not any(part.startswith(".") for part in child.relative_to(path).parts):
                        self.node.importFile(str(child), f"{destination}/{child.relative_to(source)}")
        self.node.setFile(f"{destination}/package.json", json.dumps(manifest))
        if any(manifest.get(k) for k in ("dependencies", "optionalDependencies", "devDependencies")) or "build" in scripts:
            frozen = not rewritten and (source / "pnpm-lock.yaml").is_file()
            install = "pnpm install --ignore-workspace " + ("--frozen-lockfile" if frozen else "--no-frozen-lockfile")
            if "build" in scripts:
                install += " && pnpm run build"
            self.node.addBuildCommandAtEnd(f"cd {shlex.quote(destination)} && {install}")
        return name, destination


class DshAgentServer(Server):
    def __init__(self, name, bundles, config, runtime_image, home):
        super().__init__()
        self.name = name
        self.bundles = bundles
        self.config = config
        self.runtime_image = runtime_image
        self.home = home

    def install(self, node):
        settings = _mapping(_yaml(self.config), self.config) if self.config else {}
        profile = _mapping(settings.get("profile", {}), self.config)
        profile_name = profile.get("name", "dshagent")
        template = profile.get("template", "web")
        startup = profile.get("startup", "manual")
        if not isinstance(profile_name, str) or not re.fullmatch(r"[a-zA-Z0-9_-]{1,60}", profile_name):
            raise ValueError(f"{self.config}: invalid profile name")
        if template != "web" or startup not in ("manual", "auto"):
            raise ValueError(f"{self.config}: expected web template and manual or auto startup")
        overrides = _mapping(settings.get("plugins", {}), self.config)
        used_overrides = {}
        occupied = {}
        runtime_rows = {}
        bundles = []
        aliases = set()
        packages = _Packages(node)

        def add_bundle(alias, package, directory, rows):
            if alias in aliases or any(b["package"] == package for b in bundles):
                raise ValueError(f"{self.name}: duplicate bundle {alias} ({package})")
            aliases.add(alias)
            bundles.append({"name": alias, "package": package, "directory": directory, "rows": rows})

        def prepare(row, scope, source):
            identifier = row["id"]
            key = scope, identifier
            if key in occupied:
                raise ValueError(f"Duplicate {scope} plugin {identifier}: {occupied[key]} and {source}")
            occupied[key] = source
            runtime_id = f"resident-{identifier}" if scope == "resident" else identifier
            if runtime_id in runtime_rows:
                raise ValueError(f"Duplicate DSH row {runtime_id}: {runtime_rows[runtime_id]} and {source}")
            runtime_rows[runtime_id] = source
            if identifier in overrides:
                if identifier in used_overrides:
                    raise ValueError(f"{self.config}: ambiguous override {identifier}: {used_overrides[identifier]} and {source}")
                used_overrides[identifier] = source
                override = _mapping(overrides[identifier], self.config)
                row["config"] = _merge(_mapping(row.get("config", {}), source), _mapping(override.get("config", {}), self.config))
            return {"id": identifier, "package": row["name"], "scope": scope, "row": identifier}

        def generated(alias, declarations):
            directory = f"{BASE}/bundles/{alias}"
            package = f"@emuvista/dshagent-{alias}"
            dependencies = {}
            inserted, rows, exports = [], [], {".": "./resident.mjs"}
            for row, scope, spec, source in declarations:
                info = prepare(row, scope, source)
                dependencies[row["name"]] = spec
                if scope == "resident":
                    target = row["name"]
                    entry = "resident-" + row["id"]
                    exports["./" + entry] = "./" + entry + ".mjs"
                    node.setFile(f"{directory}/{entry}.mjs", "import * as plugin from " + json.dumps(target) +
                                 "\nimport { inject, mount } from './resident.mjs'\nexport { inject }\n"
                                 "export const apply = (ctx, config) => mount(ctx, plugin, config)\n")
                    row = {**row, "id": entry, "name": f"{package}/{entry}"}
                    info["row"] = entry
                inserted.append(row)
                rows.append(info)
            manifest = {"name": package, "version": "0.1.0", "private": True, "type": "module",
                        "exports": exports, "dependencies": dependencies,
                        "dsh": {"bundle": {"patch": "./cordis.patch.yml"}}}
            node.setFile(f"{directory}/package.json", json.dumps(manifest))
            node.setFile(f"{directory}/cordis.patch.yml", yaml.safe_dump([{"insert": inserted}], sort_keys=False))
            node.importFile(str(HERE / "resident.mjs"), f"{directory}/resident.mjs")
            node.addBuildCommandAtEnd(f"cd {shlex.quote(directory)} && pnpm install --ignore-workspace --no-frozen-lockfile")
            add_bundle(alias, package, directory, rows)

        defaults = [
            ({"id": "time-context", "name": "@deepseek-ai/dsh-time-context"}, "host", VERSION, "service defaults"),
            ({"id": "schedule", "name": "@deepseek-ai/dsh-schedule"}, "host", VERSION, "service defaults"),
            ({"id": "dshagent-preset", "name": "@deepseek-ai/dsh-agent-preset", "config": {
                "id": "resident", "name": "Resident", "plugins": [
                    {"id": "persona", "name": "@deepseek-ai/dsh-persona", "config": {
                        "prefix": "You are an individual living in an EmuVista environment.",
                        "complete": True, "includeRuntimeContext": True,
                    }},
                ],
            }}, "host", VERSION, "service defaults"),
        ]
        generated("base", defaults)
        for alias in ("soul", "claw"):
            name, path = packages.stage(ROOT / "agent-plugins" / alias)
            default = (
                {"residentId": self.name, "card": {"identity": "An EmuVista resident"}}
                if alias == "soul" else {"stateFile": f"{self.home}/storages/emuvista-claw/state.json"}
            )
            row = {"id": alias, "name": name, "config": default}
            generated(alias, [(row, "host", "link:" + path, "service defaults")])
            if alias == "soul" and row["config"]["residentId"] != self.name:
                raise ValueError(f"{self.config}: Soul residentId is derived from the instance name")

        native_overrides = []
        for source in self.bundles:
            if source.is_dir():
                package, directory = packages.stage(source, bundle=True)
                patch = source / _manifest(source)["dsh"]["bundle"]["patch"]
                rows = []
                for operation in _yaml(patch) or []:
                    for row in operation.get("insert", []):
                        rows.append(prepare(row, "host", patch))
                        if row["id"] in overrides:
                            native_overrides.append({"id": row["id"], "config": row["config"]})
                add_bundle(package.rsplit("/", 1)[-1], package, directory, rows)
                continue
            bundle = _mapping(_yaml(source), source)
            alias = bundle.get("name")
            if not isinstance(alias, str) or not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,47}", alias):
                raise ValueError(f"{source}: invalid bundle name")
            plugins = bundle.get("plugins")
            if not isinstance(plugins, list) or not plugins:
                raise ValueError(f"{source}: expected a nonempty plugins list")
            declarations = []
            for plugin in plugins:
                plugin = _mapping(plugin, source)
                identifier, scope = plugin.get("id"), plugin.get("preset", "host")
                if not isinstance(identifier, str) or not re.fullmatch(r"[a-zA-Z0-9_-]+", identifier) or scope not in ("host", "resident"):
                    raise ValueError(f"{source}: invalid plugin id or scope")
                path = plugin.get("package")
                if not isinstance(path, str) or not path:
                    raise ValueError(f"{source}: expected a package directory")
                name, destination = packages.stage(source.parent / path)
                row = {"id": identifier, "name": name, "config": _mapping(plugin.get("config", {}), source)}
                declarations.append((row, scope, "link:" + destination, source))
            generated(alias, declarations)
        if unknown := set(overrides) - set(used_overrides):
            raise ValueError(f"{self.config}: unknown plugin overrides: {', '.join(sorted(unknown))}")

        config = [{"id": "agent-preset-registry", "config": {"default": "resident", "selectedDefault": "resident"}},
                  *native_overrides]
        node.setFile(BASE + "/profile.patch.yml", yaml.safe_dump(config, sort_keys=False))
        metadata = {"name": self.name, "profile": profile_name, "home": self.home, "bundles": bundles,
                    "port": 3080, "log": BASE + "/web.log"}
        node.setFile(BASE + "/instance.json", json.dumps(metadata))
        node.setLabel(LABEL_KEY, self.name)
        node.addSoftware("ca-certificates curl")
        node.addDockerCommand(f"COPY --from={self.runtime_image} /usr/local/ /usr/local/")
        node.importFile(str(HERE / "initialize.sh"), BASE + "/initialize.sh")
        node.addBuildCommandAtEnd(f"chmod 755 {BASE}/initialize.sh && ln -s {BASE}/initialize.sh /usr/local/bin/dshagent")
        init_args = shlex.join([self.home, profile_name, *(b["directory"] for b in bundles)])
        node.setFile(BASE + "/launch", f'#!/bin/bash\nexec {BASE}/initialize.sh {init_args} "$@"\n')
        node.addBuildCommandAtEnd(f"chmod 755 {BASE}/launch")
        node.appendStartCommand(f"{BASE}/launch {startup}", isPostConfigCommand=True)
