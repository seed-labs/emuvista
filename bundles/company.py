"""Small deployment helpers shared by company bundles."""

import json
from pathlib import Path
import tempfile


def configuration(value):
    return json.loads(Path(value).read_text()) if isinstance(value, (str, Path)) else value


def assign_networks(bundle, application_roles, data_roles):
    addresses = {}
    for network, roles in zip(bundle.getInternalNetworks(), (application_roles, data_roles)):
        for role, address in zip(roles, network['ip_addresses']):
            container = bundle.getContainer(role)
            container.joinInternalNetwork(network['asn'], network['network_name'],
                                          address, container.getHostname(), network['default_route'])
            addresses[role] = str(address)
    return addresses


def state_directory(name, path, directories):
    root = Path(path) if path else Path(tempfile.mkdtemp(prefix='emuvista-' + name + '-'))
    root.mkdir(parents=True, exist_ok=True)
    for directory in directories:
        (root / directory).mkdir(exist_ok=True)
    return root


def prepare_container(container, settings, script='#!/bin/sh\nexec "$@"\n'):
    container.setFile('/application-start.sh', script)
    container.setEntrypointWrapper('/application-start.sh', [])
    container.updateServiceConfig(settings)
