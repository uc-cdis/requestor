import asyncio
from alembic.config import main as alembic_main
import copy
import os
import pytest
import pytest_asyncio
import requests
from sqlalchemy.ext.asyncio import (
    async_sessionmaker,
    create_async_engine,
    # async_scoped_session,
)
from starlette.config import environ
from starlette.testclient import TestClient
from unittest.mock import AsyncMock, MagicMock, patch

# Set REQUESTOR_CONFIG_PATH *before* loading requestor modules
CURRENT_DIR = os.path.dirname(os.path.realpath(__file__))
environ["REQUESTOR_CONFIG_PATH"] = os.path.join(
    CURRENT_DIR, "test-requestor-config.yaml"
)

from requestor.app import app_init
from requestor.arborist import get_auto_policy_id
from requestor.config import config
from requestor.models import Base, get_db_engine_and_sessionmaker, initialize_db


@pytest.fixture(scope="session")
def app():
    app = app_init()
    return app


@pytest_asyncio.fixture(autouse=True, scope="session")
async def setup_test_database():  # TODO rename
    """
    At teardown, restore original config and reset test DB.
    """
    saved_config = copy.deepcopy(config._configs)

    # loop = asyncio.get_running_loop()
    # await loop.run_in_executor(None, alembic_main, ["--raiseerr", "upgrade", "head"])

    yield

    # restore old configs
    config.update(saved_config)

    # if not config["TEST_KEEP_DB"]:
    #     await loop.run_in_executor(
    #         None, alembic_main, ["--raiseerr", "downgrade", "base"]
    #     )


# @pytest_asyncio.fixture(scope="function")
# async def engine():
#     """
#     Non-session scoped engine which recreates the database, yields, then drops the tables
#     """
#     engine = create_async_engine(config["DB_URL"], echo=False, future=True)

#     async with engine.begin() as conn:
#         await conn.run_sync(Base.metadata.drop_all)
#         await conn.run_sync(Base.metadata.create_all)

#     yield engine

#     async with engine.begin() as conn:
#         await conn.run_sync(Base.metadata.drop_all)

#     await engine.dispose()


# @pytest_asyncio.fixture()
# async def db_session(engine):
#     """
#     Database session which utilizes the above engine and event loop and sets up a nested transaction before yielding.
#     It rolls back the nested transaction after yield.
#     """
#     event_loop = asyncio.get_running_loop()
#     session_maker = async_sessionmaker(
#         engine, expire_on_commit=False, autocommit=False, autoflush=False
#     )

#     async with engine.connect() as conn:
#         transaction = await conn.begin()
#         async with session_maker(bind=conn) as session:
#             yield session

#             await transaction.rollback()


@pytest_asyncio.fixture(scope="function")
async def db_session():
    """
    Creates a new async DB session.
    """
    engine = create_async_engine(config["DB_URL"], echo=False, future=True)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)

    await initialize_db()
    _, session_maker_instance = get_db_engine_and_sessionmaker()

    async with session_maker_instance() as session:
        yield session

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)

    await engine.dispose()


@pytest.fixture
def client(app, db_session):
    with TestClient(app) as client:
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
        else get_auto_policy_id(resource_paths=[resource_paths[0]])
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


@pytest.fixture(scope="function")
def list_roles_patcher():
    """
    This fixture patches the list_roles method.
    """

    future = asyncio.Future()
    future.set_result(
        {
            "roles": [
                {
                    "id": "study_registrant",
                    "permissions": [
                        {
                            "id": "study_registration",
                            "action": {
                                "service": "study_registration",
                                "method": "access",
                            },
                        },
                    ],
                },
                {
                    "id": "/mds_user",
                    "permissions": [
                        {
                            "id": "mds_access",
                            "action": {"service": "mds_gateway", "method": "access"},
                        },
                    ],
                },
                {
                    "id": "/study_user",
                    "permissions": [
                        {
                            "id": "study_access",
                            "action": {"service": "study_access", "method": "access"},
                        },
                    ],
                },
            ]
        }
    )

    list_roles_mock = MagicMock()
    list_roles_mock.return_value = future
    role_patch = patch("requestor.routes.query.arborist.list_roles", list_roles_mock)
    role_patch.start()

    yield

    role_patch.stop()


@pytest.fixture(autouse=True, scope="function", params=["user_token", "client_token"])
def access_token_user_client_patcher(client, request):
    """
    The `access_token` function will return first a token linked to a test
    user, then a token linked to a test client.
    """

    async def get_access_token(*args, **kwargs):
        if request.param == "user_token":
            return {"sub": "1", "context": {"user": {"name": "requestor_user"}}}
        if request.param == "client_token":
            return {"context": {}, "azp": "test-client-id"}

    access_token_mock = MagicMock()
    access_token_mock.return_value = get_access_token

    access_token_patch = patch("requestor.auth.access_token", access_token_mock)
    access_token_patch.start()

    yield access_token_mock

    access_token_patch.stop()


@pytest.fixture(scope="function")
def access_token_user_only_patcher(client, request):
    """
    The `access_token` function will return a token linked to a test user.
    This fixture should be used explicitely instead of the automatic
    `access_token_user_client_patcher` fixture for endpoints that do not
    support client tokens.
    """

    async def get_access_token(*args, **kwargs):
        return {"sub": "1", "context": {"user": {"name": "requestor_user"}}}

    access_token_mock = MagicMock()
    access_token_mock.return_value = get_access_token

    access_token_patch = patch("requestor.auth.access_token", access_token_mock)
    access_token_patch.start()

    yield access_token_mock

    access_token_patch.stop()


# @pytest.fixture(autouse=True)
# def clean_db():
#     """
#     Before each test, delete all existing requests from the DB
#     """
#     # The code below doesn't work because of this issue
#     # https://github.com/encode/starlette/issues/440, so for now reset
#     # using alembic.
#     # pytest-asyncio = "^0.14.0"
#     # from requestor.models import Request as RequestModel
#     # @pytest.mark.asyncio
#     # async def clean_db():
#     #     await RequestModel.delete.gino.all()
#     #     yield

#     alembic_main(["--raiseerr", "downgrade", "base"])
#     alembic_main(["--raiseerr", "upgrade", "head"])

#     yield


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
                        "name": "requestor_user",
                        "groups": [],
                        "policies": [{"policy": "test-policy"}],
                    },
                    200 if authorized else 403,
                )
            },
            "http://arborist-service/user/requestor_user/policy": {
                "POST": ({}, 204 if authorized else 403)
            },
            "http://arborist-service/user/other_user/policy": {
                "POST": ({}, 204 if authorized else 403)
            },
            "http://arborist-service/user/requestor_user/policy/test-policy": {
                "DELETE": ({}, 204 if authorized else 403)
            },
            "http://arborist-service/user/requestor_user/policy/test-policy-with-external-calls": {
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
                                "id": "test-policy-with-external-calls",
                                "resource_paths": [
                                    "/resource-with-external-calls/resource"
                                ],
                                "roles": [],
                            },
                            {
                                "id": "test-policy-with-authed-external-call",
                                "resource_paths": [
                                    "/resource-with-authed-external-call/resource"
                                ],
                                "roles": [],
                            },
                            {
                                "id": "test-policy-with-redirect-and-external-call",
                                "resource_paths": [
                                    "/resource-with-redirect-and-external-call"
                                ],
                                "roles": [],
                            },
                            {
                                "id": "test-policy-i-cant-access",
                                "resource_paths": ["something-i-cant-access"],
                                "roles": [],
                            },
                            {
                                "id": "my.resource_accessor",
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
