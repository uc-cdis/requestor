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


# unused for now
# @pytest.fixture(scope="function")
# def mock_arborist_requests(request):
#     def do_patch(urls_to_responses=None):
#         urls_to_responses = urls_to_responses or {}

#         def make_mock_response(method, url, *args, **kwargs):
#             method = method.upper()
#             mocked_response = MagicMock(requests.Response)

#             if url not in urls_to_responses:
#                 mocked_response.status_code = 404
#                 mocked_response.text = "NOT FOUND"
#             elif method not in urls_to_responses[url]:
#                 mocked_response.status_code = 405
#                 mocked_response.text = "METHOD NOT ALLOWED"
#             else:
#                 content, code = urls_to_responses[url][method]
#                 mocked_response.status_code = code
#                 if isinstance(content, dict):
#                     mocked_response.json.return_value = content
#                 else:
#                     mocked_response.text = content

#             return mocked_response

#         mocked_method = MagicMock(side_effect=make_mock_response)
#         patch_method = patch(
#             "gen3authz.client.arborist.client.httpx.Client.request", mocked_method
#         )

#         patch_method.start()
#         request.addfinalizer(patch_method.stop)

#     return do_patch
