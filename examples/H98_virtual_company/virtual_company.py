#!/usr/bin/env python3
"""Deploy company applications on the shared company network."""

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from seedemu.compiler import Docker, Platform
from seedemu.containerBundle import InternetMap
from seedemu.core import Binding, Filter
from examples.H00_mini_internet import COMPANY_ASN, DNS_RESOLVER, build_emulator as build_mini_internet, host_zone
from bundles.ERPBundle import ERPBundle
from bundles.HelpdeskBundle import HelpdeskBundle
from bundles.IdentityBundle import IdentityBundle
from bundles.KnowledgeBundle import KnowledgeBundle
from bundles.ProjectBundle import ProjectBundle
from bundles.WorkChatBundle import WorkChatBundle
from services.CloudDriveService import CloudDriveService

COMPANY_DOMAIN = 'company.com'


def createworld(state=None):
    emu = build_mini_internet()
    company = emu.getLayer('Base').getAutonomousSystem(COMPANY_ASN)
    configuration = json.loads(Path(__file__).with_name('company.json').read_text())
    identity = IdentityBundle(emu, name='company-identity', resolver=DNS_RESOLVER)
    identity.setHostname('login.' + COMPANY_DOMAIN).enableHostAccess(8085)
    identity.setInitialConfiguration(configuration)
    if state:
        identity.setSavePath(Path(state) / 'identity')
    cloud = CloudDriveService(saveState=bool(state), savePath=str(Path(state or '.') / 'cloud'))
    cloud.createDatabase('company_cloud_db')
    cloud.createObjectStorage('company_cloud_storage')
    drive = cloud.createDrive('company_cloud')
    drive.setDatabase('company_cloud_db')
    drive.setObjectStorage('company_cloud_storage')
    drive.setServerNames(['cloud.' + COMPANY_DOMAIN])
    drive.setAdminCredentials('admin', 'CompanyDrive123!')
    drive.connectIdentity(identity)
    emu.addLayer(cloud)
    for vnode, host in [
        ('company_cloud', 'cloud'),
        ('company_cloud_db', 'database1'),
        ('company_cloud_storage', 'storage'),
    ]:
        emu.addBinding(Binding(f'^{vnode}$', filter=Filter(asn=COMPANY_ASN, nodeName=f'^{host}$')))
    company.getHost('cloud').addPort(8081, 80)
    host_zone(emu, COMPANY_DOMAIN).addRecord(f'cloud A 10.{COMPANY_ASN}.20.16')

    applications = {
        'chat': (WorkChatBundle, 8086, 110, 2, 4),
        'erp': (ERPBundle, 8082, 60, 6, 2),
        'projects': (ProjectBundle, 8087, 80, 4, 1),
        'knowledge': (KnowledgeBundle, 8088, 90, 2, 1),
        'helpdesk': (HelpdeskBundle, 8089, 100, 3, 1),
    }
    bundles = {}
    for name, (bundle_class, port, address, app_count, data_count) in applications.items():
        bundle = bundle_class(emu, name='company-' + name, resolver=DNS_RESOLVER)
        bundle.setHostname(name + '.' + COMPANY_DOMAIN).enableHostAccess(port)
        bundle.setInitialConfiguration(configuration).connectIdentity(identity)
        if state:
            bundle.setSavePath(Path(state) / name)
        host_zone(emu, COMPANY_DOMAIN).addRecord(f'{name} A 10.{COMPANY_ASN}.20.{address}')
        bundles[name] = bundle
    bundles['erp'].connectChat(bundles['chat'])
    host_zone(emu, COMPANY_DOMAIN).addRecord(f'login A 10.{COMPANY_ASN}.20.70')
    emu.render()
    for bundle, (_, _, address, app_count, data_count) in zip(bundles.values(), applications.values()):
        bundle.addInternalNetwork(str(COMPANY_ASN), 'applications',
                                  [f'10.{COMPANY_ASN}.20.{index}' for index in range(address, address + app_count)])
        bundle.addInternalNetwork(str(COMPANY_ASN), 'data',
                                  [f'10.{COMPANY_ASN}.30.{index}' for index in range(address, address + data_count)])
    identity.addInternalNetwork(str(COMPANY_ASN), 'applications',
                                [f'10.{COMPANY_ASN}.20.{index}' for index in range(70, 73)])
    identity.addInternalNetwork(str(COMPANY_ASN), 'data', [f'10.{COMPANY_ASN}.30.70', f'10.{COMPANY_ASN}.30.71'])
    # Install the directory last, after applications have registered their clients.
    return emu, [*bundles.values(), identity]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=Path('output'))
    parser.add_argument('--platform', choices=['amd', 'arm'], default='amd')
    parser.add_argument('--state', type=Path)
    args = parser.parse_args()
    if args.state and (args.state.resolve() == args.output.resolve()
                       or args.output.resolve() in args.state.resolve().parents):
        parser.error('state must be outside output')
    emu, bundles = createworld(args.state)
    platform = Platform.AMD64 if args.platform == 'amd' else Platform.ARM64
    compiler = Docker(platform=platform)
    internet_map = InternetMap(emu)
    internet_map.setPorts([8083, 8080, 8084])
    compiler.addContainerBundle(internet_map)
    for bundle in bundles:
        compiler.addContainerBundle(bundle)
    emu.compile(compiler, str(args.output.resolve()), override=True)


if __name__ == '__main__':
    main()
