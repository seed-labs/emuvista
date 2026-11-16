"""Convert a domain data file and dispatch it to the owning services."""
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
import re

import yaml
from seedemu.core import Service


class DomainDataService(Service):
    """Import initial domain data during configuration, without a dedicated node."""

    def __init__(self):
        super().__init__()
        self._documents = []
        self._names = set()
        self._targets = {}
        self.addDependency('Base', False, False)
        self.addDependency('DomainNameService', True, False)

    def addTarget(self, name, server):
        """Register an external application's import configuration by scenario name."""
        if name in self._targets:
            raise ValueError(f'Duplicate domain import target: {name}')
        self._targets[name] = server
        return self

    def importFile(self, path):
        """Read YAML now; resolve scenario references and dispatch during configure."""
        document = yaml.safe_load(Path(path).read_text(encoding='utf-8'))
        names = [self._domain(item['name']) for item in document['domains']]
        if len(set(names)) != len(names) or self._names.intersection(names):
            raise ValueError('Duplicate domain in import files')
        self._documents.append(document)
        self._names.update(names)
        return self

    @staticmethod
    def _domain(value):
        value = value.lower().rstrip('.')
        if len(value) > 253 or not all(re.fullmatch(r'[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?', p)
                                     for p in value.split('.')):
            raise ValueError(f'Invalid DNS name: {value}')
        return value

    @staticmethod
    def _date(value):
        parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
        if parsed.tzinfo is None:
            raise ValueError('Registration timestamps must include a timezone')
        return parsed.astimezone(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')

    def _zone(self, item, primary, addresses):
        name = self._domain(item['name'])
        config = item['dns']
        ttl = config.get('ttl', 300)
        soa = dict(rname=f'hostmaster.{name}.', serial=1, refresh=900, retry=900, expire=1800, minimum=60)
        soa.update(config.get('soa', {}))
        rname = self._domain(soa['rname']) + '.'
        lines = [f'$ORIGIN {name}.', f'$TTL {ttl}',
                 f'@ IN SOA {primary}. {rname} ({soa["serial"]} {soa["refresh"]} '
                 f'{soa["retry"]} {soa["expire"]} {soa["minimum"]})']
        lines.extend(f'@ IN NS {ns}.' for ns in addresses)
        # In-zone nameserver addresses are authoritative topology data.
        for ns, ip in addresses.items():
            if ns == name or ns.endswith('.' + name):
                lines.append(f'{ns}. IN A {ip}')
        for record in config.get('records', []):
            owner, kind, value = record['name'], record['type'].upper(), record['value']
            absolute = name if owner == '@' else (owner.rstrip('.') if owner.endswith('.') else owner + '.' + name)
            if absolute != name and not absolute.endswith('.' + name):
                raise ValueError(f'{name}: record outside zone')
            if kind == 'SOA' or (absolute == name and kind == 'NS'):
                raise ValueError(f'{name}: apex NS and SOA are generated from shared fields')
            if absolute in addresses and kind in ('A', 'AAAA'):
                continue
            record_ttl = record.get('ttl', ttl)
            lines.append(f'{owner} {record_ttl} IN {kind} {value}')
        return '\n'.join(lines) + '\n'

    def configure(self, emulator):
        """Prepare all payloads before invoking the three services' import APIs."""
        dns = emulator.getLayer('DomainNameService')
        registries, registrars, zones = {}, {}, []
        contacts, clients = {}, {}
        for document in self._documents:
            ns_nodes = {self._domain(ns): vnode for ns, vnode in document['hosting-nameservers'].items()}
            for item in document['domains']:
                name = self._domain(item['name'])
                if name.count('.') != 1:
                    raise ValueError(f'{name}: expected a registrable name under a single-label TLD')
                registration, account = item['registration'], item['registrar']
                registry_name, registrar_name = registration['registry'], account['server']
                registry = (self._targets[registry_name] if registry_name in self._targets
                            else emulator.getServerByVirtualNodeName(registry_name))
                registrar = (self._targets[registrar_name] if registrar_name in self._targets
                             else emulator.getServerByVirtualNodeName(registrar_name))
                if registrar.getRegistry() != registration['registry']:
                    raise ValueError(f'{name}: Registrar is connected to a different Registry')
                contact = deepcopy(document['contacts'][item['registrant']])
                client = deepcopy(document['clients'][account['client']])
                client['contact'] = deepcopy(document['contacts'][client['contact']])
                for values, key, value in (
                    (contacts, (registry, registrar.getEppUsername(), item['registrant']), contact),
                    (clients, (registrar, client['email']), client),
                ):
                    if key in values and values[key] != value:
                        raise ValueError(f'{name}: conflicting contact or customer definitions')
                    values[key] = value
                nameservers = {self._domain(ns): ns_nodes[self._domain(ns)] for ns in item['nameservers']}
                if not 1 <= len(nameservers) <= 4:
                    raise ValueError(f'{name}: FOSSBilling supports one to four nameservers')
                primary = dns.getPrimaryNameServer(nameservers)
                addresses = {ns: str(emulator.getBindingFor(vnode).getInterfaces()[0].getAddress())
                             for ns, vnode in nameservers.items()}
                zone = self._zone(item, primary, addresses)
                created, expires = self._date(registration['created_at']), self._date(registration['expires_at'])
                if expires <= created:
                    raise ValueError(f'{name}: expiry must follow creation')
                if registration.get('statuses', ['ok']) != ['ok'] or account.get('status', 'active') != 'active':
                    raise ValueError(f'{name}: initial import currently supports ok/active domains only')
                common = dict(name=name, contact=contact, created_at=created, expires_at=expires,
                              nameservers=addresses)
                registries.setdefault(registry, []).append(dict(common, registrant=item['registrant'],
                    registrar=registrar.getEppUsername(), statuses=registration.get('statuses', ['ok'])))
                registrars.setdefault(registrar, []).append(dict(common, client=client,
                    status=account.get('status', 'active'), auto_renew=account.get('auto_renew', False)))
                zones.append((name, zone, nameservers))
        for server, records in registries.items():
            server.importDomains(records)
        for server, records in registrars.items():
            server.importDomains(records)
        for name, zone, nameservers in zones:
            dns.importZone(name, zone, nameservers)
        super().configure(emulator)

    def getName(self):
        return 'DomainDataService'

    def install(self, vnode: str):
        raise NotImplementedError('DomainDataService does not install on nodes.')

    def print(self, indent: int):
        return ' ' * indent + 'DomainDataServiceLayer\n'
