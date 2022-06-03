import asyncio
from alembic.config import main as alembic_main
import copy
import os
import pytest
import requests
from starlette.config import environ
from starlette.testclient import TestClient
from unittest.mock import AsyncMock, MagicMock, patch

from requestor.arborist import get_auto_policy_id_for_resource_path


# Set REQUESTOR_CONFIG_PATH *before* loading the configuration
CURRENT_DIR = os.path.dirname(os.path.realpath(__file__))
environ["REQUESTOR_CONFIG_PATH"] = os.path.join(
    CURRENT_DIR, "test-requestor-config.yaml"
)
from requestor.app import app_init
from requestor.config import config


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


@pytest.fixture(scope="function")
def list_policies_patcher(test_data):
    """
    This fixture patches the list_policies method with a mock implementation based on
    the test_data provided which is a dictionary consisting of resource_path(s) and
    policy_id wherever appropriate
    """
    resource_paths = (
        test_data["resource_paths"]
        if "resource_paths" in test_data
        else [test_data["resource_path"]]
    )
    expanded_permissions = (
        test_data["permissions"]
        if "permissions" in test_data
        else [
            {
                "id": permission,
                "description": "",
                "action": {
                    "service": "*",
                    "method": permission,
                },
            }
            for permission in ["reader", "storage_reader"]
        ]
    )
    policy_id = (
        test_data["policy_id"]
        if "policy_id" in test_data
        else get_auto_policy_id_for_resource_path(resource_paths[0])
    )

    future = asyncio.Future()
    future.set_result(
        {
            "policies": [
                {
                    "id": policy_id,
                    "resource_paths": resource_paths,
                    "roles": [
                        {
                            "id": "reader",
                            "description": "",
                            "permissions": expanded_permissions,
                        }
                    ],
                },
            ]
        }
    )

    list_policies_mock = MagicMock()
    list_policies_mock.return_value = future
    policy_expand_patch = patch(
        "requestor.routes.query.arborist.list_policies", list_policies_mock
    )
    policy_expand_patch.start()

    yield

    policy_expand_patch.stop()


@pytest.fixture(autouse=True, scope="function")
def access_token_patcher(client, request):
    async def get_access_token(*args, **kwargs):
        return {"sub": "1", "context": {"user": {"name": "requestor_user"}}}

    access_token_mock = MagicMock()
    access_token_mock.return_value = get_access_token

    access_token_patch = patch("requestor.auth.access_token", access_token_mock)
    access_token_patch.start()

    yield access_token_mock

    access_token_patch.stop()


@pytest.fixture(autouse=True)
def clean_db():
    """
    Before each test, delete all existing requests from the DB
    """
    # The code below doesn't work because of this issue
    # https://github.com/encode/starlette/issues/440, so for now reset
    # using alembic.
    # pytest-asyncio = "^0.14.0"
    # from requestor.models import Request as RequestModel
    # @pytest.mark.asyncio
    # async def clean_db():
    #     await RequestModel.delete.gino.all()
    #     yield

    alembic_main(["--raiseerr", "downgrade", "base"])
    alembic_main(["--raiseerr", "upgrade", "head"])

    yield


@pytest.fixture(scope="function")
def mock_arborist_requests(request):
    """
    This fixture returns a function which you call to mock the call to
    arborist client's auth_request method.
    By default, it returns a 200 response. If parameter "authorized" is set
    to False, it raises a 401 error.
    """

    def do_patch(authorized=True):
        # URLs to reponses: { URL: { METHOD: ( content, code ) } }
        urls_to_responses = {
            "http://arborist-service/auth/request": {
                "POST": ({"auth": authorized}, 200)
            },
            "http://arborist-service/user/requestor_user": {
                "GET": (
                    {
                        "name": "pauline",
                        "groups": [],
                        "policies": [{"policy": "test-policy"}],
                    },
                    200 if authorized else 403,
                )
            },
            "http://arborist-service/user/requestor_user/policy": {
                "POST": ({}, 204 if authorized else 403)
            },
            "http://arborist-service/user/requestor_user/policy/test-policy": {
                "DELETE": ({}, 204 if authorized else 403)
            },
            "http://arborist-service/policy/?expand": {
                "GET": (
                    {
                        "policies": [
                            {
                                "id": "test-policy",
                                "resource_paths": ["/my/resource"],
                                "roles": [
                                    {
                                        "id": "reader",
                                        "description": "",
                                        "permissions": [
                                            {
                                                "id": "read",
                                                "description": "",
                                                "action": {
                                                    "service": "*",
                                                    "method": "read",
                                                },
                                            }
                                        ],
                                    }
                                ],
                            },
                            {
                                "id": "test-policy-with-redirect",
                                "resource_paths": ["/resource-with-redirect/resource"],
                                "roles": [],
                            },
                            {
                                "id": "test-policy-i-cant-access",
                                "resource_paths": ["something-i-cant-access"],
                                "roles": [],
                            },
                            {
                                "id": "my.resource_reader",
                                "resource_paths": ["/my/resource"],
                                "roles": [],
                            },
                            {
                                "id": "test-existing-policy",
                                "resource_paths": [],
                                "roles": [],
                            },
                            {
                                "id": "test-existing-policy-2",
                                "resource_paths": [],
                                "roles": [],
                            },
                        ]
                    },
                    204 if authorized else 403,
                )
            },
            "http://arborist-service/auth/mapping": {
                "POST": (
                    {"/": [{"service": "*", "method": "*"}]} if authorized else {},
                    200,
                )
            },
        }

        def make_mock_response(method, url, *args, **kwargs):
            method = method.upper()
            mocked_response = MagicMock(requests.Response)

            if url not in urls_to_responses:
                mocked_response.status_code = 404
                mocked_response.text = "NOT FOUND"
            elif method not in urls_to_responses[url]:
                mocked_response.status_code = 405
                mocked_response.text = "METHOD NOT ALLOWED"
            else:
                content, code = urls_to_responses[url][method]
                mocked_response.status_code = code
                if isinstance(content, dict):
                    mocked_response.json.return_value = content
                else:
                    mocked_response.text = content

            return mocked_response

        mocked_method = AsyncMock(side_effect=make_mock_response)
        patch_method = patch(
            "gen3authz.client.arborist.async_client.httpx.AsyncClient.request",
            mocked_method,
        )

        patch_method.start()
        request.addfinalizer(patch_method.stop)

    return do_patch


@pytest.fixture(autouse=True)
def arborist_authorized(mock_arborist_requests):
    """
    By default, mocked arborist calls return Authorized.
    To mock an unauthorized response, use fixture
    "mock_arborist_requests(authorized=False)" in the test itself
    """
    mock_arborist_requests()
