"""Database engine and session management for mini me."""

from __future__ import annotations

from contextlib import contextmanager
from typing import Generator

from sqlalchemy import Engine, create_engine, text
from sqlalchemy.orm import Session, sessionmaker

from minime.config import load_config
from minime.logging import get_logger

logger = get_logger("db.session")


def validate_postgres_url(url: str) -> None:
    """Validate that the URL strictly uses the PostgreSQL dialect."""
    if not url.startswith(("postgresql://", "postgresql+")):
        raise ValueError(
            f"Invalid database dialect for URL '{url}'. "
            f"mini me exclusively supports PostgreSQL for operational persistence."
        )


def create_db_engine(database_url: str | None = None, echo: bool = False) -> Engine:
    """Create a SQLAlchemy engine configured for PostgreSQL."""
    if not database_url:
        config = load_config()
        database_url = config.database.resolve_url()

    validate_postgres_url(database_url)

    # Convert standard postgresql:// to postgresql+psycopg:// if no driver is specified
    if database_url.startswith("postgresql://"):
        database_url = database_url.replace("postgresql://", "postgresql+psycopg://", 1)

    return create_engine(
        database_url,
        echo=echo,
        pool_pre_ping=True,
        pool_size=10,
        max_overflow=20,
    )


class DatabaseSessionManager:
    """Manages database sessions and engine lifecycle."""

    def __init__(self, database_url: str | None = None):
        self._engine: Engine | None = None
        self._sessionmaker: sessionmaker[Session] | None = None
        self._database_url = database_url

    def initialize(self) -> None:
        if self._engine is None:
            self._engine = create_db_engine(self._database_url)
            self._sessionmaker = sessionmaker(
                bind=self._engine,
                autocommit=False,
                autoflush=False,
                expire_on_commit=False,
            )

    @property
    def engine(self) -> Engine:
        if self._engine is None:
            self.initialize()
        assert self._engine is not None
        return self._engine

    @property
    def sessionmaker(self) -> sessionmaker[Session]:
        if self._sessionmaker is None:
            self.initialize()
        assert self._sessionmaker is not None
        return self._sessionmaker

    @contextmanager
    def session(self) -> Generator[Session, None, None]:
        sess = self.sessionmaker()
        try:
            yield sess
            sess.commit()
        except Exception:
            sess.rollback()
            raise
        finally:
            sess.close()

    def check_health(self) -> tuple[bool, str]:
        """Check PostgreSQL database connectivity."""
        try:
            with self.session() as s:
                result = s.execute(text("SELECT 1")).scalar()
                if result == 1:
                    return True, "PostgreSQL connected and healthy"
                return False, f"Unexpected health check response: {result}"
        except Exception as e:
            return False, f"Database connection error: {e}"

    def close(self) -> None:
        if self._engine is not None:
            self._engine.dispose()
            self._engine = None
            self._sessionmaker = None


# Default global instance
db_manager = DatabaseSessionManager()
