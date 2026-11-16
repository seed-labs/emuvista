#!/usr/bin/env python3
"""Check H16 DNS, CA trust, Mastodon processes and public HTTPS APIs."""

from pathlib import Path
import shlex
import sys


def main() -> int:
    sys.path.insert(0, str(Path(__file__).resolve().parents[3] / 'seed-emulator'))
    from seedemu.testing import ComposeRuntimeTest

    test = ComposeRuntimeTest(__file__)
    primary = test.require_service(151, 'dns')
    secondary = test.require_service(151, 'dns-secondary')
    resolver = test.require_service(151, 'local-dns')
    ca = test.require_service(151, 'ca')
    mastodon = test.require_service(151, 'h14-mastodon')
    alice = test.require_service(151, 'alice')
    bob = test.require_service(151, 'bob')

    for role, dns in (('primary', primary), ('secondary', secondary)):
        if dns:
            test.exec_check(f'{role} DNS configuration is valid', dns, 'named-checkconf')
            test.exec_check(f'{role} DNS responds to RNDC', dns, 'rndc status >/dev/null')

    for client in (alice, bob):
        if not client:
            continue
        for role, dns in (('primary', primary), ('secondary', secondary), ('recursive', resolver)):
            if not dns:
                continue
            recursion = '' if role == 'recursive' else '+norecurse'
            for name, target in (('mastodon.com', mastodon), ('ca.mastodon.com', ca)):
                if target:
                    test.exec_check(
                        f'{client.name}: {role} DNS resolves {name}', client,
                        f'test "$(dig +time=2 +tries=1 @{dns.address} {name} A '
                        f'{recursion} +short)" = {shlex.quote(target.address)}',
                    )

        # curl verifies the hostname and certificate using the system trust store.
        # Client images provide curl but do not necessarily include Python.
        for label, url in (
            ('CA ACME directory', 'https://ca.mastodon.com/acme/acme/directory'),
            ('Mastodon instance API', 'https://mastodon.com:18443/api/v2/instance'),
            ('Mastodon public timeline', 'https://mastodon.com:18443/api/v1/timelines/public?limit=1'),
        ):
            test.exec_check(
                f'{client.name}: trusted HTTPS reaches {label}', client,
                'curl --noproxy "*" --connect-timeout 3 --max-time 10 '
                '--fail --silent --show-error ' + shlex.quote(url) + ' > /dev/null',
                retries=20, interval=3,
            )

    if mastodon:
        test.exec_check('Mastodon Nginx configuration is valid', mastodon, 'nginx -t')
        for process in ('web', 'worker', 'streaming'):
            test.exec_check(
                f'Mastodon {process} process is running', mastodon,
                'supervisorctl -c /opt/mastodon-service/supervisord.conf status '
                + process + " | grep -q ' RUNNING '",
            )
        accounts_check = '''
require 'json'
JSON.parse(File.read('/opt/mastodon-service/accounts.json')).each do |entry|
  user = Account.find_local(entry.fetch('username'))&.user
  raise 'Declared account is missing or unconfirmed' unless user && user.confirmed?
end
puts 'Declared Mastodon accounts exist and are confirmed'
'''
        test.exec_check(
            'Declared Mastodon accounts are initialized', mastodon,
            'runuser -u mastodon -- /opt/mastodon-service/run.sh bundle exec rails runner '
            + shlex.quote(accounts_check), retries=1, timeout=120,
        )

    test.write_summary('h14-custom-runtime-test.json')
    return test.exit_code()


if __name__ == '__main__':
    raise SystemExit(main())
