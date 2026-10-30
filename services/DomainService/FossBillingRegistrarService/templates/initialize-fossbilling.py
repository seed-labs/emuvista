#!/usr/bin/env python3
"""Initialize local FOSSBilling on container startup without accessing Registry or DNS APIs.
"""
import base64
import json
from pathlib import Path
import subprocess
import sys
import time

HERE = Path(__file__).resolve().parent
FossBillingFileTemplates = {name: (HERE / name).read_text() for name in (
    'configure-site-url.php', 'configure-epp-registrar.php', 'create-client.php')}

SETTINGS = {}
ROOT = "/var/www/fossbilling"
# Call the container-local web service.
LOCAL_URL = "http://127.0.0.1:8080"


def execute(*command, input_text=None, check=True):
    """Run local commands without including input or output in errors."""
    return subprocess.run(command, input=input_text, text=True, capture_output=True,
                          check=check, timeout=200)


def php_json(value):
    """Embed JSON safely without PHP string interpolation."""
    encoded = base64.b64encode(json.dumps(value).encode()).decode('ascii')
    return "json_decode(base64_decode('" + encoded + "'), true, 512, JSON_THROW_ON_ERROR)"


def database_password() -> str:
    """Read the database password from service-generated settings."""
    return SETTINGS['database_password']


def installed() -> bool:
    """Use config.php to detect completed installation."""
    return execute("test", "-f", f"{ROOT}/config.php", check=False).returncode == 0


def install(url: str, admin_email: str, admin_password: str) -> None:
    """Submit the installer form only on the first run."""
    if installed():
        return
    if execute("test", "-f", f"{ROOT}/install/install.php", check=False).returncode:
        raise RuntimeError("Installer is missing and config.php does not exist")

    fields = {
        "system_url": url,
        "database_hostname": 'localhost',
        "database_port": '3306',
        "database_name": 'fossbilling',
        "database_username": 'fossbilling',
        "database_password": database_password(),
        "admin_name": 'admin',
        "admin_email": admin_email,
        "admin_password": admin_password,
        "currency_code": "USD",
    }
    command = ["curl", "-sS", "--max-time", "180", "-X", "POST",
               f"{LOCAL_URL}/install/install.php?a=install"]
    for key, value in fields.items():
        command.extend(["--data-urlencode", f"{key}={value}"])
    response = execute(*command)
    if not installed():
        from html import unescape
        from re import sub

        message = sub(r"<[^>]+>", " ", response.stdout)
        raise RuntimeError("FOSSBilling installer failed: " + unescape(" ".join(message.split()))[-700:])


def configure_site_url(url: str) -> None:
    """Configure local and internal URLs from port forwarding."""
    from urllib.parse import urlsplit

    parsed = urlsplit(url)
    if (parsed.scheme != "http" or not parsed.hostname or parsed.username or parsed.password
            or parsed.query or parsed.fragment or parsed.path not in {"", "/"}):
        raise ValueError("Site URL must be an HTTP origin without credentials or extra paths")
    # FOSSBilling 0.8.7 stores URLs without a scheme.
    site_url = parsed.netloc + "/"
    php = (FossBillingFileTemplates['configure-site-url.php']
           .replace("URL_PLACEHOLDER", php_json(site_url))
           .replace("FORWARDED_PORT_PLACEHOLDER", php_json(SETTINGS['forwarded_port'])))
    result = execute("php8.5", input_text=php)
    sys.stdout.write(result.stdout)


def create_client(email: str, password: str) -> None:
    """Create a demo client; verify existing passwords and fill missing EPP contact fields."""
    # Use the built-in PasswordManager.
    # Bypass the online spam lists unavailable in simulation.
    php = FossBillingFileTemplates['create-client.php']
    php = (php.replace("EMAIL_PLACEHOLDER", php_json(email))
           .replace("PASSWORD_PLACEHOLDER", php_json(password))
           .replace("PROFILE_PLACEHOLDER", php_json(SETTINGS['client_profile'])))
    result = execute("php8.5", input_text=php)
    sys.stdout.write(result.stdout)


def configure_epp() -> None:
    """Bind configured TLDs to Namingo EPP while preserving existing prices."""
    result = execute("cat", "/opt/fossbilling/epp-connection.json")
    connection = json.loads(result.stdout)
    php = FossBillingFileTemplates['configure-epp-registrar.php']
    php = (php.replace("CONNECTION_PLACEHOLDER", php_json(connection))
           .replace("TLD_PRICES_PLACEHOLDER", php_json(SETTINGS['prices'])))
    result = execute("php8.5", input_text=php)
    sys.stdout.write(result.stdout)


def finish_install() -> None:
    """Set config permissions, remove the installer, and configure cron without duplicates."""
    execute("chmod", "644", f"{ROOT}/config.php")
    execute("rm", "-rf", f"{ROOT}/install")
    previous = execute("crontab", "-l", check=False)
    lines = previous.stdout.splitlines() if previous.returncode == 0 else []
    cron_command = f"/usr/bin/php8.5 {ROOT}/cron.php"
    updated = [line for line in lines if not line.endswith((cron_command, f"/usr/bin/php {ROOT}/cron.php"))]
    updated.append(f"* * * * * /usr/bin/php8.5 {ROOT}/cron.php")
    if updated != lines:
        execute("crontab", "-", input_text="\n".join(updated) + "\n")


def wait_for_services():
    """Wait for database and web services without requiring the not-yet-installed schema."""
    # Probe the installer before installation to avoid misclassifying homepage redirects.
    path = '/' if installed() else '/install/install.php'
    last_db_status, last_web_status, last_http_status = None, None, ''
    for attempt in range(120):
        db = execute('mariadb', '-N', '-e', 'SELECT 1', check=False)
        web = execute('curl', '-sS', '-o', '/dev/null', '--max-time', '2',
                     '-w', '%{http_code}', LOCAL_URL + path, check=False)
        last_db_status, last_web_status = db.returncode, web.returncode
        last_http_status = web.stdout.strip()
        if (last_db_status == 0 and last_web_status == 0
                and last_http_status in ('200', '301', '302', '303', '307', '308')):
            return
        if attempt < 119:
            time.sleep(2)
    raise RuntimeError(
        f'FOSSBilling database/web readiness timed out: database exit={last_db_status}, '
        f'curl exit={last_web_status}, HTTP={last_http_status or "unknown"}, path={path}'
    )


def main():
    """Preserve existing accounts and prices on restart; mark readiness after success."""
    ready = Path('/run/fossbilling-initialized')
    failed = Path('/run/fossbilling-initialization.failed')
    ready.unlink(missing_ok=True)
    failed.unlink(missing_ok=True)
    stage = 'read configuration'
    try:
        SETTINGS.update(json.loads((HERE / 'setup-config.json').read_text()))
        stage = 'wait for local database and web'
        wait_for_services()
        stage = 'install FOSSBilling'
        install(SETTINGS['url'], SETTINGS['admin_email'], SETTINGS['admin_password'])
        stage = 'configure site URL'
        configure_site_url(SETTINGS['url'])
        stage = 'configure EPP and TLDs'
        configure_epp()
        stage = 'initialize demo client'
        create_client(SETTINGS['client_email'], SETTINGS['client_password'])
        stage = 'finish installation'
        finish_install()
        if SETTINGS.get('dns_hosting'):
            stage = 'configure DNS Hosting product'
            subprocess.run(['php8.5', '/opt/dns-hosting/configure-dns-hosting-product.php'],
                           input=Path('/opt/dns-hosting/product-credentials.json').read_text(),
                           text=True, check=True)
        ready.touch()
        return 0
    except (OSError, subprocess.SubprocessError, RuntimeError, ValueError, KeyError) as error:
        failed.touch()
        print(f'FOSSBilling initialization failed ({stage}): {type(error).__name__}', file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
