# Examples

Use `H**` prefixes for example directories.

[H00_mini_internet](H00_mini_internet/) provides the shared network and DNS.
Import its unrendered emulator instead of copying the topology:

```python
from examples.H00_mini_internet import build_emulator

emu = build_emulator()
# Add services and DNS records, then render and compile.
```

[H99_virtual_world](H99_virtual_world/) combines email, payment, banks and a marketplace.
[E99](../experiments/E99_virtual_world_with_agents/) adds five agents to H99.

[H98_virtual_company](H98_virtual_company/) deploys company applications on H00's
AS164 campus. It currently reuses CloudDriveService, with separate application,
database, and object-storage nodes.

[H23_shop_service](H23_shop_service/) demonstrates multi-vendor shopping with Payment balance and bank-card checkout.
[H30_cloud_drive_service](H30_cloud_drive_service/) uses DshAgentService to deploy Cloud Drive agents.
