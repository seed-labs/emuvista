"""Fixed-token authentication; reload trusted policy for every request."""

import hashlib
import hmac
import os
from pathlib import Path

from pydantic import ValidationError

from seedemu_tool_service.auth.authorization import AccessContext
from seedemu_tool_service.auth.models import AccessPolicy


class AuthenticationError(PermissionError):
    """Missing, malformed, revoked or unknown credentials."""


class PolicyUnavailable(RuntimeError):
    """Policy is missing or invalid. Never fall back to an older policy."""


class TokenAuthenticator:
    def __init__(self, policy_path: str | Path | None = None) -> None:
        self.policy_path = policy_path

    def authenticate(self, token: str) -> AccessContext:
        if not token or any(c.isspace() for c in token):
            raise AuthenticationError("Invalid bearer token")
        path = self.policy_path or os.environ.get("SEEDEMU_AUTH_POLICY")
        if not path:
            raise PolicyUnavailable("Access policy is not configured")
        try:
            policy = AccessPolicy.model_validate_json(Path(path).read_bytes())
        except (OSError, ValidationError) as error:
            raise PolicyUnavailable("Access policy is unavailable") from error
        digest = hashlib.sha256(token.encode()).hexdigest()
        for identity in policy.agents:
            if hmac.compare_digest(identity.token_sha256, digest) and identity.enabled:
                return AccessContext(identity, policy)
        raise AuthenticationError("Invalid bearer token")

    def from_header(self, header: str | None) -> AccessContext:
        parts = (header or "").split()
        if len(parts) != 2 or parts[0].lower() != "bearer":
            raise AuthenticationError("Bearer token required")
        return self.authenticate(parts[1])
