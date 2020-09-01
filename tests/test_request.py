import pytest
from unittest.mock import patch

from requestor.config import config


@pytest.fixture(autouse=True)
def clean_db(client):
    # before each test, delete all existing requests from the DB
    res = client.get("/request")
    assert res.status_code == 200
    for r in res.json():
        res = client.delete("/request/" + r["request_id"])

    yield


def test_create_and_list_request(client):
    fake_jwt = "1.2.3"

    # list requests: empty
    res = client.get("/request")
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
        "resource_path": data["resource_path"],
        "resource_id": data["resource_id"],
        "resource_display_name": data["resource_display_name"],
        "status": config["DEFAULT_INITIAL_STATUS"],
        # just ensure created_time and updated_time are there:
        "created_time": request_data["created_time"],
        "updated_time": request_data["updated_time"],
    }

    # list requests
    res = client.get("/request")
    assert res.status_code == 200, res.text
    assert res.json() == [request_data]


def test_create_request_with_redirect(client):
    """
    When a redirect is configured for the requested resource, a
    redirect URL should be returned to the client.
    """
    fake_jwt = "1.2.3"

    # create a request
    data = {
        "username": "requestor_user",
        "resource_path": "/resource-with-redirect/resource",
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
        "resource_path": data["resource_path"],
        "resource_id": data["resource_id"],
        "resource_display_name": data["resource_display_name"],
        "status": config["DEFAULT_INITIAL_STATUS"],
        "redirect_url": f"http://localhost?something=&request_id={request_id}&resource_id=uniqid&resource_display_name=My+Resource",
        # just ensure created_time and updated_time are there:
        "created_time": request_data["created_time"],
        "updated_time": request_data["updated_time"],
    }


def test_create_request_without_username(client):
    """
    When a username is not provided in the body, the request is created
    using the username from the provided access token.
    """
    fake_jwt = "1.2.3"

    # create a request
    data = {
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
        "username": "requestor-user",  # username from access_token_patcher
        "resource_path": data["resource_path"],
        "resource_id": data["resource_id"],
        "resource_display_name": data["resource_display_name"],
        "status": config["DEFAULT_INITIAL_STATUS"],
        # just ensure created_time and updated_time are there:
        "created_time": request_data["created_time"],
        "updated_time": request_data["updated_time"],
    }


def test_create_duplicate_request(client):
    """
    Users can only request access to a resource once.
    (username, resource_path) should be unique.
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
        "resource_path": data["resource_path"],
        "resource_id": data["resource_id"],
        "resource_display_name": data["resource_display_name"],
        "status": config["DEFAULT_INITIAL_STATUS"],
        # just ensure created_time and updated_time are there:
        "created_time": request_data["created_time"],
        "updated_time": request_data["updated_time"],
    }

    # create a request with the same username and resource_path
    res = client.post(
        "/request", json=data, headers={"Authorization": f"bearer {fake_jwt}"}
    )
    assert res.status_code == 409, res.text

    # update the orignal request's status to a final status
    status = config["FINAL_STATUSES"][-1]
    res = client.put(f"/request/{request_id}", json={"status": status})
    assert res.status_code == 204, res.text

    # create a request with the same username and resource_path
    # now it should work: the previous request is not in progress anymore
    res = client.post(
        "/request", json=data, headers={"Authorization": f"bearer {fake_jwt}"}
    )
    assert res.status_code == 201, res.text


def test_update_request(client):
    """
    When updating the request with the GRANT_ACCESS_STATUS, a call
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

    # update the request status
    status = config["ALLOWED_REQUEST_STATUSES"][1]
    res = client.put(f"/request/{request_id}", json={"status": status})
    assert res.status_code == 204, res.text
    request_data = res.json()
    assert request_data["status"] == status
    assert request_data["created_time"] == created_time
    assert request_data["updated_time"] != updated_time

    # update the request status and grant access
    status = config["GRANT_ACCESS_STATUS"]
    with patch("gen3authz.client.arborist.client.httpx.Client.request") as mock_request:
        mock_request.return_value.status_code = 204
        res = client.put(f"/request/{request_id}", json={"status": status})
        assert mock_request.called
    assert res.status_code == 204, res.text
    request_data = res.json()
    assert request_data["status"] == status


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
    assert request_data == {
        "request_id": request_id,
        "username": data["username"],
        "resource_path": data["resource_path"],
        "resource_id": data["resource_id"],
        "resource_display_name": data["resource_display_name"],
        "status": config["DEFAULT_INITIAL_STATUS"],
        # just ensure created_time and updated_time are there:
        "created_time": request_data["created_time"],
        "updated_time": request_data["updated_time"],
    }

    # list requests
    res = client.get("/request")
    assert res.status_code == 200, res.text
    assert res.json() == [request_data]

    # create a request with the same username and resource_path
    res = client.delete(f"/request/{request_id}")
    assert res.status_code == 204, res.text

    # list requests: empty
    res = client.get("/request")
    assert res.status_code == 200
    assert res.json() == []
