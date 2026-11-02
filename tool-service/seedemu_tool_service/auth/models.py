"""Trusted identity and resource records, maintained by the experiment operator."""

import re
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from seedemu_tool_service.auth.policies import PROFILE_TOOLS


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class AgentIdentity(StrictModel):
    agent_id: str = Field(min_length=1)
    world_id: str = Field(min_length=1)
    role: Literal["observer", "member", "dns_admin", "pki_operator", "ca_operator"]
    token_sha256: str = Field(pattern=r"^[0-9a-f]{64}$", repr=False)
    nodes: tuple[str, ...] = ()
    profiles: tuple[str, ...] = ()
    enabled: bool = True


class NodeResource(StrictModel):
    node_id: str = Field(min_length=1)
    world_id: str = Field(min_length=1)
    # Pin to an immutable Docker identity; never resolve an untrusted name/short ID.
    container_id: str = Field(pattern=r"^[0-9a-f]{64}$")


def normalize_domain(value: str) -> str:
    value = value.removesuffix(".").encode("idna").decode("ascii").lower()
    if len(value) > 253 or any(
        not re.fullmatch(r"[a-z0-9_](?:[a-z0-9_-]{0,61}[a-z0-9_])?", label)
        for label in value.split(".")
    ):
        raise ValueError("Invalid DNS name")
    return value


def within(name: str, parent: str) -> bool:
    return name == parent or name.endswith("." + parent)


class DomainResource(StrictModel):
    world_id: str = Field(min_length=1)
    name: str
    zone: str
    owner_id: str = Field(min_length=1)
    expires_at: float | None = Field(default=None, allow_inf_nan=False)
    active: bool = True

    @field_validator("name", "zone")
    @classmethod
    def canonical_domain(cls, value: str) -> str:
        return normalize_domain(value)

    @model_validator(mode="after")
    def check_zone(self) -> "DomainResource":
        if not within(self.name, self.zone):
            raise ValueError("Domain must belong to its configured DNS zone")
        return self


class OperationProfile(StrictModel):
    profile_id: str = Field(min_length=1)
    world_id: str = Field(min_length=1)
    tool: str
    # Exact arguments, with omitted defaults expanded by the tool's argument model.
    arguments: dict[str, Any]

    @field_validator("tool")
    @classmethod
    def reviewed_tool(cls, value: str) -> str:
        if value not in PROFILE_TOOLS:
            raise ValueError("Tool does not support operation profiles")
        return value


class AccessPolicy(StrictModel):
    agents: tuple[AgentIdentity, ...] = ()
    nodes: tuple[NodeResource, ...] = ()
    ca_service_nodes: tuple[str, ...] = ()
    domains: tuple[DomainResource, ...] = ()
    profiles: tuple[OperationProfile, ...] = ()

    @model_validator(mode="after")
    def validate_references(self) -> "AccessPolicy":
        for values in (
            [a.agent_id for a in self.agents],
            [a.token_sha256 for a in self.agents],
            [n.node_id for n in self.nodes],
            [n.container_id for n in self.nodes],
            list(self.ca_service_nodes),
            [p.profile_id for p in self.profiles],
            [(d.world_id, d.name) for d in self.domains],
        ):
            if len(values) != len(set(values)):
                raise ValueError("Duplicate identity or resource in access policy")
        nodes = {n.node_id: n for n in self.nodes}
        if any(node_id not in nodes for node_id in self.ca_service_nodes):
            raise ValueError("Unknown CA Service node")
        profiles = {p.profile_id: p for p in self.profiles}
        agents = {a.agent_id: a for a in self.agents}
        for agent in self.agents:
            for node in agent.nodes:
                if node not in nodes or nodes[node].world_id != agent.world_id:
                    raise ValueError("Unknown or cross-world node assignment")
            for profile in agent.profiles:
                if profile not in profiles or profiles[profile].world_id != agent.world_id:
                    raise ValueError("Unknown or cross-world profile assignment")
        for domain in self.domains:
            owner = agents.get(domain.owner_id)
            if owner is None or owner.world_id != domain.world_id:
                raise ValueError("Unknown or cross-world domain owner")
        return self
