"""Validate browser tool actions and parameters."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class BrowserArguments(BaseModel):
    model_config = ConfigDict(extra="forbid")
    action: Literal[
        "observe",
        "open",
        "click",
        "fill",
        "select",
        "press",
        "check",
        "scroll",
        "back",
        "switch_tab",
    ]
    url: str | None = Field(default=None, max_length=2048)
    ref: str | None = Field(default=None, max_length=100)
    value: str | None = Field(default=None, max_length=8000)
    checked: bool = True
    delta: int = Field(default=600, ge=-2000, le=2000)
    tab: int = Field(default=0, ge=0, le=30)
