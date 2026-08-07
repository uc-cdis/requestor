"""
Unit tests for the REMS request adapter (requestor.rems_adapter.create_rems_request).

The adapter looks up an already-provisioned catalogue item and, if configured,
creates an application against it. It must never create REMS resources or
catalogue items, and must fail cleanly (404) when a resource has no catalogue
item.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException

from requestor import rems_adapter
from requestor.config import config


# Override the heavy conftest fixtures: these tests patch RemsClient and never
# touch the DB or a TestClient, but the autouse access_token_patcher needs
# `client`.
@pytest.fixture
def db_session():
    yield None


@pytest.fixture
def client():
    yield None


@pytest.fixture
def rems_config():
    """Install a minimal REMS config for the request path and restore after."""
    original = dict(config.get("REMS", {}))
    config["REMS"] = {
        **original,
        "ENABLED": True,
        "URL": "https://rems.example.org",
        "API_KEY": "test-api-key",
        "USER_ID": "requestor",
        "CREATE_APPLICATION": False,
        "CATALOGUE_ITEM_URL_TEMPLATE": "https://rems.example.org/catalogue/{catalogue_item_id}",
        "APPLICATION_URL_TEMPLATE": "https://rems.example.org/application/{application_id}",
    }
    yield config["REMS"]
    config["REMS"] = original


def _patch_rems_client(**async_methods):
    """
    Patch requestor.rems_adapter.RemsClient with a mock whose given methods are
    AsyncMocks returning the supplied values. Returns (patcher, mock_client).
    """
    mock_client = MagicMock()
    for name, return_value in async_methods.items():
        setattr(mock_client, name, AsyncMock(return_value=return_value))
    patcher = patch("requestor.rems_adapter.RemsClient", return_value=mock_client)
    return patcher, mock_client


@pytest.mark.asyncio
async def test_missing_resid_raises_400(rems_config, access_token_user_only_patcher):
    patcher, mock_client = _patch_rems_client(
        get_active_catalogue_item_for_resource=None
    )
    with patcher:
        with pytest.raises(HTTPException) as exc_info:
            await rems_adapter.create_rems_request(MagicMock(), {}, "user1")
    assert exc_info.value.status_code == 400
    mock_client.get_active_catalogue_item_for_resource.assert_not_called()


@pytest.mark.asyncio
async def test_not_provisioned_raises_404_and_skips_application(
    rems_config, access_token_user_only_patcher
):
    config["REMS"]["CREATE_APPLICATION"] = True
    patcher, mock_client = _patch_rems_client(
        get_active_catalogue_item_for_resource=None,
        create_application={"success": True, "application-id": 1},
    )
    with patcher:
        with pytest.raises(HTTPException) as exc_info:
            await rems_adapter.create_rems_request(
                MagicMock(),
                {"resource_path": "/programs/ACDC/projects/STUDY1"},
                "user1",
            )
    assert exc_info.value.status_code == 404
    mock_client.get_active_catalogue_item_for_resource.assert_awaited_once_with(
        "/programs/ACDC/projects/STUDY1"
    )
    mock_client.create_application.assert_not_called()


@pytest.mark.asyncio
async def test_creates_application_when_enabled(
    rems_config, access_token_user_only_patcher
):
    config["REMS"]["CREATE_APPLICATION"] = True
    patcher, mock_client = _patch_rems_client(
        get_active_catalogue_item_for_resource={"id": 123},
        create_application={"success": True, "application-id": 555},
    )
    with patcher:
        result = await rems_adapter.create_rems_request(
            MagicMock(),
            {
                "resource_paths": ["/programs/ACDC/projects/STUDY1"],
                "resource_display_name": "ACDC Study 1",
            },
            "auth0|abc",
        )

    assert result["backend"] == "rems"
    assert result["resource_id"] == "/programs/ACDC/projects/STUDY1"
    assert result["catalogue_item_id"] == 123
    assert result["application_id"] == 555
    assert result["redirect_url"] == "https://rems.example.org/application/555"
    mock_client.get_active_catalogue_item_for_resource.assert_awaited_once_with(
        "/programs/ACDC/projects/STUDY1"
    )
    mock_client.create_application.assert_awaited_once_with(
        catalogue_item_id=123, applicant_user_id="auth0|abc"
    )


@pytest.mark.asyncio
async def test_skips_application_when_disabled(
    rems_config, access_token_user_only_patcher
):
    # CREATE_APPLICATION defaults to False in the rems_config fixture.
    patcher, mock_client = _patch_rems_client(
        get_active_catalogue_item_for_resource={"id": 123},
        create_application={"success": True, "application-id": 999},
    )
    with patcher:
        result = await rems_adapter.create_rems_request(
            MagicMock(), {"resource_id": "study-1"}, "user1"
        )

    assert result["application_id"] is None
    assert result["catalogue_item_id"] == 123
    assert result["redirect_url"] == "https://rems.example.org/catalogue/123"
    mock_client.create_application.assert_not_called()


@pytest.mark.asyncio
async def test_application_failure_raises_502(
    rems_config, access_token_user_only_patcher
):
    config["REMS"]["CREATE_APPLICATION"] = True
    patcher, mock_client = _patch_rems_client(
        get_active_catalogue_item_for_resource={"id": 123},
        create_application={"success": False, "errors": [{"type": "boom"}]},
    )
    with patcher:
        with pytest.raises(HTTPException) as exc_info:
            await rems_adapter.create_rems_request(
                MagicMock(), {"resource_path": "/p"}, "user1"
            )
    assert exc_info.value.status_code == 502


@pytest.mark.asyncio
async def test_adapter_never_creates_rems_objects(
    rems_config, access_token_user_only_patcher
):
    """The adapter must only look up and (optionally) create an application."""
    config["REMS"]["CREATE_APPLICATION"] = True
    patcher, mock_client = _patch_rems_client(
        get_active_catalogue_item_for_resource={"id": 123},
        create_application={"success": True, "application-id": 7},
    )
    with patcher:
        await rems_adapter.create_rems_request(
            MagicMock(), {"resource_id": "r"}, "user1"
        )

    called_names = {call[0] for call in mock_client.mock_calls if call[0]}
    forbidden = {
        "create_resource",
        "ensure_resource",
        "create_catalogue_item",
        "ensure_catalogue_item",
    }
    assert not (called_names & forbidden), f"unexpected creation calls: {called_names}"


def test_redirect_url_precedence(access_token_user_only_patcher):
    """Application template wins when an application id is present; otherwise the
    catalogue item template; otherwise a sensible default."""
    cfg = {
        "URL": "https://rems.example.org",
        "CATALOGUE_ITEM_URL_TEMPLATE": "https://rems.example.org/catalogue/{catalogue_item_id}",
        "APPLICATION_URL_TEMPLATE": "https://rems.example.org/application/{application_id}",
    }
    assert (
        rems_adapter.build_rems_redirect_url(cfg, catalogue_item_id=1, application_id=9)
        == "https://rems.example.org/application/9"
    )
    assert (
        rems_adapter.build_rems_redirect_url(cfg, catalogue_item_id=1, application_id=None)
        == "https://rems.example.org/catalogue/1"
    )
    assert (
        rems_adapter.build_rems_redirect_url(
            {"URL": "https://rems.example.org"}, catalogue_item_id=42
        )
        == "https://rems.example.org/catalogue?items=42"
    )
