import importlib
import pytest
from starlette.testclient import TestClient


from requestor.app import app_init


@pytest.fixture(scope="session")
def app():
    # load configuration
    # service_app.config.from_object('requestor.test_settings')
    app = app_init()
    return app


@pytest.fixture()
def client():
    from requestor import config

    importlib.reload(config)

    with TestClient(app_init()) as client:
        yield client
