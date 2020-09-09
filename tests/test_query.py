import pytest
from unittest.mock import patch

from requestor.config import config


def test_create_get_and_list_request(client):
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

    # get the request
    res = client.get(f"/request/{request_id}")
    assert res.status_code == 200, res.text
    assert res.json() == request_data

    # list requests
    res = client.get("/request")
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
