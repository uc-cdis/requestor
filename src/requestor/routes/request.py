import uuid

from asyncpg.exceptions import UniqueViolationError
from fastapi import APIRouter, FastAPI, HTTPException, Body
from pydantic import BaseModel
from starlette.status import (
    HTTP_201_CREATED,
    HTTP_204_NO_CONTENT,
    HTTP_409_CONFLICT,
)

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
    try:
        request = await RequestModel.create(
            request_id=str(uuid.uuid4()), status=RequestStatusEnum.DRAFT, **body.dict()
        )
    except UniqueViolationError:
        raise HTTPException(HTTP_409_CONFLICT, "Please try again")
        # TODO should retry generating unique request_id automatically
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


def init_app(app: FastAPI):
    app.include_router(router, tags=["Request"])
