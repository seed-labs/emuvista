"""Serve host time in UTC to AgentService's agents."""

from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json


class ClockHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path != '/time':
            self.send_error(404)
            return
        payload = json.dumps({'time': datetime.now(timezone.utc).isoformat()}).encode()
        self.send_response(200)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)


if __name__ == '__main__':
    ThreadingHTTPServer(('0.0.0.0', 8080), ClockHandler).serve_forever()
