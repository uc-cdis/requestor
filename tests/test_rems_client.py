"""
Unit tests for the REMS API client (requestor.rems_client.RemsClient).

The client is deliberately lookup-only: it reads catalogue state and creates
applications on behalf of applicants, but never creates organizations,
resources, or catalogue items. These tests exercise the real _request path via
an httpx.MockTransport (no live REMS), and guard against the resource-creation
behaviour ever being re-added.
"""

import json

import httpx
import pytest
from fastapi import HTTPException

from requestor.rems_client import RemsClient


REMS_CONFIG = {
    "URL": "https://rems.example.org",
    "API_KEY": "test-api-key",
    "USER_ID": "requestor",
}


# Override the heavy conftest fixtures: these pure-function tests need no DB or
# TestClient, but the autouse access_token_patcher depends on `client`.
@pytest.fixture
def db_session():
    yield None


@pytest.fixture
def client():
    yield None


def build_client(handler):
    """Return (http_client, RemsClient) backed by a mock transport."""
    transport = httpx.MockTransport(handler)
    http_client = httpx.AsyncClient(transport=transport)
    return http_client, RemsClient(http_client, REMS_CONFIG)


@pytest.mark.asyncio
async def test_get_active_catalogue_item_returns_first_active(
    access_token_user_only_patcher,
):
    captured = []

    def handler(request):
        captured.append(request)
        return httpx.Response(
            200,
            json=[
                {"id": 1, "enabled": False, "archived": False, "expired": False},
                {"id": 2, "enabled": True, "archived": True, "expired": False},
                {"id": 3, "enabled": True, "archived": False, "expired": True},
                {"id": 4, "enabled": True, "archived": False, "expired": False},
            ],
        )

    http_client, rems = build_client(handler)
    async with http_client:
        item = await rems.get_active_catalogue_item_for_resource(
            "/programs/ACDC/projects/STUDY1"
        )

    assert item["id"] == 4
    req = captured[0]
    assert req.method == "GET"
    assert req.url.path == "/api/catalogue-items"
    assert req.url.params["resource"] == "/programs/ACDC/projects/STUDY1"
    assert req.url.params["archived"] == "false"
    assert req.headers["x-rems-api-key"] == "test-api-key"
    assert req.headers["x-rems-user-id"] == "requestor"


@pytest.mark.asyncio
async def test_get_active_catalogue_item_none_when_empty(
    access_token_user_only_patcher,
):
    http_client, rems = build_client(lambda request: httpx.Response(200, json=[]))
    async with http_client:
        item = await rems.get_active_catalogue_item_for_resource("/some/resource")
    assert item is None


@pytest.mark.asyncio
async def test_get_active_catalogue_item_none_when_all_inactive(
    access_token_user_only_patcher,
):
    def handler(request):
        return httpx.Response(
            200,
            json=[
                {"id": 1, "enabled": False, "archived": False, "expired": False},
                {"id": 2, "enabled": True, "archived": True, "expired": False},
                {"id": 3, "enabled": True, "archived": False, "expired": True},
            ],
        )

    http_client, rems = build_client(handler)
    async with http_client:
        item = await rems.get_active_catalogue_item_for_resource("/some/resource")
    assert item is None


@pytest.mark.asyncio
async def test_get_active_catalogue_item_url_encodes_resid(
    access_token_user_only_patcher,
):
    captured = []

    def handler(request):
        captured.append(request)
        return httpx.Response(200, json=[])

    resid = "/programs/ACDC/projects/STUDY 1 & 2"
    http_client, rems = build_client(handler)
    async with http_client:
        await rems.get_active_catalogue_item_for_resource(resid)

    # The raw query must be percent-encoded, and must round-trip back to resid.
    assert "%20" in str(captured[0].url)
    assert captured[0].url.params["resource"] == resid


@pytest.mark.asyncio
async def test_create_application_posts_as_applicant(access_token_user_only_patcher):
    captured = {}

    def handler(request):
        captured["request"] = request
        captured["body"] = request.content
        return httpx.Response(200, json={"success": True, "application-id": 555})

    http_client, rems = build_client(handler)
    async with http_client:
        res = await rems.create_application(
            catalogue_item_id=123, applicant_user_id="auth0|abc"
        )

    req = captured["request"]
    assert req.method == "POST"
    assert req.url.path == "/api/applications/create"
    # The applicant, not the service account, is the REMS actor.
    assert req.headers["x-rems-user-id"] == "auth0|abc"
    assert json.loads(captured["body"]) == {"catalogue-item-ids": [123]}
    assert res == {"success": True, "application-id": 555}


@pytest.mark.asyncio
async def test_rems_http_error_maps_to_502(access_token_user_only_patcher):
    http_client, rems = build_client(
        lambda request: httpx.Response(500, json={"error": "boom"})
    )
    async with http_client:
        with pytest.raises(HTTPException) as exc_info:
            await rems.get_active_catalogue_item_for_resource("/x")
    assert exc_info.value.status_code == 502


def test_rems_client_has_no_resource_creation_methods(access_token_user_only_patcher):
    """
    Guard against the REMS propagation behaviour being re-introduced: the client
    must not grow methods that create organizations, resources, or catalogue
    items.
    """
    forbidden = [
        "create_resource",
        "ensure_resource",
        "create_catalogue_item",
        "ensure_catalogue_item",
        "get_resource_by_resid",
        "get_catalogue_items_for_resource",
    ]
    present = [name for name in forbidden if hasattr(RemsClient, name)]
    assert not present, f"RemsClient must stay lookup-only; found: {present}"
