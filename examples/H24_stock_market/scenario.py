#!/usr/bin/env python3
"""Compile a live Stock Service and QuantReplay trade for H24."""

from __future__ import annotations

import argparse
import base64
import json
import re
import secrets
import shutil
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from seedemu.compiler import Docker, Platform
from seedemu.core import Emulator
from seedemu.layers import Base
from bundles.BankBundle import BankBundle
from bundles.EmailBundle import EmailBundle


HERE = Path(__file__).resolve().parent
WEB_DIR = ROOT / "services/StockService/stock_service/web"
STOCK_DB_IP = "10.250.0.30"
STOCK_API_IP = "10.250.0.31"
QUANTREPLAY_IP = "10.250.0.32"
QUANTREPLAY_DB_IP = "10.250.0.33"
LIQUIBASE_IP = "10.250.0.34"
CONFIG_IP = "10.250.0.35"
DASHBOARD_IP = "10.250.0.80"
RUNNER_IP = "10.250.0.81"
INTERNET_MAP_IP = "10.250.0.82"
AGENT_VM_IPS = {"Alice": "10.250.0.90", "Bob": "10.250.0.91", "Carol": "10.250.0.92"}
BANK_GATEWAY_IP = "10.250.0.40"
EMAIL_IMAP_IP = "10.250.0.53"
EMAIL_FRONT_IP = "10.250.0.50"
PORT = 8765
INTERNET_MAP_PORT = 8080


def service_entry(name: str, body: str) -> str:
    return f"""\
    {name}:
{body}
"""


def prepare_context(output: Path) -> None:
    tls = output / "h24-state" / "tls"
    tls.mkdir(parents=True, exist_ok=True)
    certificate = tls / "server.crt"
    private_key = tls / "server.key"
    subprocess.run(
        ["openssl", "req", "-x509", "-nodes", "-newkey", "rsa:2048", "-days", "365",
         "-keyout", str(private_key), "-out", str(certificate),
         "-subj", "/CN=H24 Stock Service",
         "-addext", f"subjectAltName=IP:{STOCK_API_IP},DNS:localhost"],
        check=True, capture_output=True,
    )
    private_key.chmod(0o600)

    dashboard = output / "h24-stock-dashboard"
    static = dashboard / "static"
    static.mkdir(parents=True, exist_ok=True)
    for filename in ("index.html", "app.js", "styles.css"):
        shutil.copy2(WEB_DIR / filename, static / filename)
    shutil.copy2(certificate, dashboard / "server.crt")
    shutil.copy2(HERE / "container" / "Dockerfile", dashboard / "Dockerfile")
    shutil.copy2(HERE / "container" / "server.py", dashboard / "server.py")

    runner = output / "h24-demo-runner"
    runner.mkdir(parents=True, exist_ok=True)
    shutil.copy2(certificate, runner / "server.crt")
    shutil.copy2(HERE / "container" / "runner.Dockerfile", runner / "Dockerfile")
    shutil.copy2(HERE / "container" / "runner.py", runner / "runner.py")
    shutil.copy2(HERE / "container" / "agent_worker.py", runner / "agent_worker.py")
    shutil.copy2(HERE / "container" / "bank_initialize.py", output / "h24-bank" / "config" / "h24_initialize.py")

    for directory in (
        "h24-state/stock-db",
        "h24-state/quantreplay-db",
        "h24-state/quantreplay",
    ):
        (output / directory).mkdir(parents=True, exist_ok=True)


def prepare_flat_network_images(output: Path, bundles: tuple[EmailBundle, BankBundle]) -> None:
    # The pip compiler adds Debian networking packages to every wrapped image.
    # H24 has no emulated router, so its bundle entrypoints need no routing tools.
    install_network_tools = (
        "RUN apt-get update && apt-get install -y --no-install-recommends "
        "iproute2 iputils-ping && rm -rf /var/lib/apt/lists/*\n"
    )
    for bundle in bundles:
        for container in bundle.getContainers().values():
            dockerfile = output / container.getHostname() / "Dockerfile"
            if dockerfile.is_file():
                source = dockerfile.read_text(encoding="utf-8")
                if install_network_tools in source:
                    dockerfile.write_text(source.replace(install_network_tools, "", 1), encoding="utf-8")


def attach(compiler: Docker, service: str, compose: str, ip: str, *, show=False, port="") -> None:
    compiler.attachCustomContainer(
        compose_entry=compose,
        asn=250,
        net="net0",
        ip_address=ip,
        port_forwarding=port,
        node_name=service,
        show_on_map=show,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=HERE / "output")
    parser.add_argument("--host-port", type=int, default=PORT)
    parser.add_argument("--platform", choices=("amd",), default="amd",
                        help="QuantReplay's published simulator image targets AMD64")
    parser.add_argument("--quantreplay-tag", default="main",
                        help="QuantReplay image tag (default: main)")
    parser.add_argument("--api-image", default="emuvista/stock-api:0.1.0")
    args = parser.parse_args()
    output = args.output.expanduser().resolve()

    stock_db_password = secrets.token_urlsafe(24)
    admin_token = secrets.token_urlsafe(40)
    api_url = f"https://{STOCK_API_IP}:8447"
    tag = args.quantreplay_tag

    emu = Emulator()
    base = Base()
    market_as = base.createAutonomousSystem(250)
    market_as.createNetwork("net0", "10.250.0.0/24")
    emu.addLayer(base)

    bank_password = "H24BankDemo2026!"
    mailbox_password = "H24MailDemo2026!"
    agent_emails = {name: f"{name.lower()}@h24.test" for name in ("Alice", "Bob", "Carol")}
    email = EmailBundle(emu, resolver="8.8.8.8", name="h24-mail")
    email.setHostname("mail.h24.test").setInitialConfiguration({
        "domains": ["h24.test"],
        "users": [
            {"email": agent_emails[name], "password": mailbox_password}
            for name in ("Alice", "Bob", "Carol")
        ] + [{"email": "bank@h24.test", "password": mailbox_password}],
    })
    bank = BankBundle(emu, name="h24-bank", resolver="8.8.8.8")
    bank.setHostname("bank.h24.test").setInitialConfiguration({
        "email": {"address": "bank@h24.test", "password": mailbox_password},
        "savingsProducts": [
            {"id": "USDC", "name": "USD Checking", "currency": "USD", "interestRate": 0},
        ],
        "customers": [
            {
                "id": name.lower(), "firstName": name, "lastName": "Agent",
                "email": agent_emails[name], "password": bank_password,
                "emailPassword": mailbox_password,
                "accounts": [{"id": name.lower() + "-checking", "name": name + " Checking",
                              "product": "USDC", "balance": 100}],
                "cards": [{"id": name.lower() + "-debit", "number": card_number,
                           "name": name + " Debit", "account": name.lower() + "-checking"}],
            }
            for name, card_number in (
                ("Alice", "4242424242424242"),
                ("Bob", "4012888888881881"),
                ("Carol", "4111111111111111"),
            )
        ],
    })
    bank.connectEmail(email, "bank@h24.test")
    bank.registerAPIClient("h24-stock", [f"http://{STOCK_API_IP}:8447/bank-callback"])
    emu.render()

    email.addInternalNetwork("250", "net0", [f"10.250.0.{i}" for i in range(50, 58)])
    bank.addInternalNetwork("250", "net0", [f"10.250.0.{i}" for i in range(40, 49)])
    # Configure email first so BankBundle can use its direct internal SMTP/IMAP addresses.
    email.configure()
    bank.configure()
    bank_provider = bank.getOpenBankingConnection("h24-stock")
    bank_provider["apiURL"] = f"http://{BANK_GATEWAY_IP}/api/v1"
    bank_provider["browserURL"] = f"http://{BANK_GATEWAY_IP}"
    bank_providers = json.dumps({"h24-bank": bank_provider}, separators=(",", ":"))
    worker_tokens = {name: secrets.token_urlsafe(32) for name in AGENT_VM_IPS}
    worker_urls = {name: f"http://{address}:8767" for name, address in AGENT_VM_IPS.items()}

    compiler = Docker(platform=Platform.AMD64)
    compiler.addContainerBundle(email)
    compiler.addContainerBundle(bank)
    attach(compiler, "h24-stock-db", service_entry("h24-stock-db", f"""\
        image: postgres:16-alpine
        restart: unless-stopped
        environment:
            POSTGRES_DB: stock
            POSTGRES_USER: stock
            POSTGRES_PASSWORD: {stock_db_password}
        volumes:
            - ./h24-state/stock-db:/var/lib/postgresql/data
        healthcheck:
            test: [CMD-SHELL, pg_isready -h 127.0.0.1 -U stock -d stock]
            interval: 3s
            timeout: 5s
            retries: 120"""), STOCK_DB_IP)

    attach(compiler, "h24-stock-api", service_entry("h24-stock-api", f"""\
        image: {args.api_image}
        restart: unless-stopped
        command: [uvicorn, stock_service.api:app, --host, 0.0.0.0, --port, '8447', --ssl-certfile, /stock-config/server.crt, --ssl-keyfile, /stock-config/server.key]
        environment:
            STOCK_DATABASE_URL: postgresql://stock:{stock_db_password}@{STOCK_DB_IP}:5432/stock
            STOCK_ADMIN_TOKEN: {admin_token}
            STOCK_EMAIL_HOST: {RUNNER_IP}
            STOCK_EMAIL_PORT: '2525'
            STOCK_EMAIL_FROM: stock@seed.example
            STOCK_EMAIL_STARTTLS: 'false'
            STOCK_ALLOW_TEST_EMAIL_DOMAIN: 'true'
            STOCK_TOKEN_ENCRYPTION_KEY: {base64.urlsafe_b64encode(secrets.token_bytes(32)).decode()}
            STOCK_BANK_PROVIDERS: '{bank_providers}'
            QUANTREPLAY_FIX_HOST: {QUANTREPLAY_IP}
            QUANTREPLAY_FIX_PORT: '9051'
            QUANTREPLAY_FIX_SENDER_COMP_ID: CLIENT_XETRA
            QUANTREPLAY_FIX_TARGET_COMP_ID: SIM_XETRA
        volumes:
            - ./h24-state/tls:/stock-config:ro
        depends_on:
            h24-stock-db:
                condition: service_healthy
            h24-bank-gateway:
                condition: service_started
        healthcheck:
            test: [CMD, python, -c, "import urllib.request,ssl; urllib.request.urlopen('https://127.0.0.1:8447/health', context=ssl._create_unverified_context())"]
            interval: 5s
            timeout: 5s
            retries: 60"""), STOCK_API_IP)

    attach(compiler, "h24-quantreplay-db", service_entry("h24-quantreplay-db", f"""\
        image: ghcr.io/quod-financial/postgres_marketsim:{tag}
        platform: linux/amd64
        restart: unless-stopped
        environment:
            POSTGRES_DB: simdb
            POSTGRES_USER: postgres
            POSTGRES_PASSWORD: postgres
        volumes:
            - ./h24-state/quantreplay-db:/var/lib/postgresql/data
        healthcheck:
            test: [CMD-SHELL, pg_isready -h 127.0.0.1 -U postgres -d simdb]
            interval: 3s
            timeout: 5s
            retries: 120
        """), QUANTREPLAY_DB_IP)

    attach(compiler, "h24-quantreplay-liquibase", service_entry("h24-quantreplay-liquibase", f"""\
        image: ghcr.io/quod-financial/liquibase:{tag}
        platform: linux/amd64
        restart: 'no'
        depends_on:
            h24-quantreplay-db:
                condition: service_healthy
        extra_hosts:
            - market-simulator-database:{QUANTREPLAY_DB_IP}"""), LIQUIBASE_IP)

    attach(compiler, "h24-quantreplay", service_entry("h24-quantreplay", f"""\
        image: ghcr.io/quod-financial/deploy_marketsim:{tag}
        platform: linux/amd64
        restart: unless-stopped
        environment:
            INSTANCE_ID: XETRA
            PREFIX: QUOD
        tmpfs:
            - "/market-simulator/quod/data:uid=1000,gid=1000,mode=0755"
        depends_on:
            h24-quantreplay-db:
                condition: service_healthy
            h24-quantreplay-config:
                condition: service_completed_successfully
        extra_hosts:
            - market-simulator-database:{QUANTREPLAY_DB_IP}"""), QUANTREPLAY_IP)

    attach(compiler, "h24-quantreplay-config", service_entry("h24-quantreplay-config", f"""\
        image: postgres:16-alpine
        restart: 'no'
        command: [sh, -c, "PGPASSWORD=postgres psql --host={QUANTREPLAY_DB_IP} --username=postgres --dbname=simdb -v ON_ERROR_STOP=1 -c \\\"UPDATE sim.listing SET random_orders_enabled = FALSE WHERE venue_id = 'XETRA' AND symbol = 'AMZ';\\\""]
        depends_on:
            h24-quantreplay-liquibase:
                condition: service_completed_successfully"""), CONFIG_IP)

    dashboard_service = service_entry("h24-stock-dashboard", """\
        build: ./h24-stock-dashboard
        restart: unless-stopped
        environment:
            STOCK_API_URL: https://10.250.0.31:8447
            DEMO_CONTROL_URL: http://10.250.0.81:8766
        depends_on:
            h24-stock-api:
                condition: service_started
            h24-demo-runner:
                condition: service_started""")
    attach(
        compiler, "h24-stock-dashboard", dashboard_service, DASHBOARD_IP, show=True,
        port=f"127.0.0.1:{args.host_port}:{PORT}/tcp",
    )

    runner_service = service_entry("h24-demo-runner", f"""\
        build: ./h24-demo-runner
        restart: unless-stopped
        environment:
            STOCK_API_URL: {api_url}
            STOCK_ADMIN_TOKEN: {admin_token}
            BANK_API_URL: http://{BANK_GATEWAY_IP}/api/v1
            BANK_IMAP_HOST: {EMAIL_IMAP_IP}
            BANK_EMAIL_DOMAIN: h24.test
            BANK_CUSTOMER_PASSWORD: {bank_password}
            BANK_MAILBOX_PASSWORD: {mailbox_password}
            AGENT_WORKER_URLS: '{json.dumps(worker_urls, separators=(',', ':'))}'
            AGENT_CONTROL_TOKENS: '{json.dumps(worker_tokens, separators=(',', ':'))}'
        env_file:
            - ../.env
        depends_on:
            h24-stock-api:
                condition: service_started
        expose:
            - '8766'
            - '2525'""")
    attach(compiler, "h24-demo-runner", runner_service, RUNNER_IP)

    for name, address in AGENT_VM_IPS.items():
        service_name = "h24-" + name.lower() + "-agent-vm"
        agent_service = service_entry(service_name, f"""\
        build: ./h24-demo-runner
        restart: unless-stopped
        command: [python, -u, /app/agent_worker.py]
        environment:
            AGENT_NAME: {name}
            AGENT_CONTROL_TOKEN: {worker_tokens[name]}
            STOCK_API_URL: {api_url}
        env_file:
            - ../.env
        depends_on:
            h24-stock-api:
                condition: service_started
        expose:
            - '8767'""")
        attach(compiler, service_name, agent_service, address, show=True)

    map_service = service_entry("h24-internet-map", """\
        platform: linux/amd64
        image: handsonsecurity/seedemu-internetmap:2.0
        container_name: h24-internet-map
        volumes:
            - /var/run/docker.sock:/var/run/docker.sock
        privileged: true""")
    attach(
        compiler, "h24-internet-map", map_service, INTERNET_MAP_IP, show=True,
        port=f"127.0.0.1:{INTERNET_MAP_PORT}:8080/tcp",
    )

    output.parent.mkdir(parents=True, exist_ok=True)
    emu.compile(compiler, str(output), override=True)
    prepare_flat_network_images(output, (email, bank))
    prepare_context(output)
    compose_path = output / "docker-compose.yml"
    compose_text = compose_path.read_text(encoding="utf-8")
    # Give this deployment its own Compose project even when the output
    # directory is named "output", as it was for the previous demo.
    compose_text = "name: h24-stock-market\n" + compose_text
    if compose_text.count("        - /bank/initialize.py\n") != 1:
        raise RuntimeError("Could not find the H24 Bank initializer in generated Compose")
    compose_text = compose_text.replace("        - /bank/initialize.py\n", "        - /bank/h24_initialize.py\n", 1)
    imap_start = compose_text.index("    h24-mail-imap:\n")
    imap_end = compose_text.find("\n    h24-mail-", imap_start + 1)
    if imap_end == -1:
        raise RuntimeError("Could not find the Mailu IMAP service boundary")
    imap_service = compose_text[imap_start:imap_end]
    for target, volume in (("/mail", "h24_mail_messages"),
                           ("/var/lib/dovecot", "h24_mail_index")):
        mount = re.compile(rf"(?m)^        - \S+:{re.escape(target)}$")
        if mount.search(imap_service) is None:
            raise RuntimeError(f"Could not find the Mailu IMAP bind mount for {target}")
        imap_service = mount.sub(f"        - {volume}:{target}", imap_service, count=1)
    compose_text = compose_text[:imap_start] + imap_service + compose_text[imap_end:]
    if "\nvolumes:\n" not in compose_text:
        compose_text = compose_text.replace(
            "\nnetworks:\n",
            "\nvolumes:\n"
            "  h24_mail_messages: {}\n"
            "  h24_mail_index: {}\n"
            "\nnetworks:\n",
            1,
        )
    smtp_start = compose_text.index("    h24-mail-smtp:\n")
    smtp_end = compose_text.find("\n    h24-mail-", smtp_start + 1)
    if smtp_end == -1:
        smtp_end = len(compose_text)
    smtp_service = compose_text[smtp_start:smtp_end]
    queue_volume = re.search(r"(?m)^        - \S+:/queue\s*$", smtp_service)
    if queue_volume is None:
        raise RuntimeError("Could not find the Mailu SMTP queue bind mount in generated Compose")
    smtp_service = smtp_service[:queue_volume.start()] + smtp_service[queue_volume.end():]
    if "      environment:\n" not in smtp_service:
        raise RuntimeError("Could not insert the Mailu SMTP temporary queue mount")
    smtp_service = smtp_service.replace(
        "      environment:\n", "      tmpfs:\n        - /queue\n      environment:\n", 1
    )
    compose_text = compose_text[:smtp_start] + smtp_service + compose_text[smtp_end:]
    compose_path.write_text(compose_text, encoding="utf-8")

    print(f"SEED Compose project: {output}")
    print(f"Live market dashboard: http://localhost:{args.host_port}/?live=1&symbol=AMZ")
    print(f"Internet Map: http://localhost:{INTERNET_MAP_PORT}/")
    print("The demo runner will create bank-linked agent accounts and wait for the dashboard's Start agent actions button.")
    print("Set LLM_API_KEY and LLM_MODEL in examples/H24_stock_market/.env before starting the demo runner.")
    print("QuantReplay simulator images target AMD64; Docker Desktop on ARM hosts may use emulation.")


if __name__ == "__main__":
    main()
