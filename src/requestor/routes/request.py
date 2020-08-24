import uuid

from asyncpg.exceptions import UniqueViolationError
from fastapi import APIRouter, FastAPI, HTTPException, Body
from pydantic import BaseModel
from starlette.requests import Request
from starlette.status import (
    HTTP_200_OK,
    HTTP_201_CREATED,
    HTTP_204_NO_CONTENT,
    HTTP_400_BAD_REQUEST,
    HTTP_409_CONFLICT,
    HTTP_500_INTERNAL_SERVER_ERROR,
)

from .. import logger, arborist
from ..config import config
from ..models import Request as RequestModel

router = APIRouter()


class CreateRequestInput(BaseModel):
    """
    Create an access request.
    """

    username: str
    resource_path: str
    resource_name: str = None
    status: str = None


@router.get("/request")
async def list_requests():
    logger.debug("Listing all requests")
    return [r.to_dict() for r in (await RequestModel.query.gino.all())]


@router.post("/request", status_code=HTTP_201_CREATED)
async def create_request(body: CreateRequestInput):
    """
    TODO
    """
    request_id = str(uuid.uuid4())
    try:
        logger.debug(f"Creating request. request_id: {request_id}. Body: {body.dict()}")
        data = body.dict()
        if not data.get("status"):
            data["status"] = config["DEFAULT_INITIAL_STATUS"]
        request = await RequestModel.create(request_id=request_id, **data)
    except UniqueViolationError:
        # assume the error is because a request with this (username,
        # resource_path) already exists, not about a duplicate request_id
        logger.error(
            f"Unable to create request. request_id: {request_id}. body: {body}",
            exc_info=True,
        )
        raise HTTPException(
            HTTP_409_CONFLICT,
            "An access request for these username and resource_path already exists. Users can only request access to a resource once.",
        )
    else:
        return request.to_dict()


@router.get("/request/{request_id}", status_code=HTTP_200_OK)
async def get_request(request_id: uuid.UUID):
    logger.debug(f"Getting request '{request_id}'")
    request = await RequestModel.query.where(
        RequestModel.request_id == request_id
    ).gino.first_or_404()
    return request.to_dict()


@router.put("/request/{request_id}", status_code=HTTP_204_NO_CONTENT)
async def update_request(
    request_id: uuid.UUID, api_request: Request, status: str = Body(..., embed=True),
):
    """
    TODO
    """
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
        request = await RequestModel.query.where(
            RequestModel.request_id == request_id
        ).gino.first_or_404()

        # assume we are always granting a user access to a resource.
        # in the future we may want to handle more use cases
        logger.debug(f"username: {request.username}, resource: {request.resource_path}")
        success = await arborist.grant_user_access_to_resource(
            api_request.app.arborist_client,
            request.username,
            request.resource_path,
            request.resource_name,
        )

        if not success:
            logger.error(f"Unable to grant access. Check previous logs for errors")
            raise HTTPException(
                HTTP_500_INTERNAL_SERVER_ERROR,
                "Something went wrong, unable to grant access",
            )

    request = await (
        RequestModel.update.where(RequestModel.request_id == request_id)
        .values(status=status)
        .returning(*RequestModel)
        .gino.first_or_404()
    )
    return request.to_dict()


@router.delete("/request/{request_id}", status_code=HTTP_204_NO_CONTENT)
async def delete_request(request_id: uuid.UUID):
    """
    TODO
    """
    logger.debug(f"Deleting request '{request_id}'")
    request = (
        await RequestModel.delete.where(RequestModel.request_id == request_id)
        .returning(*RequestModel)
        .gino.first_or_404()
    )


def init_app(app: FastAPI):
    app.include_router(router, tags=["Request"])
