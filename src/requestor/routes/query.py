from typing import Optional
import uuid

from datetime import datetime
from fastapi import APIRouter, Body, Depends, FastAPI, HTTPException
from pydantic import BaseModel
from starlette.requests import Request
from starlette.status import (
    HTTP_200_OK,
    HTTP_404_NOT_FOUND,
)

from .. import logger, arborist
from ..auth import Auth
from ..config import config
from ..models import Request as RequestModel


router = APIRouter()


async def get_user_requests(username: str) -> list:
    return [
        r
        for r in (
            await RequestModel.query.where(RequestModel.username == username).gino.all()
        )
    ]


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
async def list_user_requests(auth=Depends(Auth)) -> dict:
    """
    List the current user's requests.
    """
    # no authz checks because we assume the current user can read
    # their own requests.

    token_claims = await auth.get_token_claims()
    username = token_claims["context"]["user"]["name"]
    logger.debug(f"Getting requests for user '{username}'")

    user_requests = await get_user_requests(username)
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


def get_policy_for_id(policy_id: str, existing_policies: list) -> dict:
    policy_list = [p for p in existing_policies["policies"] if p["id"] == policy_id]
    return policy_list[0] if policy_list else None


@router.post("/request/user_resource_paths", status_code=HTTP_200_OK)
async def check_user_resource_paths(
    api_request: Request,
    resource_paths: list = Body(..., embed=True),
    permissions: Optional[list] = None,
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
    if not permissions:
        permissions = ["reader", "storage-reader"]
    res = {}
    user_requests = await get_user_requests(username)
    positive_requests = [
        r
        for r in user_requests
        if not r.revoke
        and r.status not in config["DRAFT_STATUSES"]
        and r.status not in config["FINAL_STATUSES"]
    ]
    existing_policies = await arborist.list_policies(
        api_request.app.arborist_client, expand=True
    )
    # Initiate everything to False
    res = {r: False for r in resource_paths}
    for r in positive_requests:
        # Get the policy
        policy = get_policy_for_id(r.policy_id, existing_policies)
        if policy is None:
            continue
        # Flatten permissions
        policy_permission_ids = [
            permission["id"]
            for role in policy["roles"]
            for permission in role["permissions"]
        ]
        # Continue to next request if all permissions in the request are not present in the policy
        if not all(permission in policy_permission_ids for permission in permissions):
            continue
        # find if a resource path matches
        for rp in policy["resource_paths"]:
            for resource_path in resource_paths:
                if arborist.is_path_prefix_of_path(rp, resource_path):
                    # update res dictionary
                    res[f"{resource_path}"] = True

    return res


def init_app(app: FastAPI):
    app.include_router(router, tags=["Query"])
