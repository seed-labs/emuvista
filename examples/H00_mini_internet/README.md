# Mini Internet

Shared network for the examples: six Internet exchanges, five transit ASes,
twelve stub ASes, and a company campus in AS164. Stub ASes have two original
hosts by default; AS164 also includes the company hosts below.

```sh
python3 mini_internet.py
cd output
docker compose build
docker compose up -d
```

Internet Map: http://localhost:8080.

## Company network

AS164 contains the company topology used by H98. Its original `net0` and edge
router remain connected to AS12 through IX104. The edge router connects to a
core router, which connects to headquarters access routers and a branch router.
AS171 remains available for E99's existing nodes.

| LAN | Subnet | Hosts |
| --- | --- | --- |
| DMZ | `10.164.10.0/24` | portal, website, vpn |
| Applications | `10.164.20.0/24` | identity, hr, finance, oa, chat, projects, cloud |
| Data | `10.164.30.0/24` | database1, database2, storage |
| Management | `10.164.40.0/24` | admin, monitoring, backup |
| HR | `10.164.50.0/24` | hr1–hr3 |
| Finance | `10.164.60.0/24` | finance1–finance3 |
| Engineering | `10.164.70.0/24` | engineer1–engineer4 |
| Sales | `10.164.80.0/24` | sales1–sales3 |
| Operations | `10.164.90.0/24` | operations1–operations3 |
| Guest | `10.164.100.0/24` | guest1–guest2 |
| Branch | `10.164.110.0/24` | branch1–branch3 |

LAN gateways use `.254`; hosts start at `.10` in the listed order. The backbone
uses `10.164.1.0/24`, the edge-to-core link uses `10.164.2.0/30`, and the branch
link uses `10.164.3.0/30`. The company has 37 added hosts and 13 routers in total.
Host names reserve roles; H00 does not install company applications.

These are routed LANs without firewall access policies or VLAN tags. The branch
link has no VPN or WAN delay configured. All examples importing H00 include this
topology; H98 only adds applications and their DNS records.

## DNS

| DNS component | Address |
| --- | --- |
| Root authority | `10.150.0.53` |
| Recursive resolver | `10.150.0.54` |
| `.com` authority | `10.151.0.53` |
| `.net` authority | `10.152.0.53` |
| `.org` authority | `10.153.0.53` |
| Shared hosting: `ns1.dns.com` | `10.154.0.53` |

SEED nodes use the recursive resolver by default. The root delegates `.com`,
`.net` and `.org` to separate servers. These delegate application zones to
`ns1.dns.com`, which hosts each zone independently. The provider's `dns.com` zone
contains its nameserver A record; `.com` also holds the glue address needed to
find it. Application A, MX and other records belong in the hosted zones.
DNS does not forward to public Internet DNS.

Import the unrendered emulator with the repository root on the Python import path,
as the other example scripts do:

```python
from examples.H00_mini_internet import DNS_RESOLVER, build_emulator, host_zone

emu = build_emulator()
zone = host_zone(emu, 'app.com')
zone.addRecord('@ A 10.151.0.10')
zone.addRecord('www A 10.151.0.11')
# Configure application services before rendering.
emu.render()
```

`host_zone()` registers the zone and its parent NS delegation, returning SEED's
native `Zone`. Repeated calls return the same zone. Use a domain under one of the
configured TLDs; register its parent zone first when delegating a nested zone.
H20–H22 and H99 use this function for their application domains. Container bundles
continue to use `DNS_RESOLVER`.

From an emulated host in H99:

```sh
dig @10.150.0.54 payment.com A
dig @10.150.0.53 payment.com A +norecurse
dig @10.151.0.53 payment.com A +norecurse
dig @10.154.0.53 payment.com A +norecurse
dig @10.150.0.53 payment.com A +trace
```

The root and `.com` return referrals; the hosting server returns the application
address. Standalone H00 has only the infrastructure and provider zone, so use
`ns1.dns.com` instead of `payment.com` until an application zone is registered.

DNSSEC signing and resolver validation are disabled. No signing keys are generated.

An external IPv4 gateway using SEED's real-world router is always included.
DNS continues to resolve the private simulation namespace.
