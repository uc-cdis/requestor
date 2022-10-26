import uuid
from datetime import datetime
from fastapi import APIRouter, Body, Depends, FastAPI, HTTPException
from starlette.requests import Request
from starlette.status import (
    HTTP_200_OK,
    HTTP_400_BAD_REQUEST,
    HTTP_401_UNAUTHORIZED,
    HTTP_403_FORBIDDEN,
    HTTP_404_NOT_FOUND,
)

from .. import logger, arborist
from ..auth import Auth
from ..config import config
from ..models import Request as RequestModel


router = APIRouter()


async def get_filtered_requests(
    username: str = None, draft: bool = True, final: bool = True, filters: dict = {}
) -> list:
    """
    If not None, gets all the requests made by user with given username.
    If only non-draft requests are needed then set draft=False.
    If only non-final requests are needed then set final=False.
    Add filters if neccessary as a dictionary of {param : <List of values>} to get filtered results
    """
    query = RequestModel.query
    if username:
        query = query.where(RequestModel.username == username)
    if not draft:
        query = query.where(RequestModel.status.notin_(config["DRAFT_STATUSES"]))
    if not final:
        query = query.where(RequestModel.status.notin_(config["FINAL_STATUSES"]))
    for field, values in filters.items():
        query = query.where(getattr(RequestModel, field).in_(values))

    return [r for r in (await query.gino.all())]


def populate_filters_from_query_params(query_params):
    active = False
    filter_dict = {k: set() for k in query_params if k != "active"}
    for param, value in query_params.multi_items():
        if param == "active":
            if value:
                raise HTTPException(
                    HTTP_400_BAD_REQUEST,
                    f"The 'active' parameter should not be assigned a value. Received '{value}'",
                )
            active = True
        elif not hasattr(RequestModel, param):
            raise HTTPException(
                HTTP_400_BAD_REQUEST,
                f"The parameter - '{param}' is invalid.",
            )
        elif not value:
            raise HTTPException(
                HTTP_400_BAD_REQUEST,
                f"The param '{param}' must have a non-empty value.",
            )
        else:
            try:
                if getattr(RequestModel, param).type.python_type == bool:
                    value = value.lower() == "true"
                elif getattr(RequestModel, param).type.python_type == datetime:
                    value = datetime.fromisoformat(value)
            except ValueError:
                raise HTTPException(
                    HTTP_400_BAD_REQUEST,
                    f"The value - '{value}' for '{param}' parameter is invalid.",
                )
            filter_dict[param].add(value)
    return filter_dict, active


@router.get("/request")
async def list_requests(
    api_request: Request,
    auth=Depends(Auth),
) -> list:
    """
    List all the requests the current user has access to see.

    Use the "active" query parameter to get only the requests
    created by the user that are not in DRAFT or FINAL statuses.

    Add filter values as key=value pairs in the query string
    to get filtered results.
    Note: for filters based on Date, only follow `YYYY-MM-DD` format

    Providing the same key with more than one value filters records whose
    value of the given key matches any of the given values. But values of
    different keys must all match.

    Example: `GET /requests/request?policy_id=foo&policy_id=bar&revoke=False&status=APPROVED`

    "policy_id=foo&policy_id=bar" means "the policy is either foo or bar" (same field name).

    "policy_id=foo&revoke=False" means "the policy is foo and revoke is false" (different field names).
    """
    filter_dict, active = populate_filters_from_query_params(api_request.query_params)
    requests = await get_filtered_requests(final=(not active), filters=filter_dict)

    # get the resources the current user has access to see
    token_claims = await auth.get_token_claims()
    username = token_claims.get("context", {}).get("user", {}).get("name")
    if username:
        authz_mapping = await api_request.app.arborist_client.auth_mapping(username)
    else:
        client_id = token_claims.get("azp")
        if not client_id:
            raise HTTPException(
                HTTP_401_UNAUTHORIZED,
                "The provided token does not include a username or a client ID",
            )
        authz_mapping = await api_request.app.arborist_client.client_auth_mapping(
            client_id
        )
    authorized_resource_paths = [
        resource_path
        for resource_path, access in authz_mapping.items()
        if any(
            e["service"] in ["requestor", "*"] and e["method"] in ["read", "*"]
            for e in access
        )
    ]

    # filter requests with read access
    existing_policies = await arborist.list_policies(
        api_request.app.arborist_client, expand=True
    )
    authorized_requests = []
    for r in requests:
        resource_paths = arborist.get_resource_paths_for_policy(
            existing_policies["policies"], r.policy_id
        )
        if not resource_paths:
            # Note that GETting a request with no resource paths would require
            # admin access - not implemented
            continue
        # A request is authorized if all the resource_paths in the request's
        # policy are authorized.
        if all(
            # A resource_path is authorized if authorized_resource_paths
            # contains the path or any of its prefixes
            any(
                arborist.is_path_prefix_of_path(authorized_resource_path, resource_path)
                for authorized_resource_path in authorized_resource_paths
            )
            for resource_path in resource_paths
        ):
            authorized_requests.append(r)

    return [r.to_dict() for r in authorized_requests]


@router.get("/request/user", status_code=HTTP_200_OK)
async def list_user_requests(api_request: Request, auth=Depends(Auth)) -> dict:
    """
    List current user's requests.

    Use the "active" query parameter to get only the requests
    created by the user that are not in DRAFT or FINAL statuses.

    Add filter values as key=value pairs in the query string
    to get filtered results.
    Note: for filters based on Date, only follow `YYYY-MM-DD` format

    Providing the same key with more than one value filters records whose
    value of the given key matches any of the given values. But values of
    different keys must all match.

    Example: `GET /requests/user?policy_id=foo&policy_id=bar&revoke=False&status=APPROVED`

    "policy_id=foo&policy_id=bar" means "the policy is either foo or bar" (same field name).

    "policy_id=foo&revoke=False" means "the policy is foo and revoke is false" (different field names).
    """
    # no authz checks because we assume the current user can read
    # their own requests.
    filter_dict, active = populate_filters_from_query_params(api_request.query_params)
    token_claims = await auth.get_token_claims()
    username = token_claims.get("context", {}).get("user", {}).get("name")
    if not username:
        raise HTTPException(
            HTTP_403_FORBIDDEN,
            "This endpoint does not support tokens that are not linked to a user",
        )
    logger.debug(f"Getting requests for user '{username}' with active = '{active}'")
    user_requests = await get_filtered_requests(
        # if we only want active requests, filter out requests in a final status
        username,
        final=(not active),
        filters=filter_dict,
    )
    return [r.to_dict() for r in user_requests]


@router.get("/request/{request_id}", status_code=HTTP_200_OK)
async def get_request(
    api_request: Request,
    request_id: uuid.UUID,
    auth=Depends(Auth),
) -> dict:
    logger.debug(f"Getting request '{request_id}'")

    request = await RequestModel.query.where(
        RequestModel.request_id == request_id
    ).gino.first()
    existing_policies = await arborist.list_policies(
        api_request.app.arborist_client, expand=True
    )
    if request:
        authorized = await auth.authorize(
            "read",
            # Note that GETting a request with no resource paths would require
            # admin access - not implemented
            arborist.get_resource_paths_for_policy(
                existing_policies["policies"], request.policy_id
            ),
            throw=False,
        )

    if not request or not authorized:
        # return the same error for unauthorized and not found
        raise HTTPException(
            HTTP_404_NOT_FOUND,
            "Not found",
        )

    return request.to_dict()


@router.post("/request/user_resource_paths", status_code=HTTP_200_OK)
async def check_user_resource_paths(
    api_request: Request,
    resource_paths: list = Body(..., embed=True),
    permissions: list = None,
    auth=Depends(Auth),
) -> dict:
    """
    Return whether the current user has already requested access to the
    specified resource path(s), including prefixes of the resource path(s).
    If the previous request was denied or is still in draft status, will
    return False.
    """
    # TODO add the ability to specify the service
    if not permissions:
        permissions = ["reader", "storage_reader"]

    # no authz checks because we assume the current user can read
    # their own requests.
    token_claims = await auth.get_token_claims()
    username = token_claims.get("context", {}).get("user", {}).get("name")
    if not username:
        raise HTTPException(
            HTTP_403_FORBIDDEN,
            "This endpoint does not support tokens that are not linked to a user",
        )
    user_requests = await get_filtered_requests(username, draft=False, final=False)
    positive_requests = [r for r in user_requests if not r.revoke]
    existing_policies = await arborist.list_policies(
        api_request.app.arborist_client, expand=True
    )

    # Initiate everything to False
    res = {r: False for r in resource_paths}

    for r in positive_requests:
        # Get the policy
        policy = arborist.get_policy_for_id(existing_policies["policies"], r.policy_id)

        if policy is None:
            continue

        # Flatten permissions
        policy_permission_ids = {
            permission["id"]
            for role in policy["roles"]
            for permission in role["permissions"]
        }

        # Continue to next request if all permissions in the request are not
        # present in the policy
        if not all(permission in policy_permission_ids for permission in permissions):
            continue

        # find if a resource path matches
        for rp in policy["resource_paths"]:
            for resource_path in resource_paths:
                if res[resource_path]:
                    continue
                if arborist.is_path_prefix_of_path(rp, resource_path):
                    res[resource_path] = True  # update result dictionary
                    break

    return res


def init_app(app: FastAPI):
    app.include_router(router, tags=["Query"])
