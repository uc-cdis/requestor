import uuid

from asyncpg.exceptions import UniqueViolationError
from fastapi import APIRouter, FastAPI, HTTPException, Body
from pydantic import BaseModel
from starlette.requests import Request
from starlette.status import (
    HTTP_200_OK,
    HTTP_201_CREATED,
    HTTP_204_NO_CONTENT,
    HTTP_409_CONFLICT,
    HTTP_500_INTERNAL_SERVER_ERROR,
)

from .. import logger, arborist
from ..models import RequestStatusEnum, Request as RequestModel

router = APIRouter()


class CreateRequestInput(BaseModel):
    """
    Create an access request.
    """

    username: str
    resource_path: str
    resource_name: str = None


@router.get("/request")
async def list_requests():
    return [r.to_dict() for r in (await RequestModel.query.gino.all())]


@router.post("/request", status_code=HTTP_201_CREATED)
async def create_request(body: CreateRequestInput):
    """
    TODO
    """
    request_id = str(uuid.uuid4())
    try:
        request = await RequestModel.create(
            request_id=request_id, status=RequestStatusEnum.DRAFT, **body.dict()
        )
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
    request = await RequestModel.query.where(
        RequestModel.request_id == request_id
    ).gino.first_or_404()
    return request.to_dict()


@router.put("/request/{request_id}", status_code=HTTP_204_NO_CONTENT)
async def update_request(
    request_id: uuid.UUID,
    api_request: Request,
    status: RequestStatusEnum = Body(..., embed=True),
):
    """
    TODO
    """
    # the access request is approved: grant access
    if status == RequestStatusEnum.APPROVED:
        request = await RequestModel.query.where(
            RequestModel.request_id == request_id
        ).gino.first_or_404()

        # assume we are always granting a user access to a resource.
        # in the future we may want to handle more use cases
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
    request = (
        await RequestModel.delete.where(RequestModel.request_id == request_id)
        .returning(*RequestModel)
        .gino.first_or_404()
    )


def init_app(app: FastAPI):
    app.include_router(router, tags=["Request"])
