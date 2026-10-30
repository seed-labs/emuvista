"""Restrict query parameters; do not accept arbitrary dig options or commands."""

import ipaddress
import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class LookupArguments(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=253)
    record_type: Literal['A', 'AAAA', 'NS', 'CNAME', 'MX', 'TXT', 'SOA', 'PTR', 'CAA'] = 'A'
    server: str | None = None
    recursive: bool = True
    tcp: bool = False

    @field_validator('name')
    @classmethod
    def valid_name(cls, value):
        if value == '.':
            return value
        name = value.rstrip('.').encode('idna').decode('ascii')
        if len(name) > 253 or any(
            not re.fullmatch(r'[A-Za-z0-9_](?:[A-Za-z0-9_-]{0,61}[A-Za-z0-9_])?', label)
            for label in name.split('.')
        ):
            raise ValueError('请输入域名；PTR 查询请提供反向查询名称')
        return name + '.'

    @field_validator('server')
    @classmethod
    def valid_server(cls, value):
        return str(ipaddress.ip_address(value)) if value is not None else None
