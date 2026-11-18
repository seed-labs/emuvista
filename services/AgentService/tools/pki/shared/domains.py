"""DNS name helpers shared by PKI tools."""

import re


def normalize_domain(value: str) -> str:
    """Convert a DNS name to lowercase IDNA ASCII and validate its labels."""

    value = value.removesuffix(".").encode("idna").decode("ascii").lower()
    if len(value) > 253 or any(
        not re.fullmatch(r"[a-z0-9_](?:[a-z0-9_-]{0,61}[a-z0-9_])?", label)
        for label in value.split(".")
    ):
        raise ValueError("Invalid DNS name")
    return value
