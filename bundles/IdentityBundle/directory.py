"""Synchronize employee identities using adapters owned by each application."""

import importlib.util
import json
from pathlib import Path
import time
from urllib.parse import urlencode

from initialize import admin_token, profile, request


def load(name, provider):
    spec = importlib.util.spec_from_file_location(name, '/identity-config/' + provider['module'])
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module, provider['configuration']


def main():
    configuration = json.loads(Path('/identity-config/identity.json').read_text())
    sources = [load(name, provider) for name, provider in configuration['sources'].items()]
    consumers = {name: load(name, provider) for name, provider in configuration['consumers'].items()}
    state_path = Path('/identity-state/profiles.json')
    previous = json.loads(state_path.read_text()) if state_path.exists() else {'people': {}, 'consumers': {}}
    while True:
        try:
            people = {person['id']: person for module, settings in sources for person in module.people(settings)}
            token = admin_token()
            for identifier, person in people.items():
                if previous['people'].get(identifier) != person:
                    users = request('GET', '/admin/realms/company/users?' + urlencode({
                        'username': identifier.lower(), 'exact': 'true'}), token=token)
                    if users:
                        request('PUT', '/admin/realms/company/users/' + users[0]['id'], profile(person), token)
                    else:
                        request('POST', '/admin/realms/company/users', {
                            **profile(person), 'credentials': [{'type': 'password',
                                'value': 'EmployeeDemo123!', 'temporary': True}],
                        }, token)
                    previous['people'][identifier] = person
                    print('Synchronized identity ' + identifier, flush=True)
            state_path.write_text(json.dumps(previous, indent=2))
            for name, (module, settings) in consumers.items():
                try:
                    records = previous['consumers'].setdefault(name, {})
                    for identifier, person in people.items():
                        if records.get(identifier) != person:
                            module.provision(person, settings)
                            records[identifier] = person
                            print('Synchronized ' + name + ' employee ' + identifier, flush=True)
                            state_path.write_text(json.dumps(previous, indent=2))
                except Exception as error:
                    print(name + ' provisioning pending: ' + type(error).__name__
                          + ' ' + str(getattr(error, 'code', '')), flush=True)
        except Exception as error:
            # Applications can initialize independently; retry when they are ready.
            print('Employee synchronization pending: ' + type(error).__name__, flush=True)
        time.sleep(30)


if __name__ == '__main__':
    main()
