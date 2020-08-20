from alembic.config import main as alembic_main
import importlib
import pytest
import requests
from starlette.config import environ
from starlette.testclient import TestClient
from unittest.mock import MagicMock, patch

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


@pytest.fixture(scope="function")
def mock_arborist_requests(request):
    def do_patch():
        def make_mock_response(*args, **kwargs):
            mocked_response = MagicMock(requests.Response)
            mocked_response.status_code = 200
            mocked_response.json.return_value = {}
            return mocked_response

        mocked_method = MagicMock(side_effect=make_mock_response)
        patch_method = patch(
            "gen3authz.client.arborist.client.httpx.Client.request", mocked_method
        )

        patch_method.start()
        request.addfinalizer(patch_method.stop)

    return do_patch


@pytest.fixture(autouse=True)
def arborist_authorized(mock_arborist_requests):
    """
    By default, mock all arborist calls.
    """
    mock_arborist_requests()
