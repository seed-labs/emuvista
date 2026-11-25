# Project Vision and Scope

## Vision

SEEDemu Agent Tools is being built toward a virtual world populated by individuals that combine an AI agent with a virtual machine (VM). Each agent acts through its VM, uses the available tools to observe and change the emulated environment, and can live and pursue goals within that world over time.

The long-term goal is not simply to provide a collection of command wrappers. It is to provide the interaction layer that lets agents participate in a persistent, networked, service-rich virtual world built with SEED-Emulator.

## The Three Parts

### Agents

An agent is the decision-making part of an individual. It observes information made available through tools, decides what to do, and selects actions that may help it pursue its goals. The agent's reasoning, personality, memory, and goal system belong to the agent implementation; the toolset should not assume one particular agent architecture.

### Virtual machines

A VM is the individual's computing environment in the emulated world. The agent uses tools to inspect and operate its VM and, through it, interact with other systems. The precise relationship between an agent process and its VM can evolve; the key idea is that the VM gives the individual a place and capabilities with which to act in the world.

### The emulated world

The virtual world is the networked environment constructed with SEED-Emulator. It can contain hosts, routers, networks, and application services. These systems provide the setting and other entities with which agents interact. SEED-Emulator provides the emulation; this project builds agent-facing ways to work with it.

## The Role of the Toolset

The toolset is the interaction layer between agents and the emulated world. It gives agents discoverable, structured operations for:

- observing nodes, services, network state, and task results;
- taking actions on a VM or interacting with services in the world; and
- receiving results that can guide the agent's next decision.

An agent can combine observations and actions into a continuing loop:

```text
observe the world → decide what to do → use tools to act → inspect the result → continue
```

Tools should expose capabilities and return useful results. They should not make the agent's decisions or encode an entire scenario-specific plan when a reusable operation would serve the agent better. Actions should be scoped to the emulated environment and make their effects understandable to the caller.

## This Repository's Responsibility

This repository develops the agent-facing tool service and its tool collections. The service discovers available tools, validates their inputs, invokes them against the relevant emulated nodes or services, and returns structured results. The current service exposes tool discovery and invocation through REST.

The repository does not own the SEED-Emulator itself, nor does the tool service define an agent's reasoning or goals. Those systems work together: SEED-Emulator supplies the world, agents supply decision-making individuals, and this project's tools let those individuals interact with the world.

## Development Principles

- **Agent-directed:** tools provide observations and actions that agents can select and combine; agents remain responsible for deciding what to do.
- **World-aware:** tool behavior should match the services and semantics actually present in the emulation.
- **Composable:** prefer focused operations that can be combined into different agent workflows.
- **Structured:** make tool inputs, results, and errors predictable for both agents and people.
- **Observable:** make relevant effects and outcomes clear so an agent can choose its next step.
- **Scoped:** constrain operations to their intended nodes, services, and emulated resources.
- **Reusable:** avoid tying a general-purpose tool to one example when the capability applies more broadly.

## Current Implementation and Long-Term Goal

The long-term vision is a world of agent-and-VM individuals that can act and live through tools. The repository is building toward that vision incrementally. Its current work includes a REST-based tool service, domain-specific tool collections, and emulation examples that demonstrate tool workflows.

The existence of a tool service or an example does not mean the complete virtual world or agent population is already implemented. Future work can add capabilities needed by agents as the world and individual model become clearer. New work should connect back to the central purpose: enabling agents to observe and act in the SEEDemu world through useful, reliable tools.
