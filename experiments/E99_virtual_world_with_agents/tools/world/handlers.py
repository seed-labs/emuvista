"""Public world directory and readiness probes; no host runtime access."""
import urllib.error
from emuvista_agent.http import client


def link_card(arguments, context):
    from .card_link import link_card as compose_link
    return compose_link(arguments, context)


def catalog(arguments, context):
    services = {name: {'name': settings.get('name', name)}
                for providers in context.tool_config.values() for name, settings in providers.items()}
    return {**context.knowledge, 'services': services}


def probe(arguments, context):
    services = {name: settings for providers in context.tool_config.values()
                for name, settings in providers.items()}
    name = arguments['service']
    if name not in services:
        raise ValueError('unknown service')
    config = services[name]
    try:
        with client(config).open(config['url'], timeout=8) as response:
            return {'service': name, 'reachable': True, 'ready': response.status < 500, 'status': response.status}
    except urllib.error.HTTPError as error:
        return {'service': name, 'reachable': True, 'ready': error.code < 500, 'status': error.code}
    except (OSError, urllib.error.URLError):
        return {'service': name, 'reachable': False, 'error': 'Service is unreachable'}
