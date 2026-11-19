# Services

SEED Emulator service layers install applications on emulator nodes before rendering.

- [AgentService](AgentService/): container-local agents, framework adapters and authorized tool packages.
- [MinecraftAgentService](MinecraftAgentService/): AgentService subclass with a local Minecraft bridge and configurable experiment scripts.
- [CloudDriveService](CloudDriveService/): Nextcloud with PostgreSQL and S3-compatible storage.
- [ChatService](ChatService/): chat servers and clients.
- [DomainService](DomainService/): domain data import, DNS hosting and simulated payments.

ContainerBundle integrations are in [bundles](../bundles/).
