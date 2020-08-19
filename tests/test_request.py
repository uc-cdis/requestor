def test_create_and_list_request(client):
    # list requests: empty
    res = client.get("/request")
    assert res.status_code == 200
    assert res.json() == []

    # create a request
    data = {
        "username": "requestor_user",
        "resource_path": "/my/resource",
        "resource_name": "My Resource",
    }
    request_id = None
    res = client.post("/request", json=data)

    try:
        assert res.status_code == 201, res.text
        request_data = res.json()
        request_id = request_data.get("request_id")
        assert request_id, "POST /request did not return a request_id"
        assert request_data == {
            "request_id": request_id,
            "username": data["username"],
            "resource_path": data["resource_path"],
            "resource_name": data["resource_name"],
            "status": "draft",
        }

        # list requests
        res = client.get("/request")
        assert res.status_code == 200, res.text
        assert res.json() == [request_data]
    finally:
        if request_id:
            res = client.delete(f"/request/{request_id}")
            assert res.status_code == 204, res.text


def test_update_request(client):
    # create a request
    request_id = None
    res = client.post(
        "/request",
        json={
            "username": "requestor_user",
            "resource_path": "/my/resource",
            "resource_name": "My Resource",
        },
    )

    try:
        assert res.status_code == 201, res.text
        request_data = res.json()
        request_id = request_data["request_id"]
        assert request_id, "POST /request did not return a request_id"
        assert request_data["status"] == "draft"

        # update the request status
        status = "submitted"
        res = client.put(f"/request/{request_id}", json={"status": status})
        assert res.status_code == 204, res.text
        request_data = res.json()
        assert request_data["status"] == status

        # update the request status and grant access
        status = "approved"  # TODO make that configurable
        res = client.put(f"/request/{request_id}", json={"status": status})
        assert res.status_code == 204, res.text
        request_data = res.json()
        assert request_data["status"] == status
        # TODO check arborist called
    finally:
        if request_id:
            res = client.delete(f"/request/{request_id}")
            assert res.status_code == 204, res.text
