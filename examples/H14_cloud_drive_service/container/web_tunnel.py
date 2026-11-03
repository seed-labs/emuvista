#!/usr/bin/env python3
"""User-owned loopback tunnels to container loopback via Docker exec/nc."""
import argparse
import os
import signal
import socket
import socketserver
import subprocess
import threading

parser = argparse.ArgumentParser()
parser.add_argument("--alice-port", type=int, default=18081)
parser.add_argument("--bob-port", type=int, default=18082)
args = parser.parse_args()


class Tunnel(socketserver.BaseRequestHandler):
    def handle(self):
        lookup = subprocess.run(
            ["docker", "ps", "-q",
             "--filter", "label=com.docker.compose.project=emuvista-h14",
             "--filter", "label=com.docker.compose.service=hnode_154_" + self.server.role],
            capture_output=True, text=True, timeout=15, check=True,
        )
        cid = lookup.stdout.strip()
        if not cid or "\n" in cid:
            return
        child = subprocess.Popen(
            ["docker", "exec", "-i", cid, "nc", "-N", "127.0.0.1", "3080"],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
        )

        def incoming():
            try:
                while True:
                    data = self.request.recv(65536)
                    if not data:
                        break
                    child.stdin.write(data)
                    child.stdin.flush()
            except (OSError, ValueError):
                pass
            finally:
                try:
                    child.stdin.close()
                except OSError:
                    pass

        threading.Thread(target=incoming, daemon=True).start()
        try:
            while True:
                data = os.read(child.stdout.fileno(), 65536)
                if not data:
                    break
                self.request.sendall(data)
        except OSError:
            pass
        finally:
            try:
                self.request.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            child.terminate()
            try:
                child.wait(timeout=5)
            except subprocess.TimeoutExpired:
                child.kill()
                child.wait()
            child.stdout.close()


class Server(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True


servers = []
try:
    for role, port in (("alice", args.alice_port), ("bob", args.bob_port)):
        server = Server(("127.0.0.1", port), Tunnel)
        server.role = role
        servers.append(server)
    def stop(*_):
        raise SystemExit(0)
    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    for server in servers:
        threading.Thread(target=server.serve_forever, daemon=True).start()
    threading.Event().wait()
finally:
    for server in servers:
        server.server_close()
