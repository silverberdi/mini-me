"""Persistence and migration contracts for non-secret project DB profiles."""

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from minime.db.models import Base
from minime.db.repository import PostgresProjectRepository
from minime.domain.models import Project, ProjectTestDatabase


def _project(project_id: str, test_database=None) -> Project:
    return Project(
        project_id=project_id,
        display_name=project_id,
        repository=f"silverberdi/{project_id}",
        test_database=test_database,
    )


def test_project_test_database_profile_round_trips_without_secrets():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    profile = ProjectTestDatabase(
        host="db.example.test",
        port=5432,
        database_name="boxio_test",
        production_database_names=["boxio_prod"],
        url_env="BOXIO_TEST_DATABASE_URL",
    )

    with Session(engine) as session:
        repository = PostgresProjectRepository(session)
        repository.save(_project("boxio", profile))
        session.commit()

        loaded = repository.get_by_id("boxio")
        assert loaded is not None
        assert loaded.test_database == profile
        assert "password" not in loaded.model_dump(mode="json")["test_database"]
        assert "postgresql://" not in repr(loaded.model_dump(mode="json"))

        repository.save(_project("legacy", None))
        session.commit()
        legacy = repository.get_by_id("legacy")
        assert legacy is not None
        assert legacy.test_database is None

