"""PostgreSQL connection and schema initialization."""

from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

import psycopg
from psycopg.rows import dict_row

from .settings import settings


SCHEMA_PATH = Path(__file__).with_name("schema.sql")


@contextmanager
def connection() -> Iterator[psycopg.Connection]:
    with psycopg.connect(settings.database_url, row_factory=dict_row) as conn:
        yield conn


def initialize_schema() -> None:
    sql = SCHEMA_PATH.read_text(encoding="utf-8")
    with connection() as conn:
        for statement in sql.split(";"):
            if statement.strip():
                conn.execute(statement)
