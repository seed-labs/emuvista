"""Deployment-time framework selection; no framework libraries run on the host."""

from importlib import import_module

FRAMEWORKS = {'langchain': '.langchain'}


def get_framework(name):
    if not isinstance(name, str) or name not in FRAMEWORKS:
        raise ValueError('unknown agent framework: ' + str(name))
    return import_module(FRAMEWORKS[name], __name__)
