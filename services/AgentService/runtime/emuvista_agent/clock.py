"""Internal workflow client for AgentService's shared ClockServer."""

from datetime import datetime

from .http import request


class ClockClient:
    def __init__(self, url):
        self._url = url

    def now(self):
        """Read the shared clock as an aware UTC datetime."""
        return datetime.fromisoformat(request({'url': self._url}, '/time')['time'])
