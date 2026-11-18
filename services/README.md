# Services

SEED Emulator service layers install applications on emulator nodes before rendering.

- [AgentService](AgentService/): container-local agents, framework adapters and authorized tool packages.
- [CloudDriveService](CloudDriveService/): Nextcloud with PostgreSQL and S3-compatible storage.
- [ChatService](ChatService/): chat servers and clients.
- [DomainService](DomainService/): domain registration, billing, DNS hosting and simulated payments.
- [ShopService](ShopService/): marketplace, MySQL and initialization on one host.

ContainerBundle integrations are in [bundles](../bundles/).
