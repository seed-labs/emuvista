"""Observations from the agent's own network environment."""
import socket


def identity(arguments, context):
    return {'agent': context.identity, 'hostname': socket.gethostname()}


def resolve(arguments, context):
    addresses = socket.getaddrinfo(arguments['hostname'], None, family=socket.AF_INET)
    return {'addresses': sorted({row[4][0] for row in addresses})}
