"""
We now use `policy_id` instead of `resource_path` in access requests.
This set of tests ensures backwards compatibility for `resource_path`
as well as testing requests with `resource_paths` + `role_ids`.
"""
import pytest

from requestor.arborist import get_auto_policy_id
from requestor.config import config


@pytest.mark.parametrize(
    "data",
    [
        {
            # single resource_path
            "resource_path": "/study/123456",
            "resource_paths": None,
            "role_ids": None,
            "expected": "study.123456_accessor",
        },
        {
            # single resource_path in resource_paths list
            "resource_path": None,
            "resource_paths": ["/study/123456"],
            "role_ids": None,
            "expected": "study.123456_accessor",
        },
        {
            # mutiple resource_paths, each with leading slashes
            # (content up to and including the first slash is removed)
            "resource_path": None,
            "resource_paths": ["/study/123456", "/other_resource", "/another_resource"],
            "role_ids": None,
            "expected": "study.123456_other_resource_another_resource_accessor",
        },
        {
            # mutiple resource_paths, each with multiple slashes
            # (content up to and including the first slash is removed,
            # following slashes are converted to '.')
            "resource_path": None,
            "resource_paths": [
                "/study/123456",
                "/another_study/98765",
                "other_path/study/7890",
            ],
            "role_ids": None,
            "expected": "study.123456_another_study.98765_study.7890_accessor",
        },
        {
            # single resource_path in resource_paths + multiple role_ids
            "resource_path": None,
            "resource_paths": ["/study/123456"],
            "role_ids": ["my_reader", "my_other_reader"],
            "expected": "study.123456_my_reader_my_other_reader",
        },
        {
            # multiple resource_paths + multiple role_ids
            "resource_path": None,
            "resource_paths": ["/study/123456", "/other_resource", "/another_resource"],
            "role_ids": ["my_reader", "my_other_reader"],
            "expected": "study.123456_other_resource_another_resource_my_reader_my_other_reader",
        },
        {
            # resource_paths with multiple slashes
            # (content up and including first slash is removed,
            # following slashed are converted to '.')
            "resource_path": None,
            "resource_paths": [
                "/study/123456",
                "/another_study/98765",
                "other_path/study/7890",
            ],
            "role_ids": ["my_reader", "my_other_reader"],
            "expected": "study.123456_another_study.98765_study.7890_my_reader_my_other_reader",
        },
        {
            # role_ids with slashes (that get removed)
            "resource_path": None,
            "resource_paths": ["/study/123456"],
            "role_ids": ["/role_with_slash", "other_role/with_slash"],
            "expected": "study.123456_role_with_slash_other_rolewith_slash",
        },
    ],
)
def test_get_auto_policy_id(client, data):
    """pass either resource_paths[s] or resource_paths+role_ids"""
    if data["role_ids"]:
        policy_id = get_auto_policy_id(
            resource_path=data["resource_path"],
            resource_paths=data["resource_paths"],
            role_ids=data["role_ids"],
        )
    else:
        policy_id = get_auto_policy_id(
            resource_path=data["resource_path"], resource_paths=data["resource_paths"]
        )
    assert policy_id == data["expected"]


@pytest.mark.parametrize(
    "data",
    [
        {
            # with role_ids without resource_paths or resource_path
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
    ],
)
def test_create_request_with_unallowed_params(client, data):
    """
    When a user attempts to create a request with
        - role_ids without resource_paths
        - both role_ids and policy_id
    a 400 Bad request is returned to the client.
    """
    fake_jwt = "1.2.3"

    res = client.post(
        "/request", json=data, headers={"Authorization": f"bearer {fake_jwt}"}
    )

    assert res.status_code == 400, res.text
    assert data["err_msg"] in res.json()["detail"]


@pytest.mark.parametrize(
    "data",
    [
        {
            # provide resource_path without policy_id to get the default reader policies
            "username": "requestor_user",
            "resource_path": "/study/123456",
            "resource_paths": None,
            "resource_id": "uniqid",
            "resource_display_name": "My Resource",
        },
        {
            # provide resource_paths without role_ids to get the default reader policies
            "username": "requestor_user",
            "resource_path": None,
            "resource_paths": ["/study/123456", "/study/7890", "/another_study/98765"],
            "resource_id": "uniqid",
            "resource_display_name": "My Resource",
        },
        {
            # resource_paths will take precedence over resource_path
            "username": "requestor_user",
            "resource_path": "/older_study/000111",
            "resource_paths": ["/study/123456", "/study/7890", "/another_study/98765"],
            "resource_id": "uniqid",
            "resource_display_name": "My Resource",
        },
    ],
)
def test_create_request_with_resource_path(client, data):
    fake_jwt = "1.2.3"

    if data.get("resource_paths"):
        policy_id = get_auto_policy_id(resource_paths=data["resource_paths"])
    elif data.get("resource_path"):
        policy_id = get_auto_policy_id(data["resource_path"])
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
            # include single item in resource_paths and single item in role_ids
            "username": "requestor_user",
            "resource_paths": ["/study/123456"],
            "role_ids": ["study_registrant"],
            "resource_id": "uniqid",
            "resource_display_name": "My Resource",
        },
        {
            # include multiple resource_paths and role_ids
            "username": "requestor_user",
            "resource_paths": ["/study/123456", "/study/7890", "/another_study/98765"],
            "role_ids": ["study_registrant", "/mds_user", "/study_user"],
            "resource_id": "uniqid",
            "resource_display_name": "My Resource",
        },
        {
            # include resource_path and resource_paths and role_ids
            "username": "requestor_user",
            "resource_path": "/older_study/98765",
            "resource_paths": ["/study/123456", "/study/7890", "/another_study/98765"],
            "role_ids": ["study_registrant", "/mds_user", "/study_user"],
            "resource_id": "uniqid",
            "resource_display_name": "My Resource",
        },
    ],
)
def test_create_request_with_resource_paths_and_role_ids(
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
        "policy_id": get_auto_policy_id(
            resource_paths=data["resource_paths"], role_ids=data["role_ids"]
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


@pytest.mark.parametrize(
    "data",
    [
        {
            # resource_path, no username
            "resource_path": "/my/resource",
            "resource_id": "uniqid",
            "resource_display_name": "My Resource",
        },
        {
            # resource_paths, no username
            "resource_paths": ["/study/123456", "/study/7890", "/another_study/98765"],
            "resource_id": "uniqid",
            "resource_display_name": "My Resource",
        },
        {
            # resource_paths will take precedence over resource_path
            "resource_path": "/older_study/000111",
            "resource_paths": ["/study/123456", "/study/7890", "/another_study/98765"],
            "resource_id": "uniqid",
            "resource_display_name": "My Resource",
        },
    ],
)
def test_create_request_without_username(client, data, access_token_user_only_patcher):
    """
    When a username is not provided in the body, the request is created
    using the username from the provided access token.
    """
    fake_jwt = "1.2.3"

    if data.get("resource_paths"):
        policy_id = get_auto_policy_id(resource_paths=data["resource_paths"])
    elif data.get("resource_path"):
        policy_id = get_auto_policy_id(data["resource_path"])
    else:
        policy_id = None

    # create a request
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
        "policy_id": policy_id,
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
    (username, resource_path) should be unique, except if other
    requests statuses are in DRAFT_STATUSES or FINAL_STATUSES.
    """
    fake_jwt = "1.2.3"

    # create a request
    data = {
        "username": "requestor_user",
        "resource_path": "/my/resource",
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
        "policy_id": get_auto_policy_id(data["resource_path"]),
        "resource_id": data["resource_id"],
        "resource_display_name": data["resource_display_name"],
        "status": config["DEFAULT_INITIAL_STATUS"],
        # just ensure revoke, created_time and updated_time are there:
        "revoke": False,
        "created_time": request_data["created_time"],
        "updated_time": request_data["updated_time"],
    }

    # create a request with the same username and resource_path.
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

    # attempt to create a request with the same username and resource_path.
    # it should not work: the previous request is in progress.
    res = client.post(
        "/request", json=data, headers={"Authorization": f"bearer {fake_jwt}"}
    )
    assert res.status_code == 409, res.text

    # update the orignal request's status to a final status
    status = config["FINAL_STATUSES"][-1]
    res = client.put(f"/request/{request_id}", json={"status": status})
    assert res.status_code == 200, res.text

    # create a request with the same username and resource_path.
    # now it should work: the previous request is not in progress anymore.
    res = client.post(
        "/request", json=data, headers={"Authorization": f"bearer {fake_jwt}"}
    )
    assert res.status_code == 201, res.text


@pytest.mark.parametrize(
    "data",
    [
        {
            # request with resource_path
            "username": "requestor_user",
            "resource_path": "/my/resource",
            "resource_id": "uniqid",
            "resource_display_name": "My Resource",
        },
        {
            # request with resource_paths and role_ids
            "username": "requestor_user",
            "role_ids": ["study_registrant"],
            "resource_paths": ["/study/123456"],
            "resource_id": "uniqid",
            "resource_display_name": "My Resource",
        },
    ],
)
def test_create_request_without_access(
    client,
    mock_arborist_requests,
    list_roles_patcher,
    data,
    access_token_user_only_patcher,
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

    # create a request
    res = client.post(
        "/request",
        json={
            "username": "requestor_user",
            "resource_path": "/my/resource",
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
    assert "is not an allowed request status" in res.json()["detail"]

    # update the request status
    status = config["ALLOWED_REQUEST_STATUSES"][1]
    res = client.put(f"/request/{request_id}", json={"status": status})
    assert res.status_code == 200, res.text
    request_data = res.json()
    assert request_data["status"] == status
    assert request_data["created_time"] == created_time
    assert request_data["updated_time"] != updated_time

    # update the request status with the same status
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
    assert request_data["status"] == status


def test_update_request_without_access(client, mock_arborist_requests):
    fake_jwt = "1.2.3"

    # create a request
    res = client.post(
        "/request",
        json={
            "username": "requestor_user",
            "resource_path": "/my/resource",
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
        "resource_path": "/my/resource",
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
        "resource_path": "/my/resource",
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


def test_no_revoke_requests(client):
    """
    The "revoke" query parameter is not compatible with the "resource_path"
    body field.
    """
    fake_jwt = "1.2.3"

    # attempt to create a request with both 'revoke' and 'resource_path'
    data = {
        "username": "requestor_user",
        "resource_path": "/my/resource",
        "resource_id": "uniqid",
        "resource_display_name": "My Resource",
    }
    res = client.post(
        "/request?revoke", json=data, headers={"Authorization": f"bearer {fake_jwt}"}
    )
    assert res.status_code == 400, res.text
    assert "not compatible" in res.json()["detail"]
