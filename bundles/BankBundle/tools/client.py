"""Customer sessions and explicit card consent through the bank's existing APIs."""

from email.utils import parseaddr
import re
import threading
import time
from urllib.error import HTTPError
from urllib.parse import parse_qs, urlencode, urlsplit, urlunsplit, unquote
from urllib.request import HTTPCookieProcessor, HTTPRedirectHandler, HTTPSHandler, ProxyHandler, Request, build_opener

from emuvista_agent.http import client, request, tls
from emuvista_agent.mail import messages

_login_lock = threading.RLock()


def configuration(context, bank=None):
    config = context.service('bank')
    if bank is None:
        return config
    if bank not in config.get('instances', {}):
        raise ValueError('Bank is not configured for this agent')
    return dict(config['instances'][bank])


def connection(context, bank=None):
    config = configuration(context, bank)
    key = (config['url'], config['email'])
    with _login_lock:
        sessions = getattr(context, '_bank_connections', {})
        context._bank_connections = sessions
        cached = sessions.get(key)
        if cached and cached[0] > time.time():
            return config, cached[1], cached[2]
        mail = context.service('email')
        previous = max((message['uid'] for message in messages(mail, 50)), default=0)
        opener = client(config)
        headers = {'X-Device-Fingerprint': 'agent-'+context.identity}
        challenge = request(config, '/api/v1/authentication/login', method='POST', headers=headers,
            opener=opener, body={'email': config['email'], 'password': config['password']})['challengeToken']
        code = None
        for _ in range(30):
            for message in reversed(messages(mail, 10)):
                if message['uid'] <= previous or parseaddr(message['from'])[1].lower() != config['sender'].lower():
                    continue
                match = re.search(r'verification code is:\s*([A-Za-z0-9]+)', message['body'])
                if match:
                    code = match.group(1)
                    break
            if code:
                break
            time.sleep(2)
        if not code:
            raise RuntimeError('Bank login email did not arrive')
        request(config, '/api/v1/authentication/2fa', method='POST', headers=headers, opener=opener,
                body={'challengeToken': challenge, 'token': code})
        sessions[key] = (time.time()+120, opener, headers)
        return config, opener, headers


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, message, headers, url):
        return None


def _location(opener, url, headers, body=None):
    try:
        with opener.open(Request(url, headers=headers, data=body), timeout=30):
            raise RuntimeError('Bank authorization did not return a redirect')
    except HTTPError as error:
        if error.code in (302, 303) and error.headers.get('Location'):
            location = error.headers['Location']
            error.close()
            return location
        error.close()
        raise RuntimeError('Bank authorization returned HTTP '+str(error.code)) from None


def _origin(url):
    parsed = urlsplit(url)
    if parsed.scheme != 'https' or not parsed.hostname or parsed.username or parsed.password or parsed.fragment:
        raise ValueError('Invalid bank authorization address')
    return parsed.scheme, parsed.hostname, parsed.port or 443


def _one(query, name):
    values = query.get(name, [])
    if len(values) != 1 or not values[0]:
        raise ValueError('Invalid bank authorization response')
    return values[0]


def _bank_address(config, url):
    """Translate this configured bank's browser origin into its simulated address."""
    allowed = {_origin(config['url']), _origin(config.get('browserURL', config['url']))}
    if _origin(url) not in allowed:
        raise ValueError('Authorization address belongs to another bank')
    parsed, internal = urlsplit(url), urlsplit(config['url'])
    return urlunsplit((internal.scheme, internal.netloc, parsed.path, parsed.query, ''))


def authorize_card(context, bank, authorization_url, redirect_uri, card_id):
    """Return a private OAuth callback to the composing caller, never to the model."""
    config, authenticated, headers = connection(context, bank)
    authorization_url = _bank_address(config, authorization_url)
    authorization = urlsplit(authorization_url)
    query = parse_qs(authorization.query)
    scopes = {'openbanking:cards.read', 'openbanking:payments'}
    if (_origin(authorization_url) != _origin(config['url'])
            or authorization.path != '/api/v1/oauth2/authorize'
            or _one(query, 'redirect_uri') != redirect_uri
            or _one(query, 'response_type') != 'code'
            or _one(query, 'code_challenge_method') != 'S256'
            or set(_one(query, 'scope').split()) != scopes):
        raise ValueError('Bank authorization does not match the requested card-link flow')
    original_state = _one(query, 'state')
    client_id = _one(query, 'client_id')
    cookies = next(handler.cookiejar for handler in authenticated.handlers if isinstance(handler, HTTPCookieProcessor))
    opener = build_opener(ProxyHandler({}), HTTPCookieProcessor(cookies),
                          HTTPSHandler(context=tls(config)), _NoRedirect())
    location = _location(opener, authorization_url, {**headers, 'Accept': 'text/html'})
    consent = urlsplit(location)
    if consent.path == '/consent':
        _bank_address(config, location)
        parameters = parse_qs(consent.query)
        if _one(parameters, 'client_id') != client_id or set(_one(parameters, 'scope').split()) != scopes:
            raise ValueError('Bank consent changed the requested permissions')
        consent_state = _one(parameters, 'state')
        preview = request(config, '/api/v1/cards/authorization?'+urlencode({'state': consent_state}),
                          opener=opener, headers=headers)
        if preview['cardId'] != card_id:
            raise ValueError('Bank consent refers to another card')
        cookie_request = Request(config['url'].rstrip('/')+'/api/v1/oauth2/authorize')
        cookies.add_cookie_header(cookie_request)
        csrf = re.search(r'(?:^|;\s*)XSRF-TOKEN=([^;]+)', cookie_request.get_header('Cookie', ''))
        if not csrf:
            raise RuntimeError('Bank consent CSRF token was not received')
        fields = [('client_id', client_id), ('state', consent_state), ('_csrf', unquote(csrf[1]))]
        fields.extend(('scope', scope) for scope in sorted(scopes))
        location = _location(opener, config['url'].rstrip('/')+'/api/v1/oauth2/authorize',
                             {**headers, 'Content-Type': 'application/x-www-form-urlencoded'},
                             urlencode(fields).encode())
    callback = urlsplit(location)
    expected = urlsplit(redirect_uri)
    result = parse_qs(callback.query)
    if (_origin(location) != _origin(redirect_uri) or callback.path != expected.path
            or 'error' in result or _one(result, 'state') != original_state):
        raise ValueError('Bank callback did not match the card-link request')
    return {'state': original_state, 'code': _one(result, 'code')}
