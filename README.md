# EmuVista

Digital-world services and agents built on [SEED Emulator](https://github.com/seed-labs/seed-emulator).
Agents run inside the simulated network and interact with world services through local tools.

- [services](services/): native SEED service layers, including [AgentService](services/AgentService/).
- [bundles](bundles/): external application containers on SEED networks.
- [examples](examples/): single-system examples and the shared H99 world.
- [experiments](experiments/): agents and tasks built on those worlds.
- [docker_images](docker_images/): customized application image build inputs.
- [docs](docs/): design and development notes.

[H99](examples/H99_virtual_world/) combines email, payment and banks.
[E99](experiments/E99_virtual_world/) adds five agents using a replaceable LangChain
adapter and per-agent tool permissions. Fill the experiment .env with your LLM API.

Requires a working SEED Emulator installation, Python dependencies from
`requirements.txt`, and Docker. Individual examples document additional images.

Licensed under [GPL-3.0](LICENSE).
