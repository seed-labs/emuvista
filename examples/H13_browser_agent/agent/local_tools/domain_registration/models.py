"""Arguments for registrar discovery."""

from pydantic import BaseModel, ConfigDict, Field, field_validator


class RegistrarFindArguments(BaseModel):
    model_config = ConfigDict(extra="forbid")
    filter: dict[str, str] = Field(default_factory=dict)

    @field_validator("filter")
    @classmethod
    def validate_filter(cls, value):
        if value.keys() - {"provider", "registrar_url"}:
            raise ValueError("Supported filters: provider, registrar_url")
        return value


class HostedDNSFindArguments(BaseModel):
    """The static hosted DNS directory supports filtering by provider or website URL only."""
    model_config = ConfigDict(extra="forbid")
    filter: dict[str, str] = Field(default_factory=dict)

    @field_validator("filter")
    @classmethod
    def validate_filter(cls, value):
        if value.keys() - {"provider", "web_url"}:
            raise ValueError("Supported filters: provider, web_url")
        return value
