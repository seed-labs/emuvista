"""Shared mini Internet topology and DNS infrastructure."""

from .mini_internet import DNS_AUTHORITY, DNS_RESOLVER, build_emulator

__all__ = ['DNS_AUTHORITY', 'DNS_RESOLVER', 'build_emulator']
