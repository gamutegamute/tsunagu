import os

import pytest
from alembic import command
from alembic.config import Config

from app.db import seed_demo_data


@pytest.fixture(scope="session", autouse=True)
def prepare_database() -> None:
    os.environ["APP_ENV"] = "test"
    os.environ["AUTH_MODE"] = "dev"
    os.environ["GATEWAY_API_KEY"] = "test-gateway-key"
    os.environ["DEMO_SEED"] = "true"
    command.upgrade(Config("alembic.ini"), "head")
    seed_demo_data()
