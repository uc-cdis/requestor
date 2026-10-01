"""
Tests the authorization check that governs creating requests for another user.
"""
import pytest
from unittest.mock import MagicMock, patch


# Resource path of "test-policy" in the `mock_arborist_requests` fixture. Every test
# here grants it, so that the only denial under test is the on-behalf one.
POLICY_RESOURCE_PATH = "/my/resource"
ON_BEHALF_ANY_USER = "/requestor/on_behalf"

FAKE_JWT = "1.2.3"


def test_create_request_for_self_does_not_need_on_behalf_access(
    client, access_token_user_only_patcher, mock_arborist_requests
):
    """A caller naming their own username does not need on-behalf access."""
    mock_arborist_requests(authorized_resource_paths=[POLICY_RESOURCE_PATH])

    res = client.post(
        "/request",
        json={"username": "requestor_user", "policy_id": "test-policy"},
        headers={"Authorization": f"bearer {FAKE_JWT}"},
    )

    assert res.status_code == 201, res.text
    assert res.json()["username"] == "requestor_user"


def test_create_request_for_other_user_without_on_behalf_access_is_denied(
    client, mock_arborist_requests
):
    """
    Naming another user is denied without on-behalf access, for a user token and for a
    client token, which has no username of its own.
    """
    mock_arborist_requests(authorized_resource_paths=[POLICY_RESOURCE_PATH])

    res = client.post(
        "/request",
        json={"username": "other_user", "policy_id": "test-policy"},
        headers={"Authorization": f"bearer {FAKE_JWT}"},
    )

    assert res.status_code == 403, res.text


def test_create_request_for_other_user_with_access_to_whole_subtree(
    client, mock_arborist_requests
):
    """A caller granted the whole on-behalf subtree may name any user."""
    mock_arborist_requests(
        authorized_resource_paths=[POLICY_RESOURCE_PATH, ON_BEHALF_ANY_USER]
    )

    res = client.post(
        "/request",
        json={"username": "other_user", "policy_id": "test-policy"},
        headers={"Authorization": f"bearer {FAKE_JWT}"},
    )

    assert res.status_code == 201, res.text
    assert res.json()["username"] == "other_user"


@pytest.mark.parametrize(
    "requested_username,expected_status_code",
    [("other_user", 201), ("a_third_user", 403)],
)
def test_create_request_with_on_behalf_access_to_a_single_user(
    client, mock_arborist_requests, requested_username, expected_status_code
):
    """A grant for one username authorizes requests for that username only."""
    mock_arborist_requests(
        authorized_resource_paths=[
            POLICY_RESOURCE_PATH,
            f"{ON_BEHALF_ANY_USER}/other_user",
        ]
    )

    res = client.post(
        "/request",
        json={"username": requested_username, "policy_id": "test-policy"},
        headers={"Authorization": f"bearer {FAKE_JWT}"},
    )

    assert res.status_code == expected_status_code, res.text


def test_create_request_with_username_containing_a_slash_is_rejected(
    client, mock_arborist_requests
):
    """
    A username containing "/" is rejected rather than used as a resource path segment,
    where a grant for "alice" would cover it.
    """
    mock_arborist_requests(
        authorized_resource_paths=[
            POLICY_RESOURCE_PATH,
            f"{ON_BEHALF_ANY_USER}/alice",
        ]
    )

    res = client.post(
        "/request",
        json={"username": "alice/bob", "policy_id": "test-policy"},
        headers={"Authorization": f"bearer {FAKE_JWT}"},
    )

    assert res.status_code == 400, res.text


def test_denied_revoke_request_does_not_query_the_user_access(
    client, mock_arborist_requests
):
    """A denied caller cannot learn whether the named user holds the policy."""
    mock_arborist_requests(authorized_resource_paths=[POLICY_RESOURCE_PATH])

    mock_user_has_policy = MagicMock()
    user_has_policy_patch = patch(
        "requestor.routes.manage.arborist.user_has_policy", mock_user_has_policy
    )
    user_has_policy_patch.start()

    res = client.post(
        "/request?revoke",
        json={"username": "other_user", "policy_id": "test-policy"},
        headers={"Authorization": f"bearer {FAKE_JWT}"},
    )

    user_has_policy_patch.stop()
    assert res.status_code == 403, res.text
    assert not mock_user_has_policy.called, "Arborist was queried for the user's access"


def test_denied_request_does_not_create_a_policy(client, mock_arborist_requests):
    """
    A denied caller does not leave a policy behind in Arborist, which request creation
    does not undo when it fails.
    """
    mock_arborist_requests(authorized_resource_paths=[POLICY_RESOURCE_PATH])

    mock_create_policy = MagicMock()
    create_policy_patch = patch(
        "requestor.routes.manage.arborist.create_arborist_policy", mock_create_policy
    )
    create_policy_patch.start()

    res = client.post(
        "/request",
        json={"username": "other_user", "resource_paths": [POLICY_RESOURCE_PATH]},
        headers={"Authorization": f"bearer {FAKE_JWT}"},
    )

    create_policy_patch.stop()
    assert res.status_code == 403, res.text
    assert not mock_create_policy.called, "A policy was created for a denied request"
