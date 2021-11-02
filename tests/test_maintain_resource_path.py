"""
We now use `policy_id` instead of `resource_path` in access requests.
This set of tests ensures backwards compatibility.
"""


from requestor import arborist
from requestor.config import config


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
        "policy_id": arborist.get_auto_policy_id_for_resource_path(
            data["resource_path"]
        ),
        "resource_id": data["resource_id"],
        "resource_display_name": data["resource_display_name"],
        "status": config["DEFAULT_INITIAL_STATUS"],
        "redirect_url": f"http://localhost?something=&request_id={request_id}&resource_id=uniqid&resource_display_name=My+Resource",
        # just ensure revoke, created_time and updated_time are there:
        "revoke": False,
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
        "policy_id": arborist.get_auto_policy_id_for_resource_path(
            data["resource_path"]
        ),
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
        "policy_id": arborist.get_auto_policy_id_for_resource_path(
            data["resource_path"]
        ),
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


def test_create_request_without_access(client, mock_arborist_requests):
    fake_jwt = "1.2.3"
    mock_arborist_requests(authorized=False)

    # attempt to create a request
    data = {
        "username": "requestor_user",
        "resource_path": "/my/resource",
        "resource_id": "uniqid",
        "resource_display_name": "My Resource",
    }
    res = client.post(
        "/request", json=data, headers={"Authorization": f"bearer {fake_jwt}"}
    )
    assert res.status_code == 403, res.text

    # check that no request was created
    res = client.get("/request", headers={"Authorization": f"bearer {fake_jwt}"})
    assert res.status_code == 200, res.text
    assert res.json() == []


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
    created_time = request_data["created_time"]
    updated_time = request_data["updated_time"]

    # try to update the request with a status that's not allowed
    status = "this is not allowed"
    res = client.put(f"/request/{request_id}", json={"status": status})
    assert res.status_code == 400, res.text

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

    # attempt to create a request with the 'revoke' query parameter
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
