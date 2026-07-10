import pytest

from app.db import init_db


@pytest.fixture(scope="session", autouse=True)
def prepare_database() -> None:
    init_db()
