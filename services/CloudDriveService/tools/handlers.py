"""WebDAV and OCS requests issued from the agent's own execution environment."""

import base64
import hashlib
import json
import re
from urllib.error import HTTPError
from urllib.parse import quote, urlencode
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener

from emuvista_agent.http import basic


MAX_TRANSFER_BYTES = 256 * 1024


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, request, response, code, message, headers, url):
        return None


def _path(value):
    parts = value.split('/')
    if (not value.startswith('/') or value == '/' or '\x00' in value
            or any(part in {'.', '..'} for part in parts)):
        raise ValueError('Cloud path must be absolute and contain no dot segments')
    return '/' + '/'.join(quote(part, safe='') for part in parts[1:])


def _request(context, service_id, path, method='GET', body=None, headers=None):
    account = context.accounts.get('cloud', {}).get(service_id)
    if account is None:
        raise ValueError('Cloud service is not configured for this agent')
    provider = context.tool_config['cloud'][service_id]
    headers = {**(headers or {}),
               'Authorization': basic(account['username'], account['password'])}
    request = Request(provider['url'].rstrip('/') + path,
                      data=body, headers=headers, method=method)
    opener = build_opener(ProxyHandler({}), _NoRedirect())
    try:
        with opener.open(request, timeout=30) as response:
            content = response.read(MAX_TRANSFER_BYTES + 1)
            status = response.status
    except HTTPError as error:
        status = error.code
        error.close()
        raise RuntimeError('Cloud service returned HTTP ' + str(status)) from None
    if len(content) > MAX_TRANSFER_BYTES:
        raise ValueError('Cloud response exceeds 256 KiB')
    return status, content


def _file_path(arguments, context):
    account = context.accounts['cloud'][arguments['service_id']]
    return ('/remote.php/dav/files/' + quote(account['username'], safe='')
            + _path(arguments['path']))


def storage_find(arguments, context):
    providers = context.tool_config.get('cloud', {})
    accounts = context.accounts.get('cloud', {})
    return {'services': [{'service_id': name, 'provider': 'nextcloud'}
                         for name in sorted(providers) if name in accounts]}


def file_upload(arguments, context):
    content = base64.b64decode(arguments['content_base64'], validate=True)
    if len(content) > MAX_TRANSFER_BYTES:
        raise ValueError('Cloud upload exceeds 256 KiB')
    status, _ = _request(context, arguments['service_id'], _file_path(arguments, context),
                         method='PUT', body=content,
                         headers={'Content-Type': 'application/octet-stream'})
    return {'service_id': arguments['service_id'], 'path': arguments['path'],
            'successful': True, 'http_status': status, 'bytes_uploaded': len(content),
            'sha256': hashlib.sha256(content).hexdigest()}


def file_download(arguments, context):
    status, content = _request(context, arguments['service_id'], _file_path(arguments, context))
    return {'service_id': arguments['service_id'], 'path': arguments['path'],
            'successful': True, 'http_status': status,
            'content_base64': base64.b64encode(content).decode(),
            'bytes_downloaded': len(content), 'sha256': hashlib.sha256(content).hexdigest()}


def file_share(arguments, context):
    _path(arguments['path'])
    if arguments.get('permission', 'read') != 'read':
        raise ValueError('Only read permission is supported')
    if not re.fullmatch(r'[A-Za-z0-9_.@-]{1,128}', arguments['recipient']):
        raise ValueError('Invalid cloud recipient username')
    body = urlencode({'path': arguments['path'], 'shareType': 0,
                      'shareWith': arguments['recipient'], 'permissions': 1}).encode()
    status, content = _request(
        context, arguments['service_id'], '/ocs/v2.php/apps/files_sharing/api/v1/shares?format=json',
        method='POST', body=body,
        headers={'OCS-APIRequest': 'true', 'Accept': 'application/json',
                 'Content-Type': 'application/x-www-form-urlencoded'})
    ocs = json.loads(content)['ocs']
    if ocs['meta']['statuscode'] not in (100, 200):
        raise RuntimeError('Cloud share request was rejected')
    return {'service_id': arguments['service_id'], 'path': arguments['path'],
            'recipient': arguments['recipient'], 'successful': True,
            'http_status': status, 'share_id': str(ocs['data']['id']),
            'permission': 'read'}
