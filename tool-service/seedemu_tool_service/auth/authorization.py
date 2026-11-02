"""Fail-closed authorization shared by REST, MCP and direct registry calls."""

import time
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel, ValidationError

from seedemu_tool_service.auth.models import (
    AccessPolicy,
    AgentIdentity,
    normalize_domain,
    within,
)
from seedemu_tool_service.auth.policies import PROFILE_TOOLS, ROLE_TOOLS


class AccessDenied(PermissionError):
    """A valid identity is not authorized for this operation."""


@dataclass(frozen=True)
class AccessContext:
    identity: AgentIdentity
    policy: AccessPolicy

    def can_call(self, tool: str) -> bool:
        if not self.identity.enabled or tool not in ROLE_TOOLS[self.identity.role]:
            return False
        if tool in PROFILE_TOOLS:
            return any(
                p.profile_id in self.identity.profiles
                and p.tool == tool
                and p.world_id == self.identity.world_id
                for p in self.policy.profiles
            )
        return True

    def _sources(self, arguments: dict[str, Any]) -> dict[str, Any]:
        result = dict(arguments)
        for field in ("source", "verification_source"):
            if field not in result:
                continue
            node = next(
                (
                    n
                    for n in self.policy.nodes
                    if n.world_id == self.identity.world_id
                    and n.node_id in self.identity.nodes
                    and result[field] in (n.node_id, n.container_id)
                ),
                None,
            )
            if node is None:
                raise AccessDenied("Source node is outside the authorized scope")
            result[field] = node.container_id
        if "ca_service_source" in result:
            ca_node = next(
                (
                    n
                    for n in self.policy.nodes
                    if n.world_id == self.identity.world_id
                    and n.node_id in self.policy.ca_service_nodes
                    and result["ca_service_source"] in (n.node_id, n.container_id)
                ),
                None,
            )
            if ca_node is None:
                raise AccessDenied("CA Service source is outside the authorized world")
            result["ca_service_source"] = ca_node.container_id
        return result

    def _owned_domain(self, name: str, zone: str | None = None) -> None:
        candidates = [
            d
            for d in self.policy.domains
            if d.world_id == self.identity.world_id and within(name, d.name)
        ]
        # A child registration shadows its parent, including when expired or inactive.
        resource = max(candidates, key=lambda d: len(d.name), default=None)
        if (
            resource is None
            or resource.owner_id != self.identity.agent_id
            or not resource.active
            or (resource.expires_at is not None and resource.expires_at <= time.time())
            or (zone is not None and zone != resource.zone)
        ):
            raise AccessDenied("Domain is outside the current ownership scope")

    def authorize(
        self,
        tool: str,
        arguments: dict[str, Any],
        arguments_model: type[BaseModel],
    ) -> dict[str, Any]:
        if not self.can_call(tool):
            raise AccessDenied("Tool is not authorized")
        result = self._sources(arguments)
        if tool == "dns.update":
            result["zone"] = normalize_domain(result["zone"])
            result["name"] = normalize_domain(result["name"])
            self._owned_domain(result["name"], result["zone"])
        if tool in PROFILE_TOOLS:
            matched = False
            for profile in self.policy.profiles:
                if (
                    profile.profile_id not in self.identity.profiles
                    or profile.tool != tool
                    or profile.world_id != self.identity.world_id
                ):
                    continue
                try:
                    expected = arguments_model.model_validate(profile.arguments).model_dump()
                    expected = self._sources(expected)
                except (ValidationError, AccessDenied):
                    continue
                if result == expected:
                    matched = True
                    break
            if not matched:
                raise AccessDenied("Arguments do not match an authorized operation profile")
            if tool == "pki.deploy_acme_certificate_to_nginx":
                self._owned_domain(normalize_domain(result["server_name"]))
        return result
