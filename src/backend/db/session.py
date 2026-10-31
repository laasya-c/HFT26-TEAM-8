"""Database Engine and Session Configuration.

Configures:
- SQLite WAL (Write-Ahead Logging) mode for concurrent reader/writer access.
- PRAGMA busy_timeout = 5000 (5 seconds) to mitigate transient database locks.
- PRAGMA foreign_keys = ON to enforce relational integrity in SQLite.
- Synchronous SQLAlchemy 2.0 session generator for FastAPI dependencies.
"""
from typing import Any, Generator
from src.backend.config import settings

try:
    from sqlalchemy import create_engine, event
    from sqlalchemy.engine import Engine
    from sqlalchemy.orm import sessionmaker, Session
    HAS_SQLALCHEMY = True
except ImportError:
    HAS_SQLALCHEMY = False
    Engine = object  # type: ignore[misc,assignment]


if HAS_SQLALCHEMY:
    connect_args = {}
    if settings.DATABASE_URL.startswith("sqlite"):
        connect_args = {"check_same_thread": False}

    engine = create_engine(
        settings.DATABASE_URL,
        connect_args=connect_args,
        echo=settings.DEBUG,
    )

    # Configure SQLite PRAGMAs on every connection
    @event.listens_for(Engine, "connect")
    def set_sqlite_pragmas(dbapi_connection: Any, connection_record: Any) -> None:
        if settings.DATABASE_URL.startswith("sqlite"):
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA journal_mode=WAL;")
            cursor.execute("PRAGMA busy_timeout=5000;")
            cursor.execute("PRAGMA foreign_keys=ON;")
            cursor.close()

    SessionLocal = sessionmaker(
        autocommit=False,
        autoflush=False,
        bind=engine,
        expire_on_commit=False,
    )

    def get_db() -> Generator[Session, None, None]:
        """FastAPI dependency yielding a clean database session per request.

        Guarantees explicit rollback on unhandled exceptions and safe session closure.
        """
        db = SessionLocal()
        try:
            yield db
        except Exception:
            try:
                db.rollback()
            except Exception:
                pass
            raise
        finally:
            try:
                db.close()
            except Exception:
                pass

else:
    engine = None  # type: ignore[assignment]
    SessionLocal = None  # type: ignore[assignment]

    def get_db():  # type: ignore[no-redef]
        raise RuntimeError("SQLAlchemy is not installed. Please run: pip install -r requirements.txt")
