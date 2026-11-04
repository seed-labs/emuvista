#!/usr/bin/env python3
"""Check H12 services, purchase a domain, and verify its DNS resolution."""

import argparse
from html.parser import HTMLParser
from http.cookiejar import CookieJar
import json
from pathlib import Path
import shlex
import sys
import time
from urllib.parse import unquote, urlencode
from urllib.request import HTTPRedirectHandler, HTTPCookieProcessor, Request, build_opener
import uuid


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class PaymentForm(HTMLParser):
    """Extract the signed form, including the adapter's iframe srcdoc."""

    def __init__(self):
        super().__init__()
        self.action = None
        self.fields = {}

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == 'iframe' and 'srcdoc' in attrs:
            nested = PaymentForm()
            nested.feed(attrs['srcdoc'])
            self.action, self.fields = nested.action, nested.fields
        elif tag == 'form':
            self.action = attrs.get('action')
        elif tag == 'input' and attrs.get('name'):
            self.fields[attrs['name']] = attrs.get('value', '')


class Customer:
    def __init__(self, origin):
        self.origin = origin
        self.cookies = CookieJar()
        self.http = build_opener(HTTPCookieProcessor(self.cookies), NoRedirect())

    def request(self, path, fields=None):
        headers = {}
        for cookie in self.cookies:
            if cookie.name in ('fossbilling_csrf', 'csrf_token'):
                headers['X-CSRF-Token'] = unquote(cookie.value)
        body = None if fields is None else urlencode(fields).encode()
        request = Request(self.origin + path, data=body, headers=headers)
        with self.http.open(request, timeout=90) as response:
            return response.read().decode()

    def api(self, path, **fields):
        response = json.loads(self.request('/api/' + path, fields))
        if response.get('error'):
            # Do not include API payloads, cookies, or payment signatures in logs.
            raise RuntimeError('API rejected ' + path)
        return response['result']

    def wait_status(self, path, status, **fields):
        deadline = time.monotonic() + 300
        while True:
            result = self.api(path, **fields)
            if result['status'] == status:
                return result
            if time.monotonic() >= deadline:
                raise RuntimeError(f'{path}: expected {status}, observed {result["status"]}')
            time.sleep(5)


def purchase(args, report):
    customer = Customer(args.registrar)
    report['stage'] = 'login'
    customer.request('/')
    customer.api('guest/client/login', email=args.email, password=args.password)
    gateways = customer.api('guest/invoice/gateways', format='pairs')
    gateway = next(key for key, title in gateways.items() if title.lower() == 'fakepayment')
    products = customer.api('guest/product/get_list', per_page=100)['list']
    domain_product = next(item['id'] for item in products if item['type'] == 'domain')
    dns_product = next(item['id'] for item in products if item['type'] == 'dns')

    def checkout(kind, fields):
        report['stage'] = kind + ' cart'
        customer.api('guest/cart/add_item', **fields)
        report['stage'] = kind + ' checkout'
        result = customer.api('client/cart/checkout', gateway_id=gateway)
        order_id = result['order_id']
        report[kind + '_order_id'] = order_id
        invoice_hash = result.get('invoice_hash')
        if kind == 'domain' and not invoice_hash:
            raise RuntimeError('Domain checkout did not produce an unpaid invoice')
        if invoice_hash:
            report['stage'] = kind + ' payment'
            invoice = customer.api('guest/invoice/get', hash=invoice_hash)
            report[kind + '_invoice_id'] = invoice['id']
            payment = customer.api('guest/invoice/payment', hash=invoice_hash, gateway_id=gateway)
            form = PaymentForm()
            form.feed(payment['result'])
            if form.action != args.payment + '/pay':
                raise RuntimeError('Invoice form does not target the configured FakePayment service')
            if form.fields.get('invoice') != str(invoice['id']):
                raise RuntimeError('Payment form invoice mismatch')
            form.fields['action'] = 'confirm'
            # Submit once, using a separate session without Registrar cookies.
            request = Request(form.action, data=urlencode(form.fields).encode())
            with build_opener(NoRedirect()).open(request, timeout=90) as response:
                response.read()
            report['stage'] = kind + ' invoice paid'
            customer.wait_status('guest/invoice/get', 'paid', hash=invoice_hash)
        report['stage'] = kind + ' order active'
        customer.wait_status('client/order/get', 'active', id=order_id)
        return order_id

    sld, tld = args.domain.split('.', 1)
    domain_order = checkout('domain', {
        'id': domain_product, 'action': 'register', 'register_sld': sld,
        'register_tld': '.' + tld, 'register_years': 1,
    })
    report['stage'] = 'nameservers'
    customer.api('client/servicedomain/update_nameservers', order_id=domain_order,
                 ns1='ns1.example.com', ns2='ns2.example.com')
    dns_order = checkout('dns', {'id': dns_product, 'domain_name': args.domain})
    report['stage'] = 'DNS record'
    customer.api('client/servicedns/add', order_id=dns_order, record_name='www',
                 record_type='A', record_value=args.address, record_ttl=60)
    report['stage'] = 'complete'


def purchase_main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--purchase', action='store_true')
    parser.add_argument('--registrar', required=True)
    parser.add_argument('--payment', required=True)
    parser.add_argument('--domain', required=True)
    parser.add_argument('--address', default='192.0.2.123')
    parser.add_argument('--email', default='user@example.com')
    parser.add_argument('--password', default='Aa123456')
    args = parser.parse_args()
    report = {'domain': args.domain, 'status': 'failed'}
    try:
        purchase(args, report)
        report['status'] = 'passed'
    except Exception as error:
        report['error'] = type(error).__name__
        if isinstance(error, RuntimeError):
            report['error'] += ': ' + str(error)
        # Retain stage and known IDs for diagnosis without logging HTTP responses.
    print(json.dumps(report), flush=True)
    return 0 if report['status'] == 'passed' else 1

def main() -> int:
    sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "seed-emulator"))
    from seedemu.testing import ComposeRuntimeTest

    test = ComposeRuntimeTest(__file__)
    registrar = test.require_service(150, "host_1")
    registry = test.require_service(151, "host_1")
    payment = test.require_service(160, "host_0")
    primary = test.require_service(170, "host_0")
    secondary = test.require_service(170, "host_1")
    resolver = test.require_service(153, "local-dns-2")
    com_dns = test.require_service(151, "host_0", "COM parent DNS is generated")

    if registrar:
        test.exec_check(
            "FOSSBilling and payment gateway are initialized",
            registrar,
            "test -f /run/fossbilling-initialized && "
            "test -f /run/fake-payment-initialized && "
            "test ! -f /run/fossbilling-initialization.failed && "
            "test ! -f /run/fake-payment-initialization.failed",
        )
        test.exec_check(
            "FOSSBilling client portal responds",
            registrar,
            "curl --connect-timeout 3 --max-time 10 -fsS http://127.0.0.1:8080/ >/dev/null",
        )

    if registrar and registry:
        test.exec_check(
            "Registrar reaches Registry control panel",
            registrar,
            f"curl --connect-timeout 3 --max-time 10 -fsS http://{registry.address}:8080/ >/dev/null",
        )
        # Read the EPP greeting without logging in or modifying Registry state.
        greeting = f"""
import socket
import ssl
import struct
import xml.etree.ElementTree as ET

context = ssl._create_unverified_context()
with socket.create_connection(({registry.address!r}, 700), timeout=5) as tcp:
    with context.wrap_socket(tcp, server_hostname={registry.address!r}) as tls:
        stream = tls.makefile('rb')
        size = struct.unpack('!I', stream.read(4))[0]
        assert 4 < size <= 65536, 'Invalid EPP frame size'
        root = ET.fromstring(stream.read(size - 4))
        assert root.find('{{urn:ietf:params:xml:ns:epp-1.0}}greeting') is not None, 'Missing EPP greeting'
"""
        test.exec_check("Registry sends an EPP greeting over TLS", registrar,
                        "python3 -c " + shlex.quote(greeting))

    if registrar and payment:
        test.exec_check(
            "Registrar reaches healthy FakePayment service",
            registrar,
            f'test "$(curl --connect-timeout 3 --max-time 10 -fsS http://{payment.address}:8080/health)" = ok',
        )

    for role, dns in (("primary", primary), ("secondary", secondary)):
        if dns:
            test.exec_check(f"DNS {role} configuration is valid", dns, "named-checkconf")
            test.exec_check(f"DNS {role} responds to RNDC", dns, "rndc status >/dev/null")
        if registrar and dns:
            connect = (
                f"import socket; socket.create_connection(({dns.address!r}, 7650), timeout=5).close()"
            )
            test.exec_check(f"Registrar reaches DNS {role} API port", registrar,
                            "python3 -c " + shlex.quote(connect))
        if registry and dns:
            test.exec_check(
                f"DNS {role} serves the example.com nameservers",
                registry,
                f'test "$(dig +time=2 +tries=1 @{dns.address} example.com NS +norecurse +short | sort)" '
                '= "$(printf \'ns1.example.com.\\nns2.example.com.\\n\')"',
            )

    if registry and resolver:
        test.exec_check(
            "Recursive DNS resolves the base google.com record",
            registry,
            f'test "$(dig +time=2 +tries=1 @{resolver.address} google.com A +short)" = 2.2.2.2',
        )

    if not test.exit_code():
        domain = 'h12-test-' + uuid.uuid4().hex[:16] + '.com'
        source = Path(__file__).read_text()
        command = (
            f'python3 - --purchase --registrar http://{registrar.address}:8080 '
            f'--payment http://{payment.address}:8080 --domain {domain} '
            "<<'H12_PURCHASE_SCRIPT'\n" + source + '\nH12_PURCHASE_SCRIPT'
        )
        # Checkout and payment must never be retried after an ambiguous failure.
        result = test.exec_check(
            f'Purchase {domain}, pay invoice, activate DNS Hosting and add A record',
            registrar, command, retries=1, timeout=1500,
        )
        if result['status'] == 'passed':
            registry_check = f"""
$config = require '/opt/registry/epp/config.php';
$db = new PDO('mysql:host=127.0.0.1;dbname=registry;charset=utf8mb4',
    'registry', $config['db_password'], [PDO::ATTR_ERRMODE => PDO::ERRMODE_EXCEPTION]);
$query = $db->prepare('SELECT id FROM domain WHERE name = ? AND exdate > CURRENT_TIMESTAMP');
$query->execute(['{domain}']);
$id = $query->fetchColumn();
if (!$id) {{ exit(1); }}
$query = $db->prepare('SELECT DISTINCT h.name FROM domain_host_map m JOIN host h ON h.id = m.host_id WHERE m.domain_id = ? ORDER BY h.name');
$query->execute([$id]);
if ($query->fetchAll(PDO::FETCH_COLUMN) !== ['ns1.example.com', 'ns2.example.com']) {{ exit(1); }}
echo 'Registry domain and nameservers verified';
"""
            test.exec_check('Registry contains the purchased domain and nameservers', registry,
                            'php8.5 -r ' + shlex.quote(registry_check))
            test.exec_check(
                'COM parent publishes the purchased domain delegation', registry,
                f'test "$(dig +time=2 +tries=1 @{com_dns.address} {domain} NS '
                '+norecurse +noall +answer +authority | '
                "awk '$4 == \"NS\" {print $5}' | sort -u)\" "
                '= "$(printf \'ns1.example.com.\\nns2.example.com.\\n\')"',
                retries=60, interval=5,
            )
            for role, dns in (('primary', primary), ('secondary', secondary), ('recursive', resolver)):
                recursion = '' if role == 'recursive' else '+norecurse'
                test.exec_check(
                    f'{role} DNS resolves www.{domain} to the purchased hosting record', registry,
                    f'test "$(dig +time=2 +tries=1 @{dns.address} www.{domain} A '
                    f'{recursion} +short)" = 192.0.2.123',
                    retries=60, interval=5,
                )

    test.write_summary("h12-custom-runtime-test.json")
    return test.exit_code()


if __name__ == "__main__":
    raise SystemExit(purchase_main() if '--purchase' in sys.argv else main())
