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
    existing_policies = arborist.list_policies(
        api_request.app.arborist_client, expand=True
    )
    authorized_requests = [
        r
        for r in requests
        if all(
            any(
                arborist.is_path_prefix_of_path(authorized_resource_path, resource_path)
                for authorized_resource_path in authorized_resource_paths
            )
            for resource_path in arborist.get_resource_paths_for_policy(
                existing_policies, r.policy_id
            )
        )
    ]
    return [r.to_dict() for r in authorized_requests]


@router.get("/request/user", status_code=HTTP_200_OK)
async def list_user_requests(
    auth=Depends(Auth),
) -> dict:
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
    existing_policies = arborist.list_policies(
        api_request.app.arborist_client, expand=True
    )
    if request:
        authorized = await auth.authorize(
            "read",
            arborist.get_resource_paths_for_policy(
                existing_policies, request.policy_id
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

    Args:
        resource_paths (list): list of resource paths

    Return: (dict) { resource_path1: true, resource_path2: false, ... }
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
            and arborist.is_path_prefix_of_path(
                r.resource_path, resource_path
            )  # TODO: (PXP-8829)
        ]
        res[resource_path] = len(requests) > 0
    return res


def init_app(app: FastAPI):
    app.include_router(router, tags=["Query"])
