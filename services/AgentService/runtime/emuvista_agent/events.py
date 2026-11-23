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
        self._find_secrets(configuration.get('persona', {}))
        self._find_secrets(configuration.get('tool_config', {}))
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
        if depth > 40:
            return '[truncated]'
        if isinstance(value, dict):
            return {str(key): '[redacted]' if re.search(r'password|secret|token|api.?key|otp|^authorization$|authorization.?code', str(key), re.I)
                    else self.clean(item, depth + 1) for key, item in value.items()}
        if isinstance(value, (list, tuple)):
            return [self.clean(item, depth + 1) for item in value]
        if isinstance(value, str):
            for secret in sorted(self.secrets, key=len, reverse=True):
                value = value.replace(secret, '[redacted]')
            value = re.sub(r'(?i)\b(Bearer|Basic)\s+\S+', r'\1 [redacted]', value)
            return re.sub(r'(?i)(\b(?:verification|security|login|one[- ]time)\s+code\s*(?:is\s*)?[:：]?\s*)([a-z0-9]{4,12})\b',
                          r'\1[redacted]', value)
        if isinstance(value, float) and not math.isfinite(value):
            return '[non-finite]'
        if value is None or isinstance(value, (int, float, bool)):
            return value
        return self.clean(str(value), depth + 1)

    def __call__(self, event, **fields):
        with self.lock:
            self.sequence += 1
            payload = self.clean(fields)
            payload.update(agent=self.identity, event=event, run_id=self.run_id,
                           sequence=self.sequence,
                           timestamp=datetime.now(timezone.utc).isoformat(timespec='milliseconds'))
            print(json.dumps(payload, allow_nan=False), flush=True)


def result_summary(value):
    """Compact outcome alongside the full, sanitized tool observation."""
    if isinstance(value, dict):
        public = ('state', 'balanceMinor', 'currency', 'sent', 'recipient',
                  'reachable', 'ready', 'status', 'agent', 'hostname')
        summary = {key: value[key] for key in public if key in value and
                   (value[key] is None or isinstance(value[key], (str, int, float, bool)))}
        if isinstance(value.get('addresses'), list):
            summary['addresses'] = [item for item in value['addresses']
                                    [:20] if isinstance(item, str)]
        return summary or {'keys': list(value)[:20]}
    if isinstance(value, list):
        return {'items': len(value)}
    return {'type': type(value).__name__}
