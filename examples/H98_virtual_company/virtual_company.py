#!/usr/bin/env python3
"""Deploy company applications on the shared company network."""

import argparse
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from seedemu.compiler import Docker, Platform
from seedemu.core import Binding, Filter
from examples.H00_mini_internet import COMPANY_ASN, build_emulator as build_mini_internet, host_zone
from services.CloudDriveService import CloudDriveService

COMPANY_DOMAIN = 'company.com'


def build_emulator():
    emu = build_mini_internet()
    company = emu.getLayer('Base').getAutonomousSystem(COMPANY_ASN)
    cloud = CloudDriveService()
    cloud.createDatabase('company_cloud_db')
    cloud.createObjectStorage('company_cloud_storage')
    drive = cloud.createDrive('company_cloud')
    drive.setDatabase('company_cloud_db')
    drive.setObjectStorage('company_cloud_storage')
    drive.setServerNames(['cloud.' + COMPANY_DOMAIN])
    drive.setAdminCredentials('admin', 'CompanyDrive123!')
    emu.addLayer(cloud)
    for vnode, host in [
        ('company_cloud', 'cloud'),
        ('company_cloud_db', 'database1'),
        ('company_cloud_storage', 'storage'),
    ]:
        emu.addBinding(Binding(f'^{vnode}$', filter=Filter(asn=COMPANY_ASN, nodeName=f'^{host}$')))
    company.getHost('cloud').addPort(8081, 80)
    host_zone(emu, COMPANY_DOMAIN).addRecord(f'cloud A 10.{COMPANY_ASN}.20.16')
    return emu


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=Path('output'))
    parser.add_argument('--platform', choices=['amd', 'arm'], default='amd')
    args = parser.parse_args()
    emu = build_emulator()
    emu.render()
    platform = Platform.AMD64 if args.platform == 'amd' else Platform.ARM64
    emu.compile(Docker(platform=platform, internetMapEnabled=True),
                str(args.output.resolve()), override=True)


if __name__ == '__main__':
    main()
