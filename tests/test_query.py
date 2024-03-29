import pytest

from requestor.config import config


def test_create_and_get_request(client):
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

    # get the request
    res = client.get(f"/request/{request_id}")
    assert res.status_code == 200, res.text
    assert res.json() == request_data


def test_create_and_list_request(client):
    fake_jwt = "1.2.3"

    # list requests: empty
    res = client.get("/request", headers={"Authorization": f"bearer {fake_jwt}"})
    assert res.status_code == 200
    assert res.json() == []

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

    # list requests
    res = client.get("/request", headers={"Authorization": f"bearer {fake_jwt}"})
    assert res.status_code == 200, res.text
    assert res.json() == [request_data]


def test_get_request_without_access(client, mock_arborist_requests):
    """
    Test that an unauthorized GET for a request that exists returns the
    same response as a GET for a request that doesn't exist.
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

    # get the request
    res = client.get(f"/request/{request_id}")
    assert res.status_code == 200, res.text
    assert res.json() == request_data

    # get a request that doesn't exist
    uuid = "571c6a1a-f21f-11ea-adc1-0242ac120002"
    res = client.get(f"/request/{uuid}")
    assert res.status_code == 404, res.text
    not_found_err = res.json()

    mock_arborist_requests(authorized=False)

    # attempt to get a request that exists without having access
    res = client.get(f"/request/{request_id}")
    assert res.status_code == 404, res.text
    unauthorized_err = res.json()

    assert not_found_err == unauthorized_err


def test_get_filtered_requests(client):
    fake_jwt = "1.2.3"
    filtered_requests = []

    # create a request with status = APPROVED and revoke = False
    data = {
        "username": "other_user",
        "policy_id": "test-policy",
        "resource_id": "draft_uniqid",
        "revoke": "False",
        "resource_display_name": "My Draft Resource",
        "status": "APPROVED",
    }
    res = client.post(
        "/request", json=data, headers={"Authorization": f"bearer {fake_jwt}"}
    )
    assert res.status_code == 201, res.text
    filtered_requests.append(res.json())
    datetime = filtered_requests[0]["created_time"]

    # create a request with a different policy_id, status = APPROVED and revoke = False
    data = {
        "username": "other_user",
        "policy_id": "my.resource_accessor",
        "resource_id": "active_uniqid",
        "revoke": "False",
        "resource_display_name": "My Active Resource",
        "status": "APPROVED",
    }
    res = client.post(
        "/request", json=data, headers={"Authorization": f"bearer {fake_jwt}"}
    )
    assert res.status_code == 201, res.text
    filtered_requests.append(res.json())

    # create a request with a different policy_id and status but with revoke=False
    data = {
        "username": "other_user",
        "policy_id": "test-policy-with-redirect",
        "resource_id": "final",
        "resource_display_name": "My Final Resource",
        "revoke": "False",
        "status": "CANCELLED",
    }
    res = client.post(
        "/request", json=data, headers={"Authorization": f"bearer {fake_jwt}"}
    )
    assert res.status_code == 201, res.text

    # check that only we get the requests which match the filtered criteria
    res = client.get(
        "/request?active&revoke=False",
        headers={"Authorization": f"bearer {fake_jwt}"},
    )
    assert res.status_code == 200, res.text
    assert res.json() == filtered_requests

    # Add multiple values to a single key to test 'or' functionality alongside 'and'
    res = client.get(
        f"/request?policy_id=test-policy&policy_id=test-policy-with-redirect&status=APPROVED&created_time={datetime}",
        headers={"Authorization": f"bearer {fake_jwt}"},
    )
    assert res.status_code == 200, res.text
    assert res.json() == filtered_requests[:1]

    # Add a filter with an invalid key
    res = client.get(
        f"/request?name=dummy",
        headers={"Authorization": f"bearer {fake_jwt}"},
    )
    assert res.status_code == 400, res.text

    # Add a filter with an invalid value to the date key
    res = client.get(
        f"/request?created_time=23/05/2020",
        headers={"Authorization": f"bearer {fake_jwt}"},
    )
    assert res.status_code == 400, res.text


def test_get_user_requests(client, access_token_user_only_patcher):
    fake_jwt = "1.2.3"

    # create a request for the current user
    data = {
        "policy_id": "test-policy",
        "resource_id": "uniqid",
        "resource_display_name": "My Resource",
    }
    res = client.post(
        "/request", json=data, headers={"Authorization": f"bearer {fake_jwt}"}
    )
    assert res.status_code == 201, res.text
    user_request = res.json()

    # create a request for a different user
    data["username"] = "not-the-same-user"
    res = client.post(
        "/request", json=data, headers={"Authorization": f"bearer {fake_jwt}"}
    )
    assert res.status_code == 201, res.text

    # check that only the request created for the current user is listed
    res = client.get("/request/user", headers={"Authorization": f"bearer {fake_jwt}"})
    assert res.status_code == 200, res.text
    assert res.json() == [user_request]

    # attempt to list requests without auth headers
    res = client.get("/request/user")
    assert res.status_code == 401, res.text


def test_get_active_user_requests(client, access_token_user_only_patcher):
    fake_jwt = "1.2.3"

    # create a request with a DRAFT status
    data = {
        "policy_id": "test-policy",
        "resource_id": "draft_uniqid",
        "resource_display_name": "My Draft Resource",
        "status": config["DRAFT_STATUSES"][0],
    }
    res = client.post(
        "/request", json=data, headers={"Authorization": f"bearer {fake_jwt}"}
    )
    assert res.status_code == 201, res.text
    active_request1 = res.json()

    # create a request for the current user with an "Active status"
    data = {
        "policy_id": "test-existing-policy",
        "resource_id": "active_uniqid",
        "resource_display_name": "My Active Resource",
        "status": "APPROVED",
    }
    res = client.post(
        "/request", json=data, headers={"Authorization": f"bearer {fake_jwt}"}
    )
    assert res.status_code == 201, res.text
    active_request2 = res.json()

    # create a request with a FINAL status
    data = {
        "policy_id": "test-existing-policy-2",
        "resource_id": "final",
        "resource_display_name": "My Final Resource",
        "status": config["FINAL_STATUSES"][0],
    }
    res = client.post(
        "/request", json=data, headers={"Authorization": f"bearer {fake_jwt}"}
    )
    assert res.status_code == 201, res.text
    final_request = res.json()

    # active=False - check that all the requests are listed
    res = client.get("/request/user", headers={"Authorization": f"bearer {fake_jwt}"})
    assert res.status_code == 200, res.text
    assert res.json() == [active_request1, active_request2, final_request]

    # active=True - check that only the active requests are listed
    res = client.get(
        "/request/user?active", headers={"Authorization": f"bearer {fake_jwt}"}
    )
    assert res.status_code == 200, res.text
    assert res.json() == [active_request1, active_request2]


def test_get_filtered_user_requests(client, access_token_user_only_patcher):
    fake_jwt = "1.2.3"
    filtered_requests = []

    # create a request with status = APPROVED and revoke = False
    data = {
        "policy_id": "test-policy",
        "resource_id": "draft_uniqid",
        "revoke": "False",
        "resource_display_name": "My Draft Resource",
        "status": "APPROVED",
    }
    res = client.post(
        "/request", json=data, headers={"Authorization": f"bearer {fake_jwt}"}
    )
    assert res.status_code == 201, res.text
    filtered_requests.append(res.json())
    datetime = filtered_requests[0]["created_time"]

    # create a request with a different policy_id, status = APPROVED and revoke = False
    data = {
        "policy_id": "test-existing-policy",
        "resource_id": "active_uniqid",
        "revoke": "False",
        "resource_display_name": "My Active Resource",
        "status": "APPROVED",
    }
    res = client.post(
        "/request", json=data, headers={"Authorization": f"bearer {fake_jwt}"}
    )
    assert res.status_code == 201, res.text
    filtered_requests.append(res.json())

    # create a request with a different policy_id and status but with revoke=False
    data = {
        "policy_id": "test-existing-policy-2",
        "resource_id": "final",
        "resource_display_name": "My Final Resource",
        "revoke": "False",
        "status": "CANCELLED",
    }
    res = client.post(
        "/request", json=data, headers={"Authorization": f"bearer {fake_jwt}"}
    )
    assert res.status_code == 201, res.text

    # check that only we get the requests which match the filtered criteria
    res = client.get(
        "/request/user?active&revoke=False",
        headers={"Authorization": f"bearer {fake_jwt}"},
    )
    assert res.status_code == 200, res.text
    assert res.json() == filtered_requests

    # Add multiple values to a single key to test 'or' functionality alongside 'and'
    res = client.get(
        f"/request/user?policy_id=test-policy&policy_id=test-existing-policy&status=APPROVED&created_time={datetime}",
        headers={"Authorization": f"bearer {fake_jwt}"},
    )
    assert res.status_code == 200, res.text
    assert res.json() == filtered_requests[:1]

    # Add a filter with an invalid key
    res = client.get(
        f"/request/user?name=dummy",
        headers={"Authorization": f"bearer {fake_jwt}"},
    )
    assert res.status_code == 400, res.text

    # Add a filter with an invalid value to the date key
    res = client.get(
        f"/request/user?created_time=23/05/2020",
        headers={"Authorization": f"bearer {fake_jwt}"},
    )
    assert res.status_code == 400, res.text


def test_list_requests_with_access(client):
    fake_jwt = "1.2.3"

    # create requests
    request_data = {}
    for policy_id in ["test-policy", "test-policy-i-cant-access"]:
        data = {
            "username": "requestor_user",
            "policy_id": policy_id,
            "resource_id": "uniqid",
            "resource_display_name": "My Resource",
        }
        res = client.post(
            "/request", json=data, headers={"Authorization": f"bearer {fake_jwt}"}
        )
        assert res.status_code == 201, res.text
        request_data[policy_id] = res.json()

    # list requests
    # the mocked auth_mapping response in mock_arborist_requests does not
    # include "test-policy-i-cant-access"'s resource paths, so it should not
    # be returned
    res = client.get("/request", headers={"Authorization": f"bearer {fake_jwt}"})
    assert res.status_code == 200, res.text
    assert res.json() == [request_data["test-policy"]]


@pytest.mark.parametrize(
    "test_data",
    [
        {
            "policy_id": "test-policy",
            "resource_path": "/a",
            "should_match": True,
        },
        {
            "policy_id": "test-policy",
            "resource_path": "/a/b",
            "should_match": True,
        },
        {
            "policy_id": "test-policy",
            "resource_path": "/a/b/",
            "should_match": True,
        },
        {
            "policy_id": "test-policy",
            "resource_path": "/a/b/d",
            "should_match": False,
        },
        {
            "policy_id": "test-policy",
            "resource_path": "/a/bc",
            "should_match": False,
        },
        {
            "policy_id": "test-policy",
            "resource_path": "/a/bc/d",
            "should_match": False,
        },
        {
            "policy_id": "test-policy",
            "resource_path": "/e",
            "should_match": False,
        },
    ],
)
def test_check_user_resource_paths_prefixes(
    client, list_policies_patcher, test_data, access_token_user_only_patcher
):
    """
    Test if having requested access to the resource path in
    test_data["resource_path"] means having requested access to
    resource_path_to_match (arborist paths logic).
    """
    fake_jwt = "1.2.3"
    resource_path_to_match = "/a/b"

    # create request
    data = {
        "username": "requestor_user",
        "policy_id": test_data["policy_id"],
        "resource_id": "uniqid",
        "resource_display_name": "My Resource",
        # skip the draft status so that the access is not re-requestable
        "status": "INTERMEDIATE_STATUS",
    }
    res = client.post(
        "/request", json=data, headers={"Authorization": f"bearer {fake_jwt}"}
    )
    assert res.status_code == 201, res.text

    # check whether the resource path matches the request we created
    data = {"resource_paths": [resource_path_to_match]}
    res = client.post(
        "/request/user_resource_paths",
        json=data,
        headers={"Authorization": f"bearer {fake_jwt}"},
    )

    assert res.status_code == 200, res.text
    err_msg = f"{resource_path_to_match} should {'' if test_data['should_match'] else 'not '}match {test_data['resource_path']}"
    expected = {resource_path_to_match: test_data["should_match"]}
    assert res.json() == expected, err_msg


@pytest.mark.parametrize(
    "test_data",
    [
        {
            "policy_id": "test-policy",
            "resource_paths": ["/a/b", "/c"],
        }
    ],
)
def test_check_user_resource_paths_multiple(
    client, list_policies_patcher, test_data, access_token_user_only_patcher
):
    fake_jwt = "1.2.3"
    expected_matches = {
        "/a/b": True,
        "/c/d": True,  # if i request all of /c, i also request /c/d
        "/a": False,  # if i request /a/b, i don't request all of /a
        "/e/f": False,
    }

    # create request
    data = {
        "policy_id": test_data["policy_id"],
        "resource_id": "uniqid",
        "resource_display_name": "My Resource",
        # skip the draft status so that the access is not re-requestable
        "status": "INTERMEDIATE_STATUS",
    }
    res = client.post(
        "/request", json=data, headers={"Authorization": f"bearer {fake_jwt}"}
    )
    assert res.status_code == 201, res.text

    # check whether the resource path matches the requests we created
    data = {"resource_paths": list(expected_matches.keys())}
    res = client.post(
        "/request/user_resource_paths",
        json=data,
        headers={"Authorization": f"bearer {fake_jwt}"},
    )
    assert res.status_code == 200, res.text
    assert res.json() == expected_matches


def test_check_user_resource_paths_username(client, access_token_user_only_patcher):
    fake_jwt = "1.2.3"

    resource_path_to_match = "/a/b"

    # create a request that matches but is for a different user
    data = {
        "username": "not-the-same-user",
        "policy_id": "test-policy",
        "resource_id": "uniqid",
        "resource_display_name": "My Resource",
        # skip the draft status so that the access is not re-requestable
        "status": "INTERMEDIATE_STATUS",
    }
    res = client.post(
        "/request", json=data, headers={"Authorization": f"bearer {fake_jwt}"}
    )
    assert res.status_code == 201, res.text

    # check that the resource path does not match the request we created
    data = {"resource_paths": [resource_path_to_match]}
    res = client.post(
        "/request/user_resource_paths",
        json=data,
        headers={"Authorization": f"bearer {fake_jwt}"},
    )
    assert res.status_code == 200, res.text
    assert res.json() == {resource_path_to_match: False}


@pytest.mark.parametrize(
    "test_data",
    [
        {
            "policy_id": "test-policy",
            "resource_path": "/a",
            "status": config["DRAFT_STATUSES"][0],
            "should_match": False,
        },
        {
            "policy_id": "test-policy",
            "resource_path": "/a",
            "status": config["FINAL_STATUSES"][0],
            "should_match": False,
        },
        {
            "policy_id": "test-policy",
            "resource_path": "/a",
            "status": "INTERMEDIATE_STATUS",
            "should_match": True,
        },
    ],
)
def test_check_user_resource_paths_status(
    client, list_policies_patcher, test_data, access_token_user_only_patcher
):
    fake_jwt = "1.2.3"

    # create a request with the status to test
    data = {
        "policy_id": test_data["policy_id"],
        "resource_id": "uniqid",
        "resource_display_name": "My Resource",
        "status": test_data["status"],
    }
    res = client.post(
        "/request", json=data, headers={"Authorization": f"bearer {fake_jwt}"}
    )
    assert res.status_code == 201, res.text

    # check whether there is a match
    # (True if the access is re-requestable, False otherwise)
    data = {"resource_paths": [test_data["resource_path"]]}
    res = client.post(
        "/request/user_resource_paths",
        json=data,
        headers={"Authorization": f"bearer {fake_jwt}"},
    )
    assert res.status_code == 200, res.text
    assert res.json() == {test_data["resource_path"]: test_data["should_match"]}


@pytest.mark.parametrize(
    "test_data",
    [
        {
            "policy_id": "test-policy",
            "resource_path": "/a",
            "permissions": [
                {
                    "id": "original-permissions-1",
                    "description": "",
                    "action": {
                        "service": "*",
                        "method": "write",
                    },
                },
                {
                    "id": "original-permissions-2",
                    "description": "",
                    "action": {
                        "service": "*",
                        "method": "delete",
                    },
                },
            ],
        },
    ],
)
def test_check_permissions_mismatch(
    client, list_policies_patcher, test_data, access_token_user_only_patcher
):
    fake_jwt = "1.2.3"

    # create a request with an active status
    data = {
        "policy_id": test_data["policy_id"],
        "resource_id": "uniqid",
        "resource_display_name": "My Resource",
        "status": "APPROVED",
    }
    res = client.post(
        "/request", json=data, headers={"Authorization": f"bearer {fake_jwt}"}
    )
    assert res.status_code == 201, res.text

    # * Permissions provided and matching
    data = {
        "resource_paths": [test_data["resource_path"]],
        "permissions": ["original-permissions-1", "original-permissions-2"],
    }
    res = client.post(
        "/request/user_resource_paths",
        json=data,
        headers={"Authorization": f"bearer {fake_jwt}"},
    )
    assert res.status_code == 200, res.text
    assert res.json() == {test_data["resource_path"]: True}

    # * Permissions not provided and not matching -- verified against default permissions
    data = {
        "resource_paths": [test_data["resource_path"]],
    }
    res = client.post(
        "/request/user_resource_paths",
        json=data,
        headers={"Authorization": f"bearer {fake_jwt}"},
    )
    assert res.status_code == 200, res.text
    assert res.json() == {test_data["resource_path"]: False}

    # * Permissions provided and not matching -- partial mismatch
    data = {
        "resource_paths": [test_data["resource_path"]],
        "permissions": ["original-permissions-1", "mismatched-permissions-2"],
    }
    res = client.post(
        "/request/user_resource_paths",
        json=data,
        headers={"Authorization": f"bearer {fake_jwt}"},
    )
    assert res.status_code == 200, res.text
    assert res.json() == {test_data["resource_path"]: False}

    # * Permissions provided and not matching -- complete mismatch
    data = {
        "resource_paths": [test_data["resource_path"]],
        "permissions": ["mismatched-permissions-1", "mismatched-permissions-2"],
    }
    res = client.post(
        "/request/user_resource_paths",
        json=data,
        headers={"Authorization": f"bearer {fake_jwt}"},
    )
    assert res.status_code == 200, res.text
    assert res.json() == {test_data["resource_path"]: False}
