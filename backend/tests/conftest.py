import os

import pytest

from app.db import init_db


@pytest.fixture(scope="session", autouse=True)
def prepare_database() -> None:
    os.environ["DEMO_SEED"] = "true"
    init_db()
