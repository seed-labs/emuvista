"""Framework-independent, timestamped events for local observation."""

from datetime import datetime, timezone
import json
import math
import os
import re
import threading
import uuid


class JsonEvents:
    def __init__(self, identity, configuration):
        self.identity = identity
        self.run_id = uuid.uuid4().hex
        self.sequence = 0
        self.lock = threading.Lock()
        self.secrets = {os.environ.get('LLM_API_KEY', '')}
        self._find_secrets(configuration.get('services', {}))
        self.secrets.discard('')

    def _find_secrets(self, value):
        if isinstance(value, dict):
            for key, item in value.items():
                if re.search(r'password|secret|token|api.?key', key, re.I) and isinstance(item, str):
                    self.secrets.add(item)
                else:
                    self._find_secrets(item)
        elif isinstance(value, list):
            for item in value:
                self._find_secrets(item)

    def clean(self, value, depth=0):
        if depth > 6:
            return '[truncated]'
        if isinstance(value, dict):
            return {str(key): '[redacted]' if re.search(r'password|secret|token|api.?key|otp|body', str(key), re.I)
                    else self.clean(item, depth+1) for key, item in list(value.items())[:40]}
        if isinstance(value, (list, tuple)):
            return [self.clean(item, depth+1) for item in value[:40]]
        if isinstance(value, str):
            for secret in sorted(self.secrets, key=len, reverse=True):
                value = value.replace(secret, '[redacted]')
            return re.sub(r'\b[0-9]{16,19}\b', lambda m: '****'+m.group()[-4:], value)[:4000]
        if isinstance(value, float) and not math.isfinite(value):
            return '[non-finite]'
        if value is None or isinstance(value, (int, float, bool)):
            return value
        return self.clean(str(value), depth+1)

    def __call__(self, event, **fields):
        with self.lock:
            self.sequence += 1
            payload = self.clean(fields)
            payload.update(agent=self.identity, event=event, run_id=self.run_id,
                           sequence=self.sequence,
                           timestamp=datetime.now(timezone.utc).isoformat(timespec='milliseconds'))
            print(json.dumps(payload, allow_nan=False), flush=True)


def result_summary(value):
    """Report outcomes without copying mailbox bodies or full bank records."""
    if isinstance(value, dict):
        public = ('state', 'balanceMinor', 'currency', 'sent', 'recipient', 'reachable', 'ready', 'status', 'agent', 'hostname')
        summary = {key: value[key] for key in public if key in value and
                   (value[key] is None or isinstance(value[key], (str, int, float, bool)))}
        if isinstance(value.get('addresses'), list):
            summary['addresses'] = [item for item in value['addresses'][:20] if isinstance(item, str)]
        return summary or {'keys': list(value)[:20]}
    if isinstance(value, list):
        return {'items': len(value)}
    return {'type': type(value).__name__}
