"""Protocol helpers shared by service-owned tools, with normal TLS validation."""
import base64
from http.cookiejar import CookieJar
import json
import ssl
import urllib.error
import urllib.parse
import urllib.request


def tls(config):
    return ssl.create_default_context(cafile=config.get('caFile'))


def client(config):
    return urllib.request.build_opener(urllib.request.ProxyHandler({}),
        urllib.request.HTTPCookieProcessor(CookieJar()),urllib.request.HTTPSHandler(context=tls(config)))


def request(config,path='',method='GET',body=None,headers=None,opener=None,form=False):
    url=config['url'].rstrip('/')+path
    headers=dict(headers or {})
    if body is not None:
        if form:
            body=urllib.parse.urlencode(body).encode()
            headers['Content-Type']='application/x-www-form-urlencoded'
        else:
            body=json.dumps(body).encode()
            headers['Content-Type']='application/json'
    req=urllib.request.Request(url,data=body,headers=headers,method=method)
    try:
        with (opener or client(config)).open(req,timeout=15) as response:
            raw=response.read(1048576)
            try:return json.loads(raw)
            except (ValueError,UnicodeError):return raw.decode(errors='replace')
    except urllib.error.HTTPError as error:
        raise RuntimeError('Service returned HTTP '+str(error.code)) from None


def basic(username,password):
    return 'Basic '+base64.b64encode((username+':'+password).encode()).decode()
