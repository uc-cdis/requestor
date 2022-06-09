import mock

from requestor.arborist import get_auto_policy_id_for_resource_path
from requestor.config import config


def test_create_request_with_redirect_policy(client):
    """
    When a redirect is configured for the requested resource, a
    redirect URL should be returned to the client.
    (creating with policy)
    """
    # create a request
    data = {
        "username": "requestor_user",
        "policy_id": "test-policy-with-redirect",
        "resource_id": "uniqid",
        "resource_display_name": "My Resource",
    }
    res = client.post("/request", json=data)

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
        "redirect_url": f"http://localhost?something=&request_id={request_id}&resource_id={data['resource_id']}&resource_display_name=My+Resource",
        # just ensure revoke, created_time and updated_time are there:
        "revoke": False,
        "created_time": request_data["created_time"],
        "updated_time": request_data["updated_time"],
    }

    # TODO assert external call not called


def test_create_request_with_redirect_resource_paths(client):
    """
    When a redirect is configured for the requested resource, a
    redirect URL should be returned to the client.
    (creating with resource_paths)
    """
    # create a request
    data = {
        "username": "requestor_user",
        "resource_path": "/resource-with-redirect/resource",
        "resource_id": "uniqid",
        "resource_display_name": "My Resource",
    }
    res = client.post("/request", json=data)

    assert res.status_code == 201, res.text
    request_data = res.json()
    request_id = request_data.get("request_id")
    assert request_id, "POST /request did not return a request_id"
    assert request_data == {
        "request_id": request_id,
        "username": data["username"],
        "policy_id": get_auto_policy_id_for_resource_path(data["resource_path"]),
        "resource_id": data["resource_id"],
        "resource_display_name": data["resource_display_name"],
        "status": config["DEFAULT_INITIAL_STATUS"],
        "redirect_url": f"http://localhost?something=&request_id={request_id}&resource_id={data['resource_id']}&resource_display_name=My+Resource",
        # just ensure revoke, created_time and updated_time are there:
        "revoke": False,
        "created_time": request_data["created_time"],
        "updated_time": request_data["updated_time"],
    }

    # TODO assert external call not called


def test_create_request_with_external_calls(client):
    # create a request
    data = {
        "username": "requestor_user",
        "policy_id": "test-policy-with-external-calls",
        "resource_id": "uniqid",
        "resource_display_name": "My Resource",
        "status": "APPROVED",
    }
    with mock.patch("requestor.request_utils.requests") as mock_requests:
        res = client.post("/request", json=data)
        mock_requests.post.assert_called_once_with(
            "https://abc_system/access",
            data={"dataset": data["resource_id"], "username": data["username"]},
        )
        mock_requests.get.assert_called_once_with(
            "https://xyz_system/access", data=None
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
        "status": data["status"],
        # just ensure revoke, created_time and updated_time are there:
        "revoke": False,
        "created_time": request_data["created_time"],
        "updated_time": request_data["updated_time"],
    }


def test_update_request_with_external_calls(client):
    # create a request
    data = {
        "username": "requestor_user",
        "policy_id": "test-policy-with-external-calls",
        "resource_id": "uniqid",
        "resource_display_name": "My Resource",
    }
    res = client.post("/request", json=data)
    assert res.status_code == 201, res.text
    request_id = res.json().get("request_id")
    assert request_id, "POST /request did not return a request_id"

    with mock.patch("requestor.request_utils.requests") as mock_requests:
        # update the request status
        res = client.put(f"/request/{request_id}", json={"status": "APPROVED"})
        mock_requests.post.assert_called_once_with(
            "https://abc_system/access",
            data={"dataset": data["resource_id"], "username": data["username"]},
        )
        mock_requests.get.assert_called_once_with(
            "https://xyz_system/access", data=None
        )

    assert res.status_code == 200, res.text
    request_data = res.json()
    assert request_data["status"] == "APPROVED"


def test_create_request_with_redirect_and_external_call(client):
    # create a request
    data = {
        "username": "requestor_user",
        "policy_id": "test-policy-with-redirect-and-external-call",
        "resource_id": "uniqid",
        "resource_display_name": "My Resource",
        "status": "CREATED",
    }
    with mock.patch("requestor.request_utils.requests") as mock_requests:
        res = client.post("/request", json=data)
        mock_requests.post.assert_called_once_with(
            "https://abc_system/access",
            data={"dataset": data["resource_id"], "username": data["username"]},
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
        "status": data["status"],
        "redirect_url": f"http://localhost?something=&request_id={request_id}&resource_id={data['resource_id']}&resource_display_name=My+Resource",
        # just ensure revoke, created_time and updated_time are there:
        "revoke": False,
        "created_time": request_data["created_time"],
        "updated_time": request_data["updated_time"],
    }
