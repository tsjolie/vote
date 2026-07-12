"""Portable column types.

Postgres (production) uses native UUID and JSONB; SQLite (used only by the test
suite) falls back to CHAR(36) and generic JSON. Production DDL is authored
explicitly in the Alembic migration, so these fallbacks never touch Postgres.
"""

from __future__ import annotations

from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.types import CHAR, JSON, TypeDecorator


class GUID(TypeDecorator):
    impl = CHAR
    cache_ok = True

    def load_dialect_impl(self, dialect):
        if dialect.name == "postgresql":
            return dialect.type_descriptor(UUID(as_uuid=False))
        return dialect.type_descriptor(CHAR(36))

    def process_bind_param(self, value, dialect):
        return None if value is None else str(value)


# JSON on SQLite, JSONB on Postgres.
JSONType = JSON().with_variant(JSONB(), "postgresql")
