import uuid

from datetime import datetime
from fastapi import APIRouter, Body, FastAPI, HTTPException, Security
from fastapi.security import HTTPAuthorizationCredentials
from pydantic import BaseModel
from starlette.requests import Request
from starlette.status import (
    HTTP_200_OK,
    HTTP_404_NOT_FOUND,
)

from .. import logger, arborist
from ..auth import bearer, get_token_claims, authorize
from ..config import config
from ..models import Request as RequestModel
from ..request_utils import is_path_prefix_of_path


router = APIRouter()


async def get_user_requests(username: str) -> list:
    return [
        r
        for r in (
            await RequestModel.query.where(RequestModel.username == username).gino.all()
        )
    ]


@router.get("/request")
async def list_requests() -> list:
    # TODO filter requests with read access
    logger.debug("Listing all requests")
    return [r.to_dict() for r in (await RequestModel.query.gino.all())]


@router.get("/request/user", status_code=HTTP_200_OK)
async def list_user_requests(
    api_request: Request,
    bearer_token: HTTPAuthorizationCredentials = Security(bearer),
) -> dict:
    """
    List the current user's requests.
    """
    # no authz checks because we assume the current user can read
    # their own requests.

    token_claims = await get_token_claims(bearer_token)
    username = token_claims["context"]["user"]["name"]
    logger.debug(f"Getting requests for user '{username}'")

    user_requests = await get_user_requests(username)
    return [r.to_dict() for r in user_requests]


@router.get("/request/{request_id}", status_code=HTTP_200_OK)
async def get_request(
    request_id: uuid.UUID,
    api_request: Request,
    bearer_token: HTTPAuthorizationCredentials = Security(bearer),
) -> dict:
    logger.debug(f"Getting request '{request_id}'")

    request = await RequestModel.query.where(
        RequestModel.request_id == request_id
    ).gino.first()

    if request:
        authorized = await authorize(
            api_request.app.arborist_client,
            bearer_token,
            "read",
            [request.to_dict()["resource_path"]],
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
    bearer_token: HTTPAuthorizationCredentials = Security(bearer),
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

    token_claims = await get_token_claims(bearer_token)
    username = token_claims["context"]["user"]["name"]

    res = {}
    user_requests = await get_user_requests(username)
    for resource_path in resource_paths:
        requests = [
            r
            for r in user_requests
            if r.status not in config["DRAFT_STATUSES"]
            and r.status not in config["FINAL_STATUSES"]
            and is_path_prefix_of_path(r.resource_path, resource_path)
        ]
        res[resource_path] = len(requests) > 0
    return res


def init_app(app: FastAPI):
    app.include_router(router, tags=["Query"])
