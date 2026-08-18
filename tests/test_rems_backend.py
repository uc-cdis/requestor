"""
Tests for the optional REMS request backend.

These tests intentionally keep the default Requestor behavior covered while
verifying that REMS mode and dual mode are opt-in only.
"""

from unittest.mock import AsyncMock, patch

import pytest

from requestor.config import config


@pytest.fixture
def rems_config_enabled():
    """Temporarily configure enough REMS settings for request routing tests."""
    original_backend = config.get("REQUEST_BACKEND", "requestor")
    original_rems = dict(config.get("REMS", {}))

    config["REMS"] = {
        **original_rems,
        "ENABLED": True,
        "URL": "https://rems.example.org",
        "API_KEY": "test-api-key",
        "USER_ID": "requestor",
        "ORGANIZATION_ID": "gen3",
        "WORKFLOW_ID": 1,
        "FORM_ID": 1,
        "LANGUAGE": "en",
        "LICENSE_IDS": [],
        "CREATE_APPLICATION": False,
        "CATALOGUE_ITEM_URL_TEMPLATE": "https://rems.example.org/catalogue/{catalogue_item_id}",
        "APPLICATION_URL_TEMPLATE": "",
    }

    yield

    config["REQUEST_BACKEND"] = original_backend
    config["REMS"] = original_rems


def test_request_backend_default_does_not_call_rems(
    client, access_token_user_only_patcher, rems_config_enabled
):
    """
    Existing behavior must remain the default.

    Even if REMS config exists, REQUEST_BACKEND=requestor should create the
    normal Requestor DB record and never call the REMS adapter.
    """
    config["REQUEST_BACKEND"] = "requestor"

    rems_mock = AsyncMock()
    with patch("requestor.routes.manage.create_rems_request", rems_mock):
        res = client.post(
            "/request",
            json={
                "username": "requestor_user",
                "policy_id": "test-policy",
                "resource_id": "uniqid",
                "resource_display_name": "My Resource",
            },
            headers={"Authorization": "bearer 1.2.3"},
        )

    assert res.status_code == 201, res.text
    body = res.json()
    assert body["username"] == "requestor_user"
    assert body["policy_id"] == "test-policy"
    assert body["status"] == config["DEFAULT_INITIAL_STATUS"]
    assert "rems" not in body
    assert "redirect_url" not in body
    rems_mock.assert_not_called()


def test_request_backend_rems_returns_rems_redirect(
    client, access_token_user_only_patcher, rems_config_enabled
):
    """
    REQUEST_BACKEND=rems should bypass normal Requestor record creation and
    return the REMS adapter result to the portal.
    """
    config["REQUEST_BACKEND"] = "rems"

    rems_response = {
        "backend": "rems",
        "resource_id": "/programs/ACDC/projects/STUDY1",
        "catalogue_item_id": 123,
        "application_id": None,
        "redirect_url": "https://rems.example.org/catalogue/123",
    }
    rems_mock = AsyncMock(return_value=rems_response)

    with patch("requestor.routes.manage.create_rems_request", rems_mock):
        res = client.post(
            "/request",
            json={
                "resource_path": "/programs/ACDC/projects/STUDY1",
                "resource_id": "study-1",
                "resource_display_name": "ACDC Study 1",
                "study_url": "https://portal.example.org/study/STUDY1",
            },
            headers={"Authorization": "bearer 1.2.3"},
        )

    assert res.status_code == 201, res.text
    assert res.json() == rems_response

    rems_mock.assert_awaited_once()
    _, data, applicant_user_id = rems_mock.await_args.args
    assert data["username"] == "requestor_user"
    assert data["resource_paths"] == ["/programs/ACDC/projects/STUDY1"]
    assert data["resource_display_name"] == "ACDC Study 1"
    assert applicant_user_id == "requestor_user"


def test_request_backend_rems_rejects_revoke(
    client, access_token_user_only_patcher, rems_config_enabled
):
    """The REMS backend does not implement revoke requests."""
    config["REQUEST_BACKEND"] = "rems"

    rems_mock = AsyncMock()
    with patch("requestor.routes.manage.create_rems_request", rems_mock):
        res = client.post(
            "/request?revoke",
            json={
                "username": "requestor_user",
                "resource_path": "/programs/ACDC/projects/STUDY1",
                "resource_display_name": "ACDC Study 1",
            },
            headers={"Authorization": "bearer 1.2.3"},
        )

    assert res.status_code == 400, res.text
    assert "does not support the 'revoke' parameter" in res.json()["detail"]
    rems_mock.assert_not_called()


def test_request_backend_dual_preserves_requestor_response_and_adds_rems(
    client, access_token_user_only_patcher, rems_config_enabled
):
    """
    REQUEST_BACKEND=dual should preserve the standard Requestor record and add
    REMS metadata under the `rems` key for migration/testing.
    """
    config["REQUEST_BACKEND"] = "dual"

    rems_response = {
        "backend": "rems",
        "resource_id": "uniqid",
        "catalogue_item_id": 456,
        "application_id": None,
        "redirect_url": "https://rems.example.org/catalogue/456",
    }
    rems_mock = AsyncMock(return_value=rems_response)

    with patch("requestor.routes.manage.create_rems_request", rems_mock):
        res = client.post(
            "/request",
            json={
                "username": "requestor_user",
                "policy_id": "test-policy",
                "resource_id": "uniqid",
                "resource_display_name": "My Resource",
                "study_url": "https://portal.example.org/study/uniqid",
            },
            headers={"Authorization": "bearer 1.2.3"},
        )

    assert res.status_code == 201, res.text
    body = res.json()
    assert body["username"] == "requestor_user"
    assert body["policy_id"] == "test-policy"
    assert body["resource_id"] == "uniqid"
    assert body["status"] == config["DEFAULT_INITIAL_STATUS"]
    assert body["rems"] == rems_response

    rems_mock.assert_awaited_once()
    _, data, applicant_user_id = rems_mock.await_args.args
    assert data["username"] == "requestor_user"
    assert data["policy_id"] == "test-policy"
    assert data["resource_id"] == "uniqid"
    assert applicant_user_id == "requestor_user"
