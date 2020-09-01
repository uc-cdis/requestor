from alembic.config import main as alembic_main
import copy
import importlib
import os
import pytest
import requests
from starlette.config import environ
from starlette.testclient import TestClient
from unittest.mock import MagicMock, patch


# Set REQUESTOR_CONFIG_PATH *before* loading the configuration
CURRENT_DIR = os.path.dirname(os.path.realpath(__file__))
environ["REQUESTOR_CONFIG_PATH"] = os.path.join(
    CURRENT_DIR, "test-requestor-config.yaml"
)
from requestor.config import config
from requestor.app import app_init


@pytest.fixture(scope="session")
def app():
    app = app_init()
    return app


@pytest.fixture(autouse=True, scope="session")
def setup_test_database():
    """
    At teardown, restore original config and reset test DB.
    """
    saved_config = copy.deepcopy(config._configs)

    alembic_main(["--raiseerr", "upgrade", "head"])

    yield

    # restore old configs
    config.update(saved_config)

    if not config["TEST_KEEP_DB"]:
        alembic_main(["--raiseerr", "downgrade", "base"])


@pytest.fixture()
def client():
    with TestClient(app_init()) as client:
        yield client


@pytest.fixture(autouse=True, scope="function")
def access_token_patcher(client, request):
    async def get_access_token(*args, **kwargs):
        return {"sub": "1", "context": {"user": {"name": "requestor-user"}}}

    access_token_mock = MagicMock()
    access_token_mock.return_value = get_access_token

    access_token_patch = patch("requestor.auth.access_token", access_token_mock)
    access_token_patch.start()

    yield access_token_mock

    access_token_patch.stop()


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
