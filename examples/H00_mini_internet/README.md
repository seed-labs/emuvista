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

SEED nodes use this resolver by default. Separate authorities serve the private
root, `com`, `net`, `edu` and the standard mini Internet sample domains. TLD
authorities use `10.151.0.53`, `10.152.0.53` and `10.153.0.53`. DNS does not forward to
public Internet DNS. Try `dig @10.150.0.54 dns.seed.example` from an emulated host.

Import the unrendered emulator with the repository root on the Python import path,
as the other example scripts do:

```python
from examples.H00_mini_internet import DNS_RESOLVER, build_emulator

emu = build_emulator()
root = emu.getLayer('DomainNameService').getRootZone()
root.addRecord('app.seed.example. A 10.151.0.10')
# Configure application services before rendering.
emu.render()
```

Use `getZone('com.')` or `getZone('net.')` for records within those zones.
Container bundles can use `DNS_RESOLVER` for their DNS configuration.

`build_emulator(dnssec=True, dnssec_key_store=path)` signs the private root and
enables validation at the resolver. This requires Docker for SEED's BIND key
generation. Keep saved keys outside compiler output. H21, H22 and H99 enable this option.
For standalone use: `python3 mini_internet.py --dnssec`.
