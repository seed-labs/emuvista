#!/usr/bin/env python3
"""Tunnel Alpaca HTTPS from Docker Desktop through a macOS physical interface."""

from __future__ import annotations

import argparse
import ipaddress
import logging
import re
import select
import socket
import subprocess
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Lock
from time import monotonic


ALPACA_HOST = "data.alpaca.markets"
ALPACA_PORT = 443
# Darwin's netinet/in.h uses this option to bind an IPv4 socket to an interface.
IP_BOUND_IF = 25

logger = logging.getLogger(__name__)


def default_gateway(interface: str) -> str:
    route = subprocess.check_output(
        ["/sbin/route", "-n", "get", "-ifscope", interface, "default"], text=True, timeout=3,
    )
    gateway = re.search(r"^\s*gateway:\s*([\d.]+)\s*$", route, re.MULTILINE)
    if not gateway:
        raise ValueError(f"No IPv4 gateway for {interface}. Pass --dns-server explicitly.")
    return str(ipaddress.IPv4Address(gateway[1]))


class AlpacaUpstream:
    def __init__(self, interface: str, dns_server: str):
        self.interface_index = socket.if_nametoindex(interface)
        self.dns_server = str(ipaddress.IPv4Address(dns_server))
        self.addresses: list[str] = []
        self.expires = 0.0
        self.lock = Lock()

    def resolve(self) -> list[str]:
        with self.lock:
            if monotonic() < self.expires:
                return self.addresses
            result = subprocess.check_output([
                "/usr/bin/dig", f"@{self.dns_server}", ALPACA_HOST, "A",
                "+time=2", "+tries=1", "+noall", "+answer",
            ], text=True, timeout=3)
            records = []
            for line in result.splitlines():
                fields = line.split()
                if len(fields) == 5 and fields[3] == "A":
                    address = ipaddress.IPv4Address(fields[4])
                    if address.is_global:
                        records.append((str(address), int(fields[1])))
            if not records:
                raise OSError("The physical network's DNS returned no public IPv4 address for Alpaca")
            self.addresses = [address for address, _ in records]
            self.expires = monotonic() + min(ttl for _, ttl in records)
            return self.addresses

    def connect(self) -> socket.socket:
        last_error = None
        for address in self.resolve():
            upstream = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            try:
                upstream.setsockopt(socket.IPPROTO_IP, IP_BOUND_IF, self.interface_index)
                upstream.settimeout(3)
                upstream.connect((address, ALPACA_PORT))
                return upstream
            except OSError as error:
                upstream.close()
                last_error = error
        raise OSError("Could not reach Alpaca through the selected interface") from last_error


class RelayServer(ThreadingHTTPServer):
    def __init__(self, port: int, upstream: AlpacaUpstream):
        self.upstream = upstream
        super().__init__(("127.0.0.1", port), ConnectHandler)


class ConnectHandler(BaseHTTPRequestHandler):
    timeout = 10
    rbufsize = 0

    def do_CONNECT(self):
        if self.path.lower() != f"{ALPACA_HOST}:{ALPACA_PORT}":
            self.send_error(403, "This relay only connects to Alpaca market data")
            return
        try:
            upstream = self.server.upstream.connect()
        except (OSError, subprocess.SubprocessError, ValueError) as error:
            logger.warning("Alpaca direct connection failed (%s)", type(error).__name__)
            self.send_error(502, "Could not connect to Alpaca through the selected interface")
            return

        with upstream:
            self.send_response_only(200, "Connection established")
            self.end_headers()
            peers = {self.connection: upstream, upstream: self.connection}
            try:
                while peers:
                    readable, _, _ = select.select(list(peers), [], [], 30)
                    if not readable:
                        return
                    for source in readable:
                        target = peers[source]
                        chunk = source.recv(65536)
                        if chunk:
                            target.sendall(chunk)
                        else:
                            del peers[source]
                            target.shutdown(socket.SHUT_WR)
            except OSError:
                # Either endpoint may close the tunnel as it finishes its request.
                return

    def log_message(self, format, *args):
        pass


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--interface", default="en0", help="Mac interface connected to the Internet")
    parser.add_argument("--dns-server", help="IPv4 DNS server for the physical network")
    parser.add_argument("--port", type=int, default=18790, help="Local HTTP CONNECT port")
    args = parser.parse_args()
    if sys.platform != "darwin":
        parser.error("The physical-interface relay requires macOS")
    try:
        upstream = AlpacaUpstream(args.interface, args.dns_server or default_gateway(args.interface))
        upstream.resolve()
    except (OSError, subprocess.SubprocessError, ValueError) as error:
        parser.error(str(error))

    logging.basicConfig(level=logging.INFO)
    with RelayServer(args.port, upstream) as server:
        logger.info("Alpaca relay listening on 127.0.0.1:%d with outbound interface %s", args.port, args.interface)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass


if __name__ == "__main__":
    main()
