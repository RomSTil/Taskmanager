from collections.abc import Generator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.config import get_settings
from app.database import Base, get_session
from app.main import create_app


engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
TestingSession = sessionmaker(bind=engine, expire_on_commit=False)
Base.metadata.create_all(engine)


def override_session() -> Generator[Session, None, None]:
    with TestingSession() as session:
        yield session


@pytest.fixture
def db_session() -> Generator[Session, None, None]:
    with TestingSession() as session:
        yield session


@pytest.fixture(autouse=True)
def clean_database(tmp_path: Path) -> Generator[None, None, None]:
    get_settings().vault_path = tmp_path / "vault"
    with TestingSession() as session:
        for table in reversed(Base.metadata.sorted_tables):
            session.execute(table.delete())
        session.commit()
    yield


@pytest.fixture
def client() -> Generator[TestClient, None, None]:
    app = create_app(initialize_database=False)
    app.dependency_overrides[get_session] = override_session
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def auth_headers(client: TestClient) -> dict[str, str]:
    response = client.post(
        "/api/v1/auth/setup",
        json={"username": "owner", "password": "correct horse battery staple"},
    )
    assert response.status_code == 201, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}
