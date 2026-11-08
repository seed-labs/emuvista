"""Bounded resident experience, including calls from interrupted model moments."""

from datetime import datetime, timezone
import json
import os
from pathlib import Path
import tempfile
import threading
import uuid


def bounded(value, limit=6000):
    encoded = json.dumps(value, default=str, ensure_ascii=False)
    return json.loads(encoded) if len(encoded) <= limit else {'truncated': True, 'preview': encoded[:limit]}


class Experience:
    def __init__(self, directory):
        directory = Path(directory)
        directory.mkdir(parents=True, mode=0o700, exist_ok=True)
        self.path = directory/'experience.json'
        self.lock = threading.RLock()
        try:
            self.data = json.loads(self.path.read_text()) if self.path.exists() else {
                'cycles': 0, 'history': [], 'activities': [],
            }
            if (not isinstance(self.data['cycles'], int)
                    or not isinstance(self.data['history'], list)
                    or not isinstance(self.data['activities'], list)):
                raise ValueError('Invalid resident experience')
        except (OSError, ValueError, KeyError, TypeError):
            raise RuntimeError('Resident experience could not be read; inspect the memory directory') from None

    def _save(self):
        descriptor, temporary = tempfile.mkstemp(prefix='.experience-', dir=self.path.parent)
        try:
            with os.fdopen(descriptor, 'w') as output:
                json.dump(self.data, output, ensure_ascii=False)
            os.replace(temporary, self.path)
        finally:
            Path(temporary).unlink(missing_ok=True)

    def begin(self):
        with self.lock:
            self.data['cycles'] += 1
            self._save()
            return self.data['cycles']

    def pending(self, name, arguments):
        with self.lock:
            identifier = uuid.uuid4().hex
            self.data['activities'].append({
                'id': identifier, 'time': datetime.now(timezone.utc).isoformat(),
                'tool': name, 'arguments': bounded(arguments), 'status': 'pending',
            })
            self.data['activities'] = self.data['activities'][-40:]
            self._save()
            return identifier

    def finish(self, identifier, status, result):
        with self.lock:
            activity = next(item for item in self.data['activities'] if item['id'] == identifier)
            activity.update(status=status, observation=bounded(result))
            self._save()

    def complete(self, messages):
        with self.lock:
            self.data['history'].append(messages)
            # Trim whole moments to avoid orphaned tool replies or tool requests.
            while len(self.data['history']) > 6 or len(json.dumps(self.data['history'])) > 60000:
                self.data['history'].pop(0)
            self._save()

    def recent(self):
        return self.data['activities'][-6:]
