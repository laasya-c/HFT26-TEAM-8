"""Database Declarative Base and Custom Portable Types.

Architecture standards:
1. Portable types between SQLite (local development) and PostgreSQL (production).
2. Dialect-aware JSONB on PostgreSQL, falling back to standard JSON on SQLite.
3. Strict UTC datetime normalization: guarantees timezone-awareness and prevents naive timestamp corruption.
4. Unknown timestamps remain NULL per scientific integrity guidelines.
"""
from datetime import datetime, timezone
from typing import Any, Optional

try:
    from sqlalchemy import DateTime, JSON, TypeDecorator
    from sqlalchemy.dialects.postgresql import JSONB
    from sqlalchemy.orm import DeclarativeBase
    HAS_SQLALCHEMY = True
except ImportError:
    HAS_SQLALCHEMY = False
    DeclarativeBase = object  # type: ignore[misc,assignment]


if HAS_SQLALCHEMY:
    class Base(DeclarativeBase):
        """Root declarative base for all WILDSCOPE SQLAlchemy ORM models."""
        pass

    class UTCDatetime(TypeDecorator):
        """Custom SQLAlchemy type decorator for timezone-aware UTC timestamps.
        
        - Stored as native TIMESTAMP WITH TIME ZONE on PostgreSQL.
        - Stored as ISO-8601 UTC string on SQLite.
        - Guarantees that returned Python datetimes have tzinfo=timezone.utc.
        - Scientific Rule: NULL remains NULL. Never invent capture times.
        """
        impl = DateTime(timezone=True)
        cache_ok = True

        def process_bind_param(self, value: Optional[datetime], dialect: Any) -> Optional[datetime]:
            if value is None:
                return None
            if not isinstance(value, datetime):
                raise ValueError(f"Expected datetime object, got: {type(value)}")
            if value.tzinfo is None or value.tzinfo.utcoffset(value) is None:
                raise ValueError("Cannot persist naive datetime. Timestamps must be timezone-aware.")
            return value.astimezone(timezone.utc)

        def process_result_value(self, value: Optional[datetime], dialect: Any) -> Optional[datetime]:
            if value is None:
                return None
            if value.tzinfo is None:
                return value.replace(tzinfo=timezone.utc)
            return value.astimezone(timezone.utc)

    # Dialect-aware JSON: Uses binary JSONB on PostgreSQL for indexability; standard JSON on SQLite
    PortableJSON = JSON().with_variant(JSONB(), "postgresql")

else:
    class Base:  # type: ignore[no-redef]
        pass

    class UTCDatetime:  # type: ignore[no-redef]
        pass

    PortableJSON = None  # type: ignore[assignment]
