"""Shared DNS models."""

from typing import Literal

from pydantic import BaseModel, ConfigDict

DNSRecordType = Literal["A", "AAAA", "CNAME", "MX", "NS", "PTR", "SOA", "TXT"]

class ToolArguments(BaseModel):
    """Base model for strict DNS tool argument validation."""

    model_config = ConfigDict(extra="forbid")


class DNSRecord(BaseModel):
    """A resource record parsed from a section of regular dig output."""

    name: str
    ttl: int
    record_class: str
    record_type: str
    value: str
