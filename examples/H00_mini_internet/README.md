# Mini Internet

Shared network for the examples: six Internet exchanges, five transit ASes,
twelve stub ASes and two hosts per stub AS by default.

```sh
python3 mini_internet.py
cd output
docker compose build
docker compose up -d
```

Internet Map: http://localhost:8080.

| DNS component | Address |
| --- | --- |
| Root authority | `10.150.0.53` |
| Recursive resolver | `10.150.0.54` |

SEED nodes use this resolver by default. The authority starts with an empty
private root: no TLD servers, sample domains or application records. DNS does not
forward to public Internet DNS. Application examples register their own records
before rendering. From an emulated host, `dig @10.150.0.54 . SOA` checks the root.

Import the unrendered emulator with the repository root on the Python import path,
as the other example scripts do:

```python
from examples.H00_mini_internet import DNS_RESOLVER, build_emulator

emu = build_emulator()
root = emu.getLayer('DomainNameService').getRootZone()
root.addRecord('app.com. A 10.151.0.10')
# Configure application services before rendering.
emu.render()
```

H99 registers mail, payment and bank records directly in this root. Container
bundles use `DNS_RESOLVER` for their DNS configuration.

DNSSEC signing and resolver validation are always enabled. Native BIND key
generation requires Docker. `dnssec_key_store=path` reuses saved keys; keep them
outside compiler output. Standalone: `python3 mini_internet.py --dnssec-key-store keys`.

An external IPv4 gateway using SEED's real-world router is always included.
DNS continues to resolve the private simulation namespace.
