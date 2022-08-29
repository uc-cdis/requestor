"""
We now use `policy_id` instead of `resource_path` in access requests.
This set of tests ensures backwards compatibility.
"""


import pytest

from requestor.arborist import get_auto_policy_id
from requestor.config import config


def test_create_get_and_list_request(client):
    fake_jwt = "1.2.3"

    # list requests: empty
    res = client.get("/request", headers={"Authorization": f"bearer {fake_jwt}"})
    assert res.status_code == 200
    assert res.json() == []

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
        "policy_id": get_auto_policy_id([data["resource_path"]]),
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


def test_get_user_requests(client):
    fake_jwt = "1.2.3"

    # create a request for the current user
    data = {
        "resource_path": "/my/resource",
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
    data["resource_display_name"] = "test_get_user_requests2"
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


def test_list_requests_with_access(client):
    fake_jwt = "1.2.3"

    # create requests
    request_data = {}
    for resource_path in ["/my/resource", "something-i-cant-access"]:
        data = {
            "resource_path": resource_path,
            "resource_id": "uniqid",
            "resource_display_name": "My Resource",
        }
        res = client.post(
            "/request", json=data, headers={"Authorization": f"bearer {fake_jwt}"}
        )
        assert res.status_code == 201, res.text
        request_data[resource_path] = res.json()

    # list requests
    # the mocked auth_mapping response in mock_arborist_requests does not
    # include "something-i-cant-access", so it should not be returned
    res = client.get("/request", headers={"Authorization": f"bearer {fake_jwt}"})
    assert res.status_code == 200, res.text
    assert res.json() == [request_data["/my/resource"]]


@pytest.mark.parametrize(
    "test_data",
    [
        {
            "resource_path": "/a",
            "should_match": True,
        },
        {
            "resource_path": "/a/b",
            "should_match": True,
        },
        {
            "resource_path": "/a/b/",
            "should_match": True,
        },
        {
            "resource_path": "/a/b/d",
            "should_match": False,
        },
        {
            "resource_path": "/a/bc",
            "should_match": False,
        },
        {
            "resource_path": "/a/bc/d",
            "should_match": False,
        },
        {
            "resource_path": "/e",
            "should_match": False,
        },
    ],
)
def test_check_user_resource_paths_prefixes(client, list_policies_patcher, test_data):
    """
    Test if having requested access to the resource path in
    test_data["resource_path"] means having requested access to
    resource_path_to_match (arborist paths logic).
    """
    fake_jwt = "1.2.3"
    resource_path_to_match = "/a/b"

    # create request
    data = {
        "resource_path": test_data["resource_path"],
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


@pytest.mark.parametrize("test_data", [{"resource_paths": ["/a/b", "/c"]}])
def test_check_user_resource_paths_multiple(client, list_policies_patcher, test_data):
    fake_jwt = "1.2.3"
    existing_resource_paths = test_data["resource_paths"]
    expected_matches = {
        "/a/b": True,
        "/c/d": True,  # if i request all of /c, i also request /c/d
        "/a": False,  # if i request /a/b, i don't request all of /a
        "/e/f": False,
    }

    # create requests
    for resource_path in existing_resource_paths:
        data = {
            "resource_path": resource_path,
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


def test_check_user_resource_paths_username(client):
    fake_jwt = "1.2.3"

    resource_path_to_match = "/a/b"

    # create a request that matches but is for a different user
    data = {
        "username": "not-the-same-user",
        "resource_path": resource_path_to_match,
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
            "resource_path": "/a",
            "status": config["DRAFT_STATUSES"][0],
            "should_match": False,
        },
        {
            "resource_path": "/a",
            "status": config["FINAL_STATUSES"][0],
            "should_match": False,
        },
        {
            "resource_path": "/a",
            "status": "INTERMEDIATE_STATUS",
            "should_match": True,
        },
    ],
)
def test_check_user_resource_paths_status(client, list_policies_patcher, test_data):
    fake_jwt = "1.2.3"
    resource_path_to_match = test_data["resource_path"]

    # create a request with the status to test
    data = {
        "resource_path": resource_path_to_match,
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
    data = {"resource_paths": [resource_path_to_match]}
    res = client.post(
        "/request/user_resource_paths",
        json=data,
        headers={"Authorization": f"bearer {fake_jwt}"},
    )
    assert res.status_code == 200, res.text
    assert res.json() == {resource_path_to_match: test_data["should_match"]}
