import time

import pytest

from requestor.config import config


def create_request(client, token):
    data = {
        "policy_id": "test-policy",
        "resource_id": "uniqid",
        "resource_display_name": "My Resource",
    }
    return client.post(
        "/request", json=data, headers={"Authorization": f"bearer {token}"}
    )


def authz_check_called(arborist_mock):
    return any(
        call.args[1].endswith("/auth/request") for call in arborist_mock.call_args_list
    )


@pytest.mark.parametrize("test_case", ["match", "mismatch"])
def test_token_audience_check(
    client,
    access_token_user_only_patcher,
    generate_signed_token,
    mock_arborist_requests,
    test_case,
):
    """
    Test that a token's audience is validated before it is handed off to the authorization service.
    """
    arborist_mock = mock_arborist_requests()

    # `gen3` is the default audience for Gen3 Fence tokens
    token_aud = "gen3" if test_case == "match" else "WORKFLOW"
    token = generate_signed_token(aud=token_aud)

    res = create_request(client, token)

    if test_case == "match":
        assert res.status_code == 201, res.text
        assert authz_check_called(arborist_mock)
    else:
        assert res.status_code == 401, res.text
        assert not authz_check_called(arborist_mock)


@pytest.mark.parametrize("test_case", ["match", "mismatch"])
def test_token_issuer_check(
    client,
    access_token_user_only_patcher,
    generate_signed_token,
    mock_arborist_requests,
    test_case,
):
    """
    Test that a token's issuer is validated before it is handed off to the authorization service.
    """
    arborist_mock = mock_arborist_requests()

    token_iss = (
        config["ALLOWED_ISSUERS"][0]
        if test_case == "match"
        else "https://other-issuer.example.com/user"
    )
    token = generate_signed_token(iss=token_iss)

    res = create_request(client, token)

    if test_case == "match":
        assert res.status_code == 201, res.text
        assert authz_check_called(arborist_mock)
    else:
        assert res.status_code == 401, res.text
        assert not authz_check_called(arborist_mock)


@pytest.mark.parametrize("test_case", ["expired", "valid"])
def test_token_expiration_check(
    client,
    access_token_user_only_patcher,
    generate_signed_token,
    mock_arborist_requests,
    test_case,
):
    """
    Test that a token's expiration is validated before it is handed off to the authorization
    service.
    """
    arborist_mock = mock_arborist_requests()

    now = int(time.time())
    token_exp = now + 300 if test_case == "valid" else now - 300
    token = generate_signed_token(exp=token_exp)

    res = create_request(client, token)

    if test_case == "valid":
        assert res.status_code == 201, res.text
        assert authz_check_called(arborist_mock)
    else:
        assert res.status_code == 401, res.text
        assert not authz_check_called(arborist_mock)
