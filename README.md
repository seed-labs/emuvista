# SEEDemu Agent Tools

SEEDemu Agent Tools is a collection of agent-facing tools and services for working with [SEED-Emulator](https://github.com/seed-labs/seed-emulator), a Python framework for creating realistic, container-based Internet emulations.

The project aims to make SEEDemu environments easier for AI agents to understand and operate. Instead of relying only on shell commands and unstructured output, agents will be able to use well-defined interfaces to create emulations, manage their lifecycle, inspect network state, run experiments, and diagnose problems.

> [!NOTE]
> This repository is in its initial development stage. Interfaces, layout, and setup instructions will evolve as the first tools are implemented.

## Goals

- Provide structured, machine-friendly access to common SEEDemu workflows.
- Help agents safely build, start, stop, inspect, and troubleshoot emulations.
- Turn emulator state and command output into useful, predictable responses.
- Keep tool behavior observable, testable, and suitable for repeatable experiments.
- Support cybersecurity education, networking labs, and agent-based research.

## Planned Capabilities

The initial tool services are expected to cover areas such as:

- discovering available emulations, nodes, networks, and services;
- generating and compiling SEEDemu scenarios;
- managing container-based emulation lifecycles;
- executing approved operations on emulated hosts and routers;
- inspecting routing, connectivity, DNS, and service state;
- collecting experiment results, logs, and diagnostics; and
- exposing these operations through interfaces designed for AI agents.

## Repository Layout

```text
seedemu-agent-tools/
|-- agents/         # Agent definitions, prompts, and orchestration resources
|-- docs/           # Architecture and design documentation
|-- tool-service/   # FastAPI tool service and tests
|-- LICENSE
`-- README.md
```

The tool service is organized as an installable Python package. See its [development guide](tool-service/README.md) for local setup, testing, and run instructions.

## Design Principles

- **Safe by default:** potentially disruptive operations should be explicit and constrained.
- **Structured interfaces:** inputs and outputs should be easy for both agents and humans to validate.
- **Clear observability:** tool actions should produce useful logs, errors, and diagnostic context.
- **Reproducibility:** experiments and their results should be repeatable whenever possible.
- **Composable tools:** small, focused operations should work together across different agent workflows.

## Getting Started

Development setup and usage instructions will be added when the first tool service is available. For now, clone the repository to follow or contribute to its development:

```bash
git clone https://github.com/seed-labs/seedemu-agent-tools.git
cd seedemu-agent-tools
```

Using the tools will require a working SEED-Emulator environment. See the [SEED-Emulator repository](https://github.com/seed-labs/seed-emulator) for its installation and usage documentation.

## Contributing

The project is at an early stage, so ideas, use cases, and implementation contributions are welcome. When proposing a tool, please describe:

- the SEEDemu workflow it supports;
- the inputs, outputs, and expected side effects;
- relevant safety boundaries; and
- how the behavior can be tested.

Contribution guidelines and development conventions will be documented as the project takes shape.

## License

This project is licensed under the [GNU General Public License v3.0](LICENSE).
