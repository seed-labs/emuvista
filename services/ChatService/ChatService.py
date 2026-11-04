from __future__ import annotations

from typing import Optional

from seedemu.core import Emulator, Node, Service
from seedemu.core.enums import NetworkType

from .ChatServer import ChatClient, ChatServer, check_safe


class ChatService(Service):
    """Tinode chat service managing both server and client nodes.

    ChatServer and ChatClient remain separate concrete node handlers, while
    this class owns their shared configuration and lifecycle.
    """

    def __init__(self, tinode_pkg: Optional[str] = None,
                 tncli_pkg: Optional[str] = None,
                 tinode_grpc_version: Optional[str] = None):
        super().__init__()
        self.addDependency('Base', False, False)
        self.addDependency('Routing', False, False)

        self.__tinode_pkg = tinode_pkg
        self.__tncli_pkg = tncli_pkg
        self.__tinode_grpc_version = tinode_grpc_version
        self.__db_user = 'tinode'
        self.__db_password = 'tinode123'
        self.__db_name = 'tinode'
        self.__http_port = 6060
        self.__grpc_port = 16060

    def setTinodePackage(self, path: str) -> 'ChatService':
        self.__tinode_pkg = path
        return self

    def setTnCliPackage(self, path: str) -> 'ChatService':
        self.__tncli_pkg = path
        return self

    def setTinodeGrpcVersion(self, version: Optional[str]) -> 'ChatService':
        self.__tinode_grpc_version = version
        return self

    def setDbUser(self, user: str) -> 'ChatService':
        self.__db_user = check_safe(user, 'db_user')
        return self

    def setDbPassword(self, password: str) -> 'ChatService':
        self.__db_password = check_safe(password, 'db_password')
        return self

    def setDbName(self, name: str) -> 'ChatService':
        self.__db_name = check_safe(name, 'db_name')
        return self

    def setHttpPort(self, port: int) -> 'ChatService':
        self.__http_port = port
        return self

    def setGrpcPort(self, port: int) -> 'ChatService':
        self.__grpc_port = port
        return self

    def getDbUser(self) -> str:
        return self.__db_user

    def getDbPassword(self) -> str:
        return self.__db_password

    def getDbName(self) -> str:
        return self.__db_name

    def getHttpPort(self) -> int:
        return self.__http_port

    def getGrpcPort(self) -> int:
        return self.__grpc_port

    def getTinodePackage(self) -> str:
        assert self.__tinode_pkg, 'ChatService: tinode package path not set.'
        return self.__tinode_pkg

    def getTnCliPackage(self) -> str:
        assert self.__tncli_pkg, 'ChatService: tn-cli package path not set.'
        return self.__tncli_pkg

    def installServer(self, vnode: str) -> ChatServer:
        """Register a Tinode server target."""
        existing = self._pending_targets.get(vnode)
        if existing is not None:
            assert isinstance(existing, ChatServer), \
                'ChatService: vnode {} is already registered as a client.'.format(vnode)
            return existing

        server = ChatServer(
            tinode_pkg=self.getTinodePackage(),
            db_user=self.__db_user,
            db_password=self.__db_password,
            db_name=self.__db_name,
            http_port=self.__http_port,
            grpc_port=self.__grpc_port,
        )
        self._pending_targets[vnode] = server
        return server

    def installClient(self, vnode: str, server_vnode: Optional[str] = None,
                      server_addr: Optional[str] = None) -> ChatClient:
        """Register a tn-cli target connected to a Tinode server.

        Use server_vnode for a server inside this emulation, or server_addr for
        a server outside it. Exactly one is required.
        """
        existing = self._pending_targets.get(vnode)
        if existing is not None:
            assert isinstance(existing, ChatClient), \
                'ChatService: vnode {} is already registered as a server.'.format(vnode)
            return existing

        assert (server_vnode is None) != (server_addr is None), \
            'ChatService: specify exactly one of server_vnode or server_addr.'

        client = ChatClient(
            tncli_pkg=self.getTnCliPackage(),
            server_vnode=server_vnode,
            server_addr=server_addr,
            http_port=self.__http_port,
            grpc_port=self.__grpc_port,
            tinode_grpc_version=self.__tinode_grpc_version,
        )
        self._pending_targets[vnode] = client
        return client

    def _getPrimaryIp(self, node: Node) -> str:
        for iface in node.getInterfaces():
            if iface.getNet().getType() == NetworkType.Local:
                return str(iface.getAddress())
        raise AssertionError(
            'ChatService: node as{}/{} has no local network interface.'.format(
                node.getAsn(), node.getName()))

    def configure(self, emulator: Emulator):
        """Resolve client server addresses before base Service configuration."""
        for vnode, target in self._pending_targets.items():
            if not isinstance(target, ChatClient):
                continue

            server_vnode = target.getServerVnode()
            if server_vnode is not None:
                server_target = self._pending_targets.get(server_vnode)
                assert isinstance(server_target, ChatServer), \
                    'ChatService: client {} references unknown server vnode {}.'.format(
                        vnode, server_vnode)
                server_node = emulator.getBindingFor(server_vnode)
                target.setServerAddr(self._getPrimaryIp(server_node))

            target.setServerPorts(self.__http_port, self.__grpc_port)
            self._log('configured chat client {} -> {}'.format(
                vnode, target.getServerAddr()))

        super().configure(emulator)

    def getName(self) -> str:
        return 'ChatService'

    def print(self, indent: int) -> str:
        return ' ' * indent + 'ChatService layer (http={}, grpc={}).\n'.format(
            self.__http_port, self.__grpc_port)


__all__ = ['ChatService', 'ChatServer', 'ChatClient']
