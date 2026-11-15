"""Validate application hostnames and browser URL origins."""

import re
from urllib.parse import urlsplit


def hostname(value):
    if not isinstance(value, str) or len(value) > 253 or not re.fullmatch(
            r'[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?(?:\.[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?)+', value):
        raise ValueError('Use a lowercase fully qualified hostname')
    return value


def origin(value):
    if not isinstance(value, str) or not re.fullmatch(r'http://[a-z0-9.-]+(?::[0-9]{1,5})?', value):
        raise ValueError('Use an HTTP origin without a path')
    port = urlsplit(value).port
    if port is not None and not 1 <= port <= 65535:
        raise ValueError('Invalid HTTP port')
    return value
