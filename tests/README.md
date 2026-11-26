# Example smoke tests

The runner reuses `seedemu.testing`, following SeedEmu and ChainSEED's
`example.yaml` lifecycle. It checks compilation, image builds, and container
startup. Business workflows and LLM decisions are outside this smoke suite.

Run from the repository root with Python 3.10+, an editable SeedEmu checkout,
and the root `requirements.txt` installed. Docker Engine and Compose v2 are
required for builds and startup; PKI examples also use Docker during compilation.

```sh
python tests/run_examples.py list
python tests/run_examples.py all all
python tests/run_examples.py compile all
python tests/run_examples.py compile H12
python tests/run_examples.py build H20
python tests/run_examples.py all H20
```

| Command | Steps |
| --- | --- |
| `compile` | Generate the deployment and check expected files |
| `build` | Compile, validate Compose, build custom images, then generated images |
| `all` | Compile, build, start, wait for readiness, collect logs, and stop |

Replace `H20` with any listed code, or `all`. Examples run sequentially locally.
Compilation, image builds, and startup checks cover every current example,
including those before H20:

| Code | Example |
| --- | --- |
| H00 | Mini Internet and DNS |
| H12 | Domain purchase and DNS hosting |
| H13 | Browser agent |
| H14 | PKI HTTP-01 |
| H15 | PKI DNS-01 wildcard |
| H20 | Payment |
| H21 | Email |
| H22 | Bank |
| H23 | Shop |
| H30 | Cloud Drive agents |
| H98 | Virtual company |
| H99 | Virtual world |
| E99 | Virtual world with agents |

Each run uses a new source copy under `.runtime/ci/` and a unique Compose project.
Existing example outputs, application state, and `.env` files remain untouched.
Run Docker tests on an otherwise unused Docker host: the examples retain their
fixed container names, subnets, and host ports. Separate project names do not
remove those conflicts.

Results are written to `ci-artifacts/summary.json` and, for each example,
`result.json`, `runtime-status.json`, and `logs/`. Use `--artifact-dir PATH` to
choose another directory. The command exits nonzero if any example fails and
continues testing the remaining examples. `result.json` records the workspace
and Compose project; generated files remain there for inspection. Remove those
workspaces when finished.

Builds run one service at a time, with SEED's generated base images first.
`build.images` prepares the example's custom image groups from `docker_images/`.
BuildKit defaults to enabled because some source images use cache mounts;
an explicit `DOCKER_BUILDKIT` environment setting is respected.

Startup passes when every application and network container stays running for
10 seconds, any declared health checks pass, and initialization jobs exit with
code 0. SEED's build-only dummy services are excluded. Unexpected exits and
startup timeouts fail the test. After startup is attempted, success and failure
both collect diagnostics and run project-scoped `down --volumes --remove-orphans`.
Cleanup stops containers in parallel so large topologies do not exceed the
cleanup timeout; image builds remain sequential.
Images and build caches are retained. This checks container readiness; services
without health checks need separate business tests to establish functionality.

E99 uses its existing `start.py` to start infrastructure before agents. The copy
receives placeholder LLM settings pointing at a reserved test address. No real
API credentials are copied. Agent decisions and tool execution are not verified.

## GitHub Actions

[Example smoke tests](../.github/workflows/examples.yml) runs compile → build →
up → container readiness → down for all examples on pushes and PRs to `main`
and `development`. Each example runs in a separate Ubuntu job, and logs are
uploaded even after failures. This checks startup only; no business probes or
functional test programs are run.

Use **Actions → Example smoke tests → Run workflow** to choose:

- `example`: one code or `all`.
- `seedemu-ref`: a SeedEmu branch, tag, or commit; defaults to `master`.

Large worlds, especially H98, need substantial memory, disk space, and build
time. Full lifecycle runs have a 180-minute job limit. Use a SeedEmu ref containing
any core changes required by your examples; local uncommitted core changes are
not included in GitHub Actions. This workflow tests deployments and does not
publish images or deploy to an external host.

## Add an example

Put `example.yaml` beside the entry script. The runner scans every `Hxx*` directory
under `examples/` and every `Exx*` directory under `experiments/`; the directory
prefix becomes its code. Missing manifests and duplicate codes fail discovery,
so new examples cannot silently disappear from the CI matrix.
Existing H12/H14/H15 manifests remain usable by SeedEmu's own runner. This smoke
runner does not execute their additional `probes` or `test_programs`.

```yaml
id: h40
runner: internet
script: application.py
compile:
  standard_args: false
  args: [--output, output]
  output: output
  expected: [output/docker-compose.yml]
  timeout: 600
build:
  images: []
  timeout: 3600
runtime:
  compose: output/docker-compose.yml
  timeout: 1200
```

`build.images` lists custom image group directories. Optional `build.commands`
contains argument lists run from the copied repository root before generated
images are built. Optional `runtime.startup` selects an example's Python startup
script accepting `--output` and `--timeout`, as E99 does.

Runner checks need no Docker:

```sh
python -m unittest discover -s tests/ci -p 'test_*.py'
```
