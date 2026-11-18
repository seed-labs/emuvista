"""Shared mini Internet topology and DNS infrastructure."""

from .mini_internet import COMPANY_ASN, DNS_AUTHORITY, DNS_HOSTING, DNS_RESOLVER, build_emulator, host_zone

__all__ = ['COMPANY_ASN', 'DNS_AUTHORITY', 'DNS_HOSTING', 'DNS_RESOLVER', 'build_emulator', 'host_zone']
