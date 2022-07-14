import asyncio
import pytest
from unittest.mock import MagicMock, patch

from requestor.arborist import (
    get_auto_policy_id_for_resource_paths,
    get_auto_policy_id_for_role_ids_and_resource_paths,
)
from requestor.config import config


@pytest.mark.parametrize(
    "data",
    [
        {
            # with both resource_path and policy_id
            "username": "requestor_user",
            "resource_path": "/test-resource-path/resource",
            "policy_id": "test-policy",
            "resource_id": "uniqid",
            "resource_display_name": "My Resource",
            "err_msg": "The request must have either",
        },
        {
            # without resource_path and policy_id
            "username": "requestor_user",
            "resource_id": "uniqid",
            "resource_display_name": "My Resource",
            "err_msg": "The request must have either",
        },
        {
            # with role_ids without resource_paths and resource_path
            "username": "requestor_user",
            "role_ids": ["test-role"],
            "resource_id": "uniqid",
            "resource_display_name": "My Resource",
            "err_msg": "The request must have either",
        },
        {
            # with both role_ids and policy_id
            "username": "requestor_user",
            "role_ids": ["study_registrant"],
            "policy_id": "test-policy",
            "resource_id": "uniqid",
            "resource_display_name": "My Resource",
            "err_msg": "The request cannot have both role_ids and policy_id",
        },
    ],
)
def test_create_request_with_unallowed_params(client, data):
    """
    When a user attempts to create a request with
        - both resource_path and policy_id
        - both of them missing
        - both role_ids and policy_id
    a 400 Bad request is returned to the client.
    """
    fake_jwt = "1.2.3"

    res = client.post(
        "/request", json=data, headers={"Authorization": f"bearer {fake_jwt}"}
    )

    assert res.status_code == 400, res.text
    assert data["err_msg"] in res.json()["detail"]


def test_create_request_without_username(client):
    """
    When a username is not provided in the body, the request is created
    using the username from the provided access token.
    """
    fake_jwt = "1.2.3"

    # create a request
    data = {
        "policy_id": "test-policy",
        "resource_id": "uniqid",
        "resource_display_name": "My Resource",
    }
    res = client.post(
        "/request", json=data, headers={"Authorization": f"bearer {fake_jwt}"}
    )

    assert res.status_code == 201, res.text
    request_data = res.json()
    request_id = request_data.get("request_id")
    assert request_id, "POST /request did not return a request_id"
    assert request_data == {
        "request_id": request_id,
        "username": "requestor_user",  # username from access_token_patcher
        "policy_id": data["policy_id"],
        "resource_id": data["resource_id"],
        "resource_display_name": data["resource_display_name"],
        "status": config["DEFAULT_INITIAL_STATUS"],
        # just ensure revoke, created_time and updated_time are there:
        "revoke": False,
        "created_time": request_data["created_time"],
        "updated_time": request_data["updated_time"],
    }


def test_create_duplicate_request(client):
    """
    Users can only request access to a resource once.
    (username, policy_id) should be unique, except if other
    requests statuses are in DRAFT_STATUSES or FINAL_STATUSES.
    """
    fake_jwt = "1.2.3"

    # create a request
    data = {
        "username": "requestor_user",
        "policy_id": "test-policy",
        "resource_id": "uniqid",
        "resource_display_name": "My Resource",
    }
    res = client.post(
        "/request", json=data, headers={"Authorization": f"bearer {fake_jwt}"}
    )
    assert res.status_code == 201, res.text
    request_data = res.json()
    request_id = request_data.get("request_id")
    assert request_id, "POST /request did not return a request_id"
    assert request_data == {
        "request_id": request_id,
        "username": data["username"],
        "policy_id": data["policy_id"],
        "resource_id": data["resource_id"],
        "resource_display_name": data["resource_display_name"],
        "status": config["DEFAULT_INITIAL_STATUS"],
        # just ensure revoke, created_time and updated_time are there:
        "revoke": False,
        "created_time": request_data["created_time"],
        "updated_time": request_data["updated_time"],
    }

    # create a request with the same username and policy_id.
    # since the previous request is still a draft, it should work.
    res = client.post(
        "/request", json=data, headers={"Authorization": f"bearer {fake_jwt}"}
    )
    assert res.status_code == 201, res.text
    new_request_id = request_data.get("request_id")
    assert new_request_id == request_id

    # update the orignal request's status to a non-final, non-draft status
    res = client.put(f"/request/{request_id}", json={"status": "INTERMEDIATE_STATUS"})
    assert res.status_code == 200, res.text

    # attempt to create a request with the same username and policy_id.
    # it should not work: the previous request is in progress.
    res = client.post(
        "/request", json=data, headers={"Authorization": f"bearer {fake_jwt}"}
    )
    assert res.status_code == 409, res.text

    # update the orignal request's status to a final status
    status = config["FINAL_STATUSES"][-1]
    res = client.put(f"/request/{request_id}", json={"status": status})
    assert res.status_code == 200, res.text

    # create a request with the same username and policy_id.
    # now it should work: the previous request is not in progress anymore.
    res = client.post(
        "/request", json=data, headers={"Authorization": f"bearer {fake_jwt}"}
    )
    assert res.status_code == 201, res.text


@pytest.mark.parametrize(
    "data",
    [
        {
            # request with policy_id
            "username": "requestor_user",
            "policy_id": "test-policy",
            "resource_id": "uniqid",
            "resource_display_name": "My Resource",
        },
        {
            # request with role_ids and resource_paths
            "username": "requestor_user",
            "role_ids": ["study_registrant"],
            "resource_paths": ["/study/123456"],
            "resource_id": "uniqid",
            "resource_display_name": "My Resource",
        },
    ],
)
def test_create_request_without_access(
    client, mock_arborist_requests, list_roles_patcher, data
):
    fake_jwt = "1.2.3"
    mock_arborist_requests(authorized=False)

    # attempt to create a request
    res = client.post(
        "/request", json=data, headers={"Authorization": f"bearer {fake_jwt}"}
    )
    assert res.status_code == 403, res.text

    # check that no request was created
    res = client.get("/request", headers={"Authorization": f"bearer {fake_jwt}"})
    assert res.status_code == 200, res.text
    assert res.json() == []


def test_create_request_with_non_existent_policy(client):
    fake_jwt = "1.2.3"

    # attempt to create an access request with a policy that is not present in arborist
    data = {
        "username": "requestor_user",
        "policy_id": "some-nonexistent-policy",
    }
    res = client.post(
        "/request", json=data, headers={"Authorization": f"bearer {fake_jwt}"}
    )
    assert res.status_code == 400, res.text
    assert "does not exist" in res.text

    # attempt to create a revoke request with a policy that is not present in arborist
    data = {
        "username": "requestor_user",
        "policy_id": "some-nonexistent-policy",
    }
    res = client.post(
        "/request?revoke", json=data, headers={"Authorization": f"bearer {fake_jwt}"}
    )
    assert res.status_code == 400, res.text
    assert "does not exist" in res.text


def test_create_request_with_non_existent_role_id(client, list_roles_patcher):
    fake_jwt = "1.2.3"

    # attempt to create an access request with a role_id that is not present in arborist
    data = {
        "username": "requestor_user",
        "role_ids": ["study_registrant", "some-nonexistent-role"],
        "resource_paths": ["/test-resource-path/resource"],
    }
    res = client.post(
        "/request", json=data, headers={"Authorization": f"bearer {fake_jwt}"}
    )
    assert res.status_code == 400, res.text
    assert "do not exist" in res.text
    assert "nonexistent-role" in res.text
    assert "study_registrant" not in res.text


def test_update_request(client):
    """
    When updating the request with an UPDATE_ACCESS_STATUS, a call
    should be made to Arborist to grant the user access.
    """
    fake_jwt = "1.2.3"
    mock_arborist_return_value = 200
    # create a request
    res = client.post(
        "/request",
        json={
            "username": "requestor_user",
            "policy_id": "test-policy",
            "resource_id": "uniqid",
            "resource_display_name": "My Resource",
        },
        headers={"Authorization": f"bearer {fake_jwt}"},
    )
    assert res.status_code == 201, res.text
    request_data = res.json()
    request_id = request_data["request_id"]
    assert request_id, "POST /request did not return a request_id"
    assert request_data["status"] == config["DEFAULT_INITIAL_STATUS"]
    created_time = request_data["created_time"]
    updated_time = request_data["updated_time"]

    # try to update the request with a status that's not allowed
    status = "this is not allowed"
    res = client.put(f"/request/{request_id}", json={"status": status})
    assert res.status_code == 400, res.text
    assert "not an allowed request status" in res.json()["detail"]

    future = asyncio.Future()
    future.set_result(mock_arborist_return_value)
    mock_arborist_call = MagicMock(return_value=future)
    # Patching arborist method to see if arborist is being called when an update status is used.
    arborist_patch = patch(
        "requestor.routes.manage.arborist.grant_user_access_to_policy",
        mock_arborist_call,
    )
    arborist_patch.start()

    # update the request status
    status = config["ALLOWED_REQUEST_STATUSES"][1]
    res = client.put(f"/request/{request_id}", json={"status": status})
    assert res.status_code == 200, res.text
    request_data = res.json()
    assert request_data["status"] == status
    assert request_data["created_time"] == created_time
    assert request_data["updated_time"] != updated_time

    # update the request status and grant access
    status = config["UPDATE_ACCESS_STATUSES"][0]
    res = client.put(f"/request/{request_id}", json={"status": status})
    assert res.status_code == 200, res.text
    request_data = res.json()
    assert (
        mock_arborist_call.called
    ), "Arborist not called when updating a request with an 'update' status"
    arborist_patch.stop()
    assert request_data["status"] == status


def test_create_request_with_granting_access(client):
    fake_jwt = "1.2.3"
    mock_arborist_return_value = 200
    # Set status of a request to one of the "update" statuses to see if arborist is being called.
    status = config["UPDATE_ACCESS_STATUSES"][0]
    future = asyncio.Future()
    future.set_result(mock_arborist_return_value)
    mock_arborist_call = MagicMock(return_value=future)
    # Patching arborist method to see if arborist is being called when an update status is used.
    arborist_patch = patch(
        "requestor.routes.manage.arborist.grant_user_access_to_policy",
        mock_arborist_call,
    )
    arborist_patch.start()
    res = client.post(
        "/request",
        json={
            "username": "requestor_user",
            "policy_id": "test-policy",
            "resource_id": "uniqid",
            "resource_display_name": "My Resource",
            "status": status,
        },
        headers={"Authorization": f"bearer {fake_jwt}"},
    )
    assert (
        mock_arborist_call.called
    ), "Arborist not called when creating a request with an 'update' status"
    arborist_patch.stop()
    assert res.status_code == 201, res.text


@pytest.mark.parametrize(
    "data",
    [
        {
            # provide resource_path to get the default reader policies
            "username": "requestor_user",
            "resource_path": "/study/123456",
            "resource_id": "uniqid",
            "resource_display_name": "My Resource",
        },
        {
            # provide resource_paths without role_ids to get the default reader policies
            "username": "requestor_user",
            "resource_paths": ["/study/123456", "/mds_gateway", "/cedar"],
            "resource_id": "uniqid",
            "resource_display_name": "My Resource",
        },
        {
            # resource_paths will take precedence over resource_path
            "username": "requestor_user",
            "resource_paths": ["/study/123456", "/mds_gateway", "/cedar"],
            "resource_path": "/older_study/000111",
            "resource_id": "uniqid",
            "resource_display_name": "My Resource",
        },
    ],
)
def test_create_request_with_resource_path(client, data):
    fake_jwt = "1.2.3"

    if data.get("resource_paths"):
        policy_id = get_auto_policy_id_for_resource_paths(data["resource_paths"])
    elif data.get("resource_path"):
        # resource_path will get cast to a list
        policy_id = get_auto_policy_id_for_resource_paths([data["resource_path"]])
    else:
        policy_id = None

    res = client.post(
        "/request", json=data, headers={"Authorization": f"bearer {fake_jwt}"}
    )
    assert res.status_code == 201, res.text
    request_data = res.json()
    request_id = request_data.get("request_id")
    assert request_id, "POST /request did not return a request_id"
    assert request_data == {
        "request_id": request_id,
        "username": data["username"],
        "policy_id": policy_id,
        "resource_id": data["resource_id"],
        "resource_display_name": data["resource_display_name"],
        "status": config["DEFAULT_INITIAL_STATUS"],
        # just ensure revoke, created_time and updated_time are there:
        "revoke": False,
        "created_time": request_data["created_time"],
        "updated_time": request_data["updated_time"],
    }

    # get the request
    res = client.get(f"/request/{request_id}")
    assert res.status_code == 200, res.text
    assert res.json() == request_data


@pytest.mark.parametrize(
    "data",
    [
        {
            # include single role_ids and single resource_paths
            "username": "requestor_user",
            "role_ids": ["study_registrant"],
            "resource_paths": ["/study/123456"],
            "resource_id": "uniqid",
            "resource_display_name": "My Resource",
        },
        {
            # include multiple role_ids and resource_paths
            "username": "requestor_user",
            "role_ids": ["study_registrant", "/mds_user", "/cedar_user"],
            "resource_paths": ["/study/123456", "/mds_gateway", "/cedar"],
            "resource_id": "uniqid",
            "resource_display_name": "My Resource",
        },
        {
            # include role_ids and resource_path and resource_paths
            "username": "requestor_user",
            "role_ids": ["study_registrant", "/mds_user", "/cedar_user"],
            "resource_path": "/older_study/123456",
            "resource_paths": ["/study/123456", "/mds_gateway", "/cedar"],
            "resource_id": "uniqid",
            "resource_display_name": "My Resource",
        },
    ],
)
def test_create_request_with_role_ids_and_resource_paths(
    client, list_roles_patcher, data
):
    fake_jwt = "1.2.3"

    res = client.post(
        "/request", json=data, headers={"Authorization": f"bearer {fake_jwt}"}
    )
    assert res.status_code == 201, res.text
    request_data = res.json()
    request_id = request_data.get("request_id")
    assert request_id, "POST /request did not return a request_id"
    assert request_data == {
        "request_id": request_id,
        "username": data["username"],
        "policy_id": get_auto_policy_id_for_role_ids_and_resource_paths(
            data["role_ids"], data["resource_paths"]
        ),
        "resource_id": data["resource_id"],
        "resource_display_name": data["resource_display_name"],
        "status": config["DEFAULT_INITIAL_STATUS"],
        # just ensure revoke, created_time and updated_time are there:
        "revoke": False,
        "created_time": request_data["created_time"],
        "updated_time": request_data["updated_time"],
    }

    # get the request
    res = client.get(f"/request/{request_id}")
    assert res.status_code == 200, res.text
    assert res.json() == request_data


def test_update_request_without_access(client, mock_arborist_requests):
    fake_jwt = "1.2.3"

    # create a request
    res = client.post(
        "/request",
        json={
            "username": "requestor_user",
            "policy_id": "test-policy",
            "resource_id": "uniqid",
            "resource_display_name": "My Resource",
        },
        headers={"Authorization": f"bearer {fake_jwt}"},
    )
    assert res.status_code == 201, res.text
    request_data = res.json()
    request_id = request_data["request_id"]
    assert request_id, "POST /request did not return a request_id"
    assert request_data["status"] == config["DEFAULT_INITIAL_STATUS"]

    mock_arborist_requests(authorized=False)

    # attempt to update the request status
    status = config["ALLOWED_REQUEST_STATUSES"][1]
    res = client.put(f"/request/{request_id}", json={"status": status})
    assert res.status_code == 403, res.text

    # check that the request was not updated
    mock_arborist_requests()  # authorize the GET request
    res = client.get(f"/request/{request_id}")
    assert res.status_code == 200, res.text
    assert res.json() == request_data


def test_delete_request(client):
    fake_jwt = "1.2.3"

    # create a request
    data = {
        "username": "requestor_user",
        "policy_id": "test-policy",
        "resource_id": "uniqid",
        "resource_display_name": "My Resource",
    }
    res = client.post(
        "/request", json=data, headers={"Authorization": f"bearer {fake_jwt}"}
    )
    assert res.status_code == 201, res.text
    request_data = res.json()
    request_id = request_data.get("request_id")
    assert request_id, "POST /request did not return a request_id"

    # get the request
    res = client.get(f"/request/{request_id}")
    assert res.status_code == 200, res.text
    assert res.json() == request_data

    # delete the request
    res = client.delete(f"/request/{request_id}")
    assert res.status_code == 200, res.text

    # make sure the request doesn't exist anymore
    res = client.get(f"/request/{request_id}")
    assert res.status_code == 404, res.text

    # delete a request that doesn't exist
    uuid = "571c6a1a-f21f-11ea-adc1-0242ac120002"
    res = client.delete(f"/request/{uuid}")
    assert res.status_code == 404, res.text


def test_delete_request_without_access(client, mock_arborist_requests):
    fake_jwt = "1.2.3"

    # create a request
    data = {
        "username": "requestor_user",
        "policy_id": "test-policy",
        "resource_id": "uniqid",
        "resource_display_name": "My Resource",
    }
    res = client.post(
        "/request", json=data, headers={"Authorization": f"bearer {fake_jwt}"}
    )
    assert res.status_code == 201, res.text
    request_data = res.json()
    request_id = request_data.get("request_id")
    assert request_id, "POST /request did not return a request_id"

    mock_arborist_requests(authorized=False)

    # delete the request
    res = client.delete(f"/request/{request_id}")
    assert res.status_code == 403, res.text

    # get the request
    mock_arborist_requests()  # authorize the GET request
    res = client.get(f"/request/{request_id}")
    assert res.status_code == 200, res.text
    assert res.json() == request_data


def test_revoke_request_success(client):
    """
    When updating a "revoke" request with an UPDATE_ACCESS_STATUS, a call
    should be made to Arborist to revoke the user access.
    """
    fake_jwt = "1.2.3"
    data = {
        "username": "requestor_user",
        "policy_id": "test-policy",
        "resource_id": "uniqid",
        "resource_display_name": "My Resource",
    }

    # create a request with the 'revoke' query parameter
    res = client.post(
        "/request?revoke", json=data, headers={"Authorization": f"bearer {fake_jwt}"}
    )
    assert res.status_code == 201, res.text
    request_data = res.json()
    request_id = request_data.get("request_id")
    assert request_id, "POST /request did not return a request_id"
    assert request_data == {
        "request_id": request_id,
        "username": data["username"],
        "policy_id": data["policy_id"],
        "resource_id": data["resource_id"],
        "resource_display_name": data["resource_display_name"],
        "status": config["DEFAULT_INITIAL_STATUS"],
        "revoke": True,
        # just ensure created_time and updated_time are there:
        "created_time": request_data["created_time"],
        "updated_time": request_data["updated_time"],
    }

    # update the request status and revoke access
    status = config["UPDATE_ACCESS_STATUSES"][0]
    res = client.put(f"/request/{request_id}", json={"status": status})

    assert res.status_code == 200, res.text
    request_data = res.json()
    assert request_data["status"] == status


def test_revoke_request_after_creating(client):
    """
    Requestor should allow creating a "revoke" request for the same policy ID
    and username that already have an active non-"revoke" request (even if we
    do not expect this scenario to happen in real life).
    """
    fake_jwt = "1.2.3"
    data = {
        "username": "requestor_user",
        "policy_id": "test-policy",
        "resource_id": "uniqid",
        "resource_display_name": "My Resource",
    }

    # create a request
    res = client.post(
        "/request",
        json=data,
        headers={"Authorization": f"bearer {fake_jwt}"},
    )
    assert res.status_code == 201, res.text
    request_id = res.json()["request_id"]

    # update the request status so it's not a draft anymore
    status = "INTERMEDIATE_STATUS"
    res = client.put(f"/request/{request_id}", json={"status": status})
    assert res.status_code == 200, res.text

    # create an identical request, but with the 'revoke' query parameter
    res = client.post(
        "/request?revoke", json=data, headers={"Authorization": f"bearer {fake_jwt}"}
    )
    assert res.status_code == 201, res.text
    request_id = res.json()["request_id"]


def test_revoke_request_failure(client):
    fake_jwt = "1.2.3"
    data = {
        "username": "requestor_user",
        "policy_id": "test-policy",
        "resource_id": "uniqid",
        "resource_display_name": "My Resource",
    }

    # create a request with an invalid 'revoke' query parameter
    res = client.post(
        "/request?revoke=false",
        json=data,
        headers={"Authorization": f"bearer {fake_jwt}"},
    )
    assert res.status_code == 400, res.text
    assert "should not be assigned a value" in res.json()["detail"]

    # attempt to revoke access to a policy the user doesn't have
    data["policy_id"] = "test-existing-policy"
    res = client.post(
        "/request?revoke", json=data, headers={"Authorization": f"bearer {fake_jwt}"}
    )
    assert res.status_code == 400, res.text
    assert "does not have access to policy" in res.json()["detail"]
