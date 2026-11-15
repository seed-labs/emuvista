"""Serve the resident owner's public shop catalog from their own container."""

import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


def serve(config_path='/etc/emuvista-agent/config.json', address=('0.0.0.0', 8080)):
    class CatalogHandler(BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path not in ('/', '/catalog'):
                self.send_error(404)
                return
            shop = json.loads(Path(config_path).read_text())['persona']['possessions']['shop']
            catalog = {'name': shop['name'], 'seller': shop['seller'],
                       'products': [{key: product[key] for key in
                                     ('id', 'title', 'description', 'priceMinor', 'currency')}
                                    for product in shop['products']]}
            payload = json.dumps(catalog).encode()
            self.send_response(200)
            self.send_header('Content-Type', 'application/json; charset=utf-8')
            self.send_header('Content-Length', str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

    ThreadingHTTPServer(address, CatalogHandler).serve_forever()


if __name__ == '__main__':
    serve()
