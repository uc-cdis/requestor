import uuid

from datetime import datetime
from fastapi import APIRouter, Body, Depends, FastAPI, HTTPException
from pydantic import BaseModel
from starlette.requests import Request
from starlette.status import (
    HTTP_200_OK,
    HTTP_400_BAD_REQUEST,
    HTTP_404_NOT_FOUND,
)

from .. import logger, arborist
from ..auth import Auth
from ..config import config
from ..models import Request as RequestModel


router = APIRouter()


async def get_user_requests(username: str, active: bool = False) -> list:
    query = RequestModel.query.where(RequestModel.username == username)
    if active:
        query = query.where(
            RequestModel.status.notin_(
                config["DRAFT_STATUSES"] + config["FINAL_STATUSES"]
            )
        )
    return [r for r in (await query.gino.all())]


@router.get("/request")
async def list_requests(
    api_request: Request,
    auth=Depends(Auth),
) -> list:
    """
    List all the requests the current user has access to see.
    """
    # get the resources the current user has access to see
    token_claims = await auth.get_token_claims()
    username = token_claims["context"]["user"]["name"]
    authz_mapping = await api_request.app.arborist_client.auth_mapping(username)
    authorized_resource_paths = [
        resource_path
        for resource_path, access in authz_mapping.items()
        if any(
            e["service"] in ["requestor", "*"] and e["method"] in ["read", "*"]
            for e in access
        )
    ]

    # filter requests with read access
    requests = await RequestModel.query.gino.all()
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
    List the current user's requests.

    Use the "active" query parameter to get only those requests
    created by the user that are not in DRAFT or FINAL statuses.
    """
    # no authz checks because we assume the current user can read
    # their own requests.
    active = False
    if "active" in api_request.query_params:
        if api_request.query_params["active"]:
            raise HTTPException(
                HTTP_400_BAD_REQUEST,
                f"The 'active' parameter should not be assigned a value. Received '{api_request.query_params['active']}'",
            )
        active = True
    token_claims = await auth.get_token_claims()
    username = token_claims["context"]["user"]["name"]
    logger.debug(f"Getting requests for user '{username}' with active = '{active}'")

    user_requests = await get_user_requests(username, active=active)
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
    resource_paths: list = Body(..., embed=True),
    auth=Depends(Auth),
) -> dict:
    """
    Return whether the current user has already requested access to the
    specified resource path(s), including prefixes of the resource path(s).
    If the previous request was denied or is still in draft status, will
    return False.
    """
    # no authz checks because we assume the current user can read
    # their own requests.

    token_claims = await auth.get_token_claims()
    username = token_claims["context"]["user"]["name"]

    res = {}
    user_requests = await get_user_requests(username)
    for resource_path in resource_paths:
        requests = [
            r
            for r in user_requests
            if r.status not in config["DRAFT_STATUSES"]
            and r.status not in config["FINAL_STATUSES"]
            # TODO update logic to handle `policy_id` (PXP-8829)
            and arborist.is_path_prefix_of_path(r.resource_path, resource_path)
        ]
        res[resource_path] = len(requests) > 0
    return res


def init_app(app: FastAPI):
    app.include_router(router, tags=["Query"])
