import uuid

from asyncpg.exceptions import UniqueViolationError
from fastapi import APIRouter, FastAPI, HTTPException, Body
from pydantic import BaseModel
from starlette.status import (
    HTTP_201_CREATED,
    HTTP_204_NO_CONTENT,
    HTTP_409_CONFLICT,
)

from .. import logger
from ..models import RequestStatusEnum, Request as RequestModel

router = APIRouter()


class CreateRequestInput(BaseModel):
    """
    Create a request.
    username (str)
    resource_path (str)
    resource_name (str, optional)
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


@router.put("/request/{request_id}", status_code=HTTP_204_NO_CONTENT)
async def update_request(
    request_id: uuid.UUID, status: RequestStatusEnum = Body(..., embed=True),
):
    """
    TODO
    """
    # TODO update arborist if status is "approved"
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
        .gino.first()
    )
    if request:
        return {}
    else:
        raise HTTPException(HTTP_404_NOT_FOUND, f"Not found: {request_id}")


def init_app(app: FastAPI):
    app.include_router(router, tags=["Request"])
