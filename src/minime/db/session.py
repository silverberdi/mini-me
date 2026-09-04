"""Database engine and session management for mini me."""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Generator

from sqlalchemy import Engine, create_engine, inspect, text
from sqlalchemy.orm import Session, sessionmaker

from minime.config import load_config
from minime.logging import get_logger

logger = get_logger("db.session")


@dataclass(frozen=True)
class SchemaInvariantResult:
    valid: bool
    revision: str | None = None
    missing_tables: tuple[str, ...] = field(default_factory=tuple)
    missing_columns: dict[str, tuple[str, ...]] = field(default_factory=dict)
    reason: str | None = None


def verify_physical_schema_invariants(engine: Engine) -> SchemaInvariantResult:
    """Verify the physical PostgreSQL schema against SQLAlchemy metadata.

    This is inspection only: it never runs DDL or repairs a database.
    """
    from minime.db.models import Base

    expected_revision = "019_work_intake_and_backlog_items"
    inspector = inspect(engine)

    tables = set(inspector.get_table_names())
    missing_tables = sorted(set(Base.metadata.tables) - tables)
    missing_columns: dict[str, tuple[str, ...]] = {}
    for table_name, table in Base.metadata.tables.items():
        if table_name in tables:
            actual = {column["name"] for column in inspector.get_columns(table_name)}
            missing = tuple(sorted(set(table.columns.keys()) - actual))
            if missing:
                missing_columns[table_name] = missing
    revision = None
    if "alembic_version" in tables:
        with engine.connect() as connection:
            revision = connection.execute(text("SELECT version_num FROM alembic_version")).scalar()
    reason = None
    if revision != expected_revision:
        reason = f"Expected Alembic head {expected_revision}, found {revision or 'none'}."
    elif missing_tables or missing_columns:
        reason = "Physical schema is missing required tables or columns."
    return SchemaInvariantResult(
        not (reason or missing_tables or missing_columns),
        revision,
        tuple(missing_tables),
        missing_columns,
        reason,
    )


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
