from alembic.config import main as alembic_main
import importlib
import pytest
from starlette.config import environ
from starlette.testclient import TestClient

environ["TESTING"] = "TRUE"
from requestor import config
from requestor.app import app_init


@pytest.fixture(scope="session")
def app():
    app = app_init()
    return app


@pytest.fixture(autouse=True, scope="session")
def setup_test_database():
    from requestor import config

    alembic_main(["--raiseerr", "upgrade", "head"])

    yield

    importlib.reload(config)
    if not config.TEST_KEEP_DB:
        alembic_main(["--raiseerr", "downgrade", "base"])


@pytest.fixture()
def client():
    from requestor import config

    importlib.reload(config)

    with TestClient(app_init()) as client:
        yield client
