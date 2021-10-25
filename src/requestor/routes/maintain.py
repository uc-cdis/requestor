import uuid

from asyncpg.exceptions import UniqueViolationError
from datetime import datetime
from fastapi import APIRouter, Body, Depends, FastAPI, HTTPException
from gen3authz.client.arborist.client import ArboristClient
from pydantic import BaseModel
from starlette.requests import Request
from starlette.status import (
    HTTP_200_OK,
    HTTP_201_CREATED,
    HTTP_400_BAD_REQUEST,
    HTTP_403_FORBIDDEN,
    HTTP_409_CONFLICT,
    HTTP_500_INTERNAL_SERVER_ERROR,
)

from .. import logger, arborist
from ..asgi import app
from ..auth import Auth
from ..config import config
from ..models import db, Request as RequestModel
from ..request_utils import post_status_update


router = APIRouter()


class CreateRequestInput(BaseModel):
    """
    Create an access request.
    """

    username: str = None
    resource_path: str = None
    resource_id: str = None
    resource_display_name: str = None
    status: str = None
    policy_id: str = None


@router.post("/request", status_code=HTTP_201_CREATED)
async def create_request(
    body: CreateRequestInput,
    auth=Depends(Auth),
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

    if data.get("resource_path") and data.get("policy_id"):
        msg = f"A Request cannot have both resource_path and policy_id."
        logger.error(
            msg + f" body: {body}",
            exc_info=True,
        )
        raise HTTPException(
            HTTP_400_BAD_REQUEST,
            msg,
        )

    if data["resource_path"]:
        data["policy_id"] = arborist.get_auto_policy_id_for_resource_path(
            data.get("resource_path")
        )
        resource_paths = [data["resource_path"]]
    else:
        client = app.arborist_client
        existing_policies = await arborist.list_policies(client, expand=True)
        resource_paths = arborist.get_resource_paths_for_policy(
            existing_policies["policies"], data.get("policy_id")
        )
    del data["resource_path"]  # Get rid off resource_path completely.

    await auth.authorize("create", resource_paths)

    request_id = str(uuid.uuid4())
    logger.debug(f"Creating request. request_id: {request_id}. Received body: {data}")

    if not data.get("status"):
        data["status"] = config["DEFAULT_INITIAL_STATUS"]

    if not data.get("username"):
        logger.debug("No username provided in body, using token username")
        token_claims = await auth.get_token_claims()
        token_username = token_claims["context"]["user"]["name"]
        logger.debug(f"Got username from token: {token_username}")
        data["username"] = token_username

    # get requests for this (username, policy_id) for which the status is
    # not in FINAL_STATUSES. users can only request access to a resource once.
    previous_requests = [
        r
        for r in (
            await RequestModel.query.where(
                RequestModel.username == data["username"],
            )
            .where(
                RequestModel.policy_id == data["policy_id"],
            )
            .where(
                RequestModel.status.notin_(config["FINAL_STATUSES"]),
            )
            .gino.all()
        )
    ]
    draft_previous_requests = [
        r for r in previous_requests if r.status in config["DRAFT_STATUSES"]
    ]

    if previous_requests and not draft_previous_requests:
        # a request for this (username, resource_path) already exists
        msg = f'An open access request for username \'{data["username"]}\' and policy_id \'{data["policy_id"]}\' already exists. Users can only request access to a resource once.'
        logger.error(
            msg
            + f" body: {body}. existing requests: {[r.request_id for r in previous_requests]}",
            exc_info=True,
        )
        raise HTTPException(
            HTTP_409_CONFLICT,
            msg,
        )

    if draft_previous_requests:
        # reuse the draft request
        res = draft_previous_requests[0].to_dict()
    else:
        # create a new request
        try:
            request = await RequestModel.create(request_id=request_id, **data)
        except UniqueViolationError:
            raise HTTPException(
                HTTP_409_CONFLICT,
                "request_id already exists. Please try again",
            )
        res = request.to_dict()

    # CORS limits redirections, so we redirect on the client side
    redirect_url = post_status_update(
        data["status"], res, resource_path=resource_paths[0]
    )
    if redirect_url:
        res["redirect_url"] = redirect_url

    return res


@router.put("/request/{request_id}", status_code=HTTP_200_OK)
async def update_request(
    api_request: Request,
    request_id: uuid.UUID,
    status: str = Body(..., embed=True),
    auth=Depends(Auth),
) -> dict:
    """
    Update an access request with a new "status".
    """
    # only allow 1 update request at a time on the same row
    async with db.transaction():
        request = (
            await RequestModel.query.where(RequestModel.request_id == request_id)
            # lock the row by using FOR UPDATE clause
            .execution_options(populate_existing=True)
            .with_for_update()
            .gino.first_or_404()
        )
        existing_policies = await arborist.list_policies(
            api_request.app.arborist_client, expand=True
        )
        resource_paths = arborist.get_resource_paths_for_policy(
            existing_policies["policies"], request.policy_id
        )
        await auth.authorize(
            "update",
            resource_paths,
        )

        if request.status == status:
            logger.debug(f"Request '{request_id}' already has status '{status}'")
            return request.to_dict()

        logger.debug(f"Updating request '{request_id}' with status '{status}'")

        allowed_statuses = config["ALLOWED_REQUEST_STATUSES"]
        if status not in allowed_statuses:
            raise HTTPException(
                HTTP_400_BAD_REQUEST,
                f"Status '{status}' is not an allowed request status ({allowed_statuses})",
            )

        # the access request is approved: grant access
        if status in config["UPDATE_ACCESS_STATUSES"]:
            logger.debug(
                f"Status is one of '{config['UPDATE_ACCESS_STATUSES']}', attempting to grant access in Arborist"
            )

            # assume we are always granting a user access to a resource.
            # in the future we may want to handle more use cases
            logger.debug(
                f"username: {request.username}, policy_id: {request.policy_id}"
            )
            success = await arborist.grant_user_access_to_policy(
                api_request.app.arborist_client,
                request.username,
                request.policy_id,
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

    # release the connection early, `post_status_update` could take time
    # https://python-gino.org/docs/en/1.0/reference/extensions/starlette.html#lazy-connection
    await api_request["connection"].release(permanent=False)

    res = request.to_dict()

    # CORS limits redirections, so we redirect on the client side
    redirect_url = post_status_update(status, res, resource_path=resource_paths[0])
    if redirect_url:
        res["redirect_url"] = redirect_url

    return res


@router.delete("/request/{request_id}", status_code=HTTP_200_OK)
async def delete_request(
    api_request: Request,
    request_id: uuid.UUID,
    auth=Depends(Auth),
) -> dict:
    """
    Delete an access request.
    """
    logger.debug(f"Deleting request '{request_id}'")
    async with db.transaction():
        request = (
            await RequestModel.delete.where(RequestModel.request_id == request_id)
            .returning(*RequestModel)
            .gino.first_or_404()
        )

        # if not authorized, the exception raised by `auth.authorize`
        # triggers a transaction rollback, so we don't delete
        exisiting_policies = await arborist.list_policies(
            api_request.app.arborist_client, expand=True
        )
        await auth.authorize(
            "delete",
            arborist.get_resource_paths_for_policy(
                exisiting_policies["policies"], request.policy_id
            ),
        )

    return {"request_id": request_id}


def init_app(app: FastAPI):
    app.include_router(router, tags=["Maintain"])
