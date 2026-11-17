# EmuVista DSH plugins

This directory contains reusable plugins for DeepSeek Harness (DSH). The packages pin their DSH dependencies to `0.2.0-rc.2`. Building them does not require a separate DSH source checkout.

| Package | Capabilities |
| --- | --- |
| `cloud-client` | Authenticate to Cloud Drive, manage and share files, and recover deleted items or previous versions. |
| `chat-client` | Sign in to Tinode, read conversations, and send messages. |
| `claw` | Observe incoming Cloud shares and file ETag changes, track items that need attention, and wake agents to handle events. |
| `soul` | Maintain resident profiles, memories, reflections, and intentions. Schedule rest and wake times. |

Use DshAgentService to select bundles for each agent and enable or disable installed bundles from Python. [DshAgentService guide](../services/DshAgentService/README.md)

During node image builds, the topologies stage plugin sources through the SEED API, install package dependencies, and compile TypeScript inside the images. Local `link:` dependencies resolve to package locations in the container. After changing plugin source, regenerate the topology and rebuild the affected node images.
