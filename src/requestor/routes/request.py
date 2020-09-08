import uuid

from asyncpg.exceptions import UniqueViolationError
from datetime import datetime
from fastapi import APIRouter, FastAPI, HTTPException, Body, Security
from fastapi.security import HTTPAuthorizationCredentials
from pydantic import BaseModel
from starlette.requests import Request
from starlette.status import (
    HTTP_200_OK,
    HTTP_201_CREATED,
    HTTP_400_BAD_REQUEST,
    HTTP_409_CONFLICT,
    HTTP_500_INTERNAL_SERVER_ERROR,
)
from sqlalchemy import and_

from .. import logger, arborist
from ..config import config
from ..models import Request as RequestModel
from ..request_utils import post_status_update
from ..auth import bearer, get_token_claims, authorize

router = APIRouter()


class CreateRequestInput(BaseModel):
    """
    Create an access request.
    """

    username: str = None
    resource_path: str
    resource_id: str = None
    resource_display_name: str = None
    status: str = None


@router.get("/request")
async def list_requests() -> list:
    # TODO GET requests for resource path - returns requests for prefixes that include the resource path - optional username param
    # TODO filter requests with read access
    logger.debug("Listing all requests")
    return [r.to_dict() for r in (await RequestModel.query.gino.all())]


@router.get("/request/{request_id}", status_code=HTTP_200_OK)
async def get_request(
    request_id: uuid.UUID,
    api_request: Request,
    bearer_token: HTTPAuthorizationCredentials = Security(bearer),
) -> dict:
    logger.debug(f"Getting request '{request_id}'")
    request = await RequestModel.query.where(
        RequestModel.request_id == request_id
    ).gino.first_or_404()

    await authorize(
        api_request.app.arborist_client,
        bearer_token,
        "read",
        [request.to_dict()["resource_path"]],
    )

    return request.to_dict()


@router.post("/request", status_code=HTTP_201_CREATED)
async def create_request(
    api_request: Request,
    body: CreateRequestInput,
    bearer_token: HTTPAuthorizationCredentials = Security(bearer),
) -> dict:
    """
    Create a new access request.
    If no "status" is specified in the request body, will use the configured
    DEFAULT_INITIAL_STATUS. Because users can only request access to a
    resource once, (username, resource_path) must be unique unless past
    requests' statuses are in FINAL_STATUSES.
    If no "username" is specified in the request body, will create an access
    request for the user who provided the token.
    """
    data = body.dict()
    await authorize(
        api_request.app.arborist_client, bearer_token, "create", [data["resource_path"]]
    )

    token_claims = await get_token_claims(bearer_token)
    token_username = token_claims["context"]["user"]["name"]
    logger.debug(f"Got username from token: {token_username}")

    request_id = str(uuid.uuid4())
    logger.debug(f"Creating request. request_id: {request_id}. Received body: {data}")

    if not data.get("status"):
        data["status"] = config["DEFAULT_INITIAL_STATUS"]
    if not data.get("username"):
        logger.debug("No username provided in body, using token username")
        data["username"] = token_username

    # get requests for this (username, resource_path) for which the status is
    # not in FINAL_STATUSES. users can only request access to a resource once.
    previous_requests = [
        (str(r.request_id), r.status)
        for r in (
            await RequestModel.query.where(
                and_(
                    RequestModel.username == data["username"],
                    RequestModel.resource_path == data["resource_path"],
                    RequestModel.status.notin_(config["FINAL_STATUSES"]),
                )
            ).gino.all()
        )
    ]
    if previous_requests:
        # a request for this (username, resource_path) already exists
        msg = f'An open access request for username \'{data["username"]}\' and resource_path \'{data["resource_path"]}\' already exists. Users can only request access to a resource once.'
        logger.error(
            msg + f" body: {body}. existing requests: {previous_requests}",
            exc_info=True,
        )
        raise HTTPException(
            HTTP_409_CONFLICT,
            msg,
        )

    # create the request
    try:
        request = await RequestModel.create(request_id=request_id, **data)
    except UniqueViolationError:
        raise HTTPException(
            HTTP_409_CONFLICT,
            "request_id already exists. Please try again",
        )

    res = request.to_dict()
    redirect_url = post_status_update(data["status"], res)

    if redirect_url:
        # CORS limits redirections, so we redirect on the client side
        res["redirect_url"] = redirect_url

    return res


@router.put("/request/{request_id}", status_code=HTTP_200_OK)
async def update_request(
    api_request: Request,
    request_id: uuid.UUID,
    status: str = Body(..., embed=True),
    bearer_token: HTTPAuthorizationCredentials = Security(bearer),
) -> dict:
    """
    Update an access request with a new "status".
    """
    request = await RequestModel.query.where(
        RequestModel.request_id == request_id
    ).gino.first_or_404()

    await authorize(
        api_request.app.arborist_client,
        bearer_token,
        "update",
        [request.to_dict()["resource_path"]],
    )

    logger.debug(f"Updating request '{request_id}' with status '{status}'")

    allowed_statuses = config["ALLOWED_REQUEST_STATUSES"]
    if status not in allowed_statuses:
        raise HTTPException(
            HTTP_400_BAD_REQUEST,
            f"Status '{status}' is not an allowed request status ({allowed_statuses})",
        )

    # the access request is approved: grant access
    approved_status = config["GRANT_ACCESS_STATUS"]
    if status == approved_status:
        logger.debug(
            f"Status is '{approved_status}', attempting to grant access in Arborist"
        )

        # assume we are always granting a user access to a resource.
        # in the future we may want to handle more use cases
        logger.debug(f"username: {request.username}, resource: {request.resource_path}")
        success = await arborist.grant_user_access_to_resource(
            api_request.app.arborist_client,
            request.username,
            request.resource_path,
            request.resource_display_name,
        )

        if not success:
            logger.error(f"Unable to grant access. Check previous logs for errors")
            raise HTTPException(
                HTTP_500_INTERNAL_SERVER_ERROR,
                "Something went wrong, unable to grant access",
            )

    request = await (
        RequestModel.update.where(RequestModel.request_id == request_id)
        .values(status=status, updated_time=datetime.utcnow())
        .returning(*RequestModel)
        .gino.first()
    )

    res = request.to_dict()

    # CORS limits redirections, so we redirect on the client side
    redirect_response = post_status_update(status, res)
    if redirect_response:
        res["redirect_url"] = redirect_response

    return res


@router.delete("/request/{request_id}", status_code=HTTP_200_OK)
async def delete_request(
    api_request: Request,
    request_id: uuid.UUID,
    bearer_token: HTTPAuthorizationCredentials = Security(bearer),
) -> dict:
    """
    Delete an access request.
    """
    request = await RequestModel.query.where(
        RequestModel.request_id == request_id
    ).gino.first_or_404()

    await authorize(
        api_request.app.arborist_client,
        bearer_token,
        "delete",
        [request.to_dict()["resource_path"]],
    )

    logger.debug(f"Deleting request '{request_id}'")
    request = (
        await RequestModel.delete.where(RequestModel.request_id == request_id)
        .returning(*RequestModel)
        .gino.first()
    )
    return {"request_id": request_id}


async def get_requests_for_resource_prefix(
    api_request: Request, resource_prefix
) -> list:
    # TODO use this
    logger.debug(f"Getting requests for resource prefix '{resource_prefix}'")
    return [
        r.to_dict()
        for r in (
            await RequestModel.query.where(
                RequestModel.resource_path.startswith(resource_prefix)
            ).gino.all()
        )
    ]


def init_app(app: FastAPI):
    app.include_router(router, tags=["Request"])
