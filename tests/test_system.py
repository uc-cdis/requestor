def test_status_endpoint(client):
    res = client.get("/_status")
    assert res.status_code == 200


def test_version_endpoint(client):
    res = client.get("/_version")
    assert res.status_code == 200

    version = res.json().get("version")
    assert version


def test_asgi_py():
    """
    Run code in asgi.py for coverage purposes
    """
    import requestor.asgi
