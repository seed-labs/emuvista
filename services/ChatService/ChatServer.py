from __future__ import annotations

from typing import Optional

from seedemu.core import Node, Server

CHAT_START_SCRIPT = r'''#!/bin/bash
service mysql start

for i in $(seq 1 30); do
    mysql -e "SELECT 1" >/dev/null 2>&1 && break
    sleep 1
done

mysql -e "CREATE USER IF NOT EXISTS '{db_user}'@'localhost' IDENTIFIED BY '{db_password}';"
mysql -e "GRANT ALL PRIVILEGES ON {db_name}.* TO '{db_user}'@'localhost';"
mysql -e "FLUSH PRIVILEGES;"

# Apply this at container start too, so an old image cannot retain the
# default email-validation requirement.
sed -i -E 's/("required"[[:space:]]*:[[:space:]]*)\["auth"\]/\1[]/' /root/tinode.conf

if ! mysql -e "USE {db_name}" >/dev/null 2>&1; then
    cd /root && ./init-db -config=./tinode.conf -data=./data.json
fi

cd /root && ./tinode -config=./tinode.conf -listen=:{http_port} -grpc_listen=:{grpc_port} 2>&1 | tee /root/tinode.log
'''

CHAT_CONF_SED = (
    "sed -i "
    "-e 's|\"use_adapter\": \"\"|\"use_adapter\": \"mysql\"|' "
    "-e 's|\"User\": \"root\",|\"User\": \"{user}\",\\n\\t\\t\\t\\t\"Passwd\": \"{password}\",|' "
    # This emulator has no SMTP/SMS service, so allow local test accounts to
    # register without external credential validation.
    "-e 's|\"required\": \\[\"auth\"\\]|\"required\": []|' "
    "/root/tinode.conf"
)

CHAT_CLIENT_BUILD = (
    'mkdir -p /root/tn-cli && cd /root/tn-cli && tar xzf /root/tn-cli.tgz && '
    'rm -f /root/tn-cli.tgz && '
    'pip3 install --break-system-packages -r /root/tn-cli/requirements.txt'
)

CHAT_CLIENT_ENV = """\
TINODE_HOST={host}
TINODE_HTTP_PORT={http_port}
TINODE_GRPC_PORT={grpc_port}
TINODE_API_KEY={api_key}
TNCLI_DIR=/root/tn-cli
"""

DEFAULT_API_KEY = 'AQEAAAABAAD_rAp4DJh05a1HAwFT3A6K'
_SAFE_CHARS = set('abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-.@')


def check_safe(value: str, what: str) -> str:
    """Reject values which could break generated shell/sed expressions."""
    bad = sorted(set(value) - _SAFE_CHARS)
    assert not bad, '{} only allows alphanumerics and _ - . @, got {!r}: {!r}'.format(
        what, bad, value)
    return value


class ChatServer(Server):
    """Concrete Tinode server (MySQL plus the Tinode daemon)."""

    def __init__(self, tinode_pkg: str, db_user: str, db_password: str,
                 db_name: str, http_port: int, grpc_port: int):
        super().__init__()
        self.__tinode_pkg = tinode_pkg
        self.__db_user = db_user
        self.__db_password = db_password
        self.__db_name = db_name
        self.__http_port = http_port
        self.__grpc_port = grpc_port

    def install(self, node: Node):
        node.addSoftware('mysql-server')
        node.importFile(self.__tinode_pkg, '/root/tinode.tgz')
        node.addBuildCommandAtEnd(
            'cd /root && tar xzf tinode.tgz && rm -f tinode.tgz'
        )
        node.addBuildCommandAtEnd(CHAT_CONF_SED.format(
            user=check_safe(self.__db_user, 'db_user'),
            password=check_safe(self.__db_password, 'db_password'),
        ))
        node.setFile('/root/chat-start.sh', CHAT_START_SCRIPT.format(
            db_user=self.__db_user,
            db_password=self.__db_password,
            db_name=check_safe(self.__db_name, 'db_name'),
            http_port=self.__http_port,
            grpc_port=self.__grpc_port,
        ))
        node.appendStartCommand('bash /root/chat-start.sh', fork=True)
        node.appendClassName('ChatService')


class ChatClient(Server):
    """Concrete tn-cli client installed on a physical node."""

    def __init__(self, tncli_pkg: str, server_vnode: Optional[str] = None,
                 server_addr: Optional[str] = None,
                 http_port: Optional[int] = None,
                 grpc_port: Optional[int] = None,
                 tinode_grpc_version: Optional[str] = None):
        super().__init__()
        self.__tncli_pkg = tncli_pkg
        self.__server_vnode = server_vnode
        self.__server_addr = server_addr
        self.__http_port = http_port
        self.__grpc_port = grpc_port
        self.__tinode_grpc_version = tinode_grpc_version

    def setServerVnode(self, vnode: str) -> 'ChatClient':
        self.__server_vnode = vnode
        return self

    def getServerVnode(self) -> Optional[str]:
        return self.__server_vnode

    def setServerAddr(self, addr: str) -> 'ChatClient':
        self.__server_addr = addr
        return self

    def getServerAddr(self) -> Optional[str]:
        return self.__server_addr

    def setServerPorts(self, http_port: int, grpc_port: int) -> 'ChatClient':
        self.__http_port = http_port
        self.__grpc_port = grpc_port
        return self

    def install(self, node: Node):
        node.addSoftware('python3 python3-pip')
        node.importFile(self.__tncli_pkg, '/root/tn-cli.tgz')
        node.addBuildCommandAtEnd(CHAT_CLIENT_BUILD)
        if self.__tinode_grpc_version:
            version = check_safe(self.__tinode_grpc_version, 'tinode_grpc_version')
            node.addBuildCommandAtEnd(
                'pip3 install --break-system-packages tinode-grpc=={}'.format(version)
            )

        if self.__server_addr:
            assert self.__http_port is not None and self.__grpc_port is not None, \
                'ChatClient: server ports are not configured.'
            node.setFile('/root/chat.env', CHAT_CLIENT_ENV.format(
                host=self.__server_addr,
                http_port=self.__http_port,
                grpc_port=self.__grpc_port,
                api_key=DEFAULT_API_KEY,
            ))

        node.appendClassName('ChatClientService')


__all__ = ['ChatServer', 'ChatClient', 'check_safe']
