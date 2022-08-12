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
            headers={},
        )
        mock_requests.get.assert_called_once_with(
            "https://xyz_system/access", data=None, headers={}
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
            headers={},
        )
        mock_requests.get.assert_called_once_with(
            "https://xyz_system/access", data=None, headers={}
        )

    assert res.status_code == 200, res.text
    request_data = res.json()
    assert request_data["status"] == "APPROVED"


def test_create_request_with_authed_external_call(client):
    # create a request
    data = {
        "username": "requestor_user",
        "policy_id": "test-policy-with-authed-external-call",
        "resource_id": "uniqid",
        "resource_display_name": "My Resource",
        "status": "CREATED",
    }
    mock_access_token = "a.b.c"
    conf = config["CREDENTIALS"]["client_creds_for_external_call"]["config"]
    with mock.patch("requestor.request_utils.requests") as mock_requests:
        mock_requests.post.return_value.json = lambda: {
            "access_token": mock_access_token
        }
        res = client.post("/request", json=data)

        # call to get credentials
        mock_requests.post.assert_called_once_with(
            conf["url"],
            data={"grant_type": "client_credentials", "scope": conf["scope"]},
            auth=(conf["client_id"], conf["client_secret"]),
        )

        # external call with credentials
        mock_requests.get.assert_called_once_with(
            "https://xyz_system/access",
            data=None,
            headers={"authorization": f"bearer {mock_access_token}"},
        )

    assert res.status_code == 201, res.text
    request_data = res.json()
    request_id = request_data.get("request_id")
    assert request_id, "POST /request did not return a request_id"


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
            headers={},
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


def test_backoff_retry(client):
    data = {
        "username": "requestor_user",
        "policy_id": "test-policy-with-redirect-and-external-call",
        "resource_id": "uniqid",
        "resource_display_name": "My Resource",
        "status": "CREATED",
    }
    with mock.patch("requestor.request_utils.requests") as mock_requests:
        mock_requests.post.return_value = "this will cause an exception"
        client.post("/request", json=data)
        assert mock_requests.post.call_count == config["DEFAULT_MAX_RETRIES"]


def test_create_request_failure_revert(client, access_token_user_only_patcher):
    """
    If something goes wrong during an external call, access should not be
    granted, the request should not be created and we should get a 500.
    """
    fake_jwt = "1.2.3"

    data = {
        "username": "requestor_user",
        "policy_id": "test-policy-with-external-calls",
        "resource_id": "uniqid",
        "resource_display_name": "test_create_request_failure_revert",
        "status": "APPROVED",
    }
    with mock.patch("requestor.request_utils.requests") as mock_requests:
        mock_requests.post.return_value = "this will cause an exception"
        with mock.patch(
            "requestor.routes.manage.grant_or_revoke_arborist_policy"
        ) as mock_arborist:
            res = client.post("/request", json=data)
            assert res.status_code == 500, res.text
            assert mock_arborist.call_count == 2
            # first a call with revoke=False:
            assert mock_arborist.call_args_list[0][0][3] == False
            # then a call with revoke=True to revert the granted access:
            assert mock_arborist.call_args_list[1][0][3] == True

    # the request should not have been created
    res = client.get(
        "/request?resource_display_name=test_create_request_failure_revert",
        headers={"Authorization": f"bearer {fake_jwt}"},
    )
    assert res.status_code == 200
    assert (
        len(res.json()) == 0
    ), "The request should have been deleted after the post-status-update action failure"


def test_update_request_failure_revert(client):
    """
    If something goes wrong during an external call, access should not be
    granted, the request status should not be updated and we should get a 500.
    """
    fake_jwt = "1.2.3"

    data = {
        "username": "requestor_user",
        "policy_id": "test-policy-with-external-calls",
        "resource_id": "uniqid",
        "resource_display_name": "test_update_request_failure_reverte",
        "status": "INTERMEDIATE_STATUS",
    }
    with mock.patch("requestor.request_utils.requests") as mock_requests:
        res = client.post("/request", json=data)
        assert res.status_code == 201, res.text
        request_id = res.json().get("request_id")
        assert request_id, "POST /request did not return a request_id"

        # update the request status
        mock_requests.post.return_value = "this will cause an exception"
        with mock.patch(
            "requestor.routes.manage.grant_or_revoke_arborist_policy"
        ) as mock_arborist:
            res = client.put(f"/request/{request_id}", json={"status": "APPROVED"})
            assert res.status_code == 500, res.text
            assert mock_arborist.call_count == 2
            # first a call with revoke=False:
            assert mock_arborist.call_args_list[0][0][3] == False
            # then a call with revoke=True to revert the granted access:
            assert mock_arborist.call_args_list[1][0][3] == True

    # the request status should not have been updated
    res = client.get(
        f"/request/{request_id}", headers={"Authorization": f"bearer {fake_jwt}"}
    )
    assert res.status_code == 200
    assert (
        res.json()["status"] == data["status"]
    ), "The request status update should have been reverted after the post-status-update action failure"
