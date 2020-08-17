from fastapi import HTTPException, Query, APIRouter, Response
from pydantic import BaseModel
from sqlalchemy.exc import IntegrityError
from starlette.requests import Request
from starlette.status import (
    HTTP_201_CREATED,
    HTTP_204_NO_CONTENT,
    HTTP_400_BAD_REQUEST,
    HTTP_404_NOT_FOUND,
    HTTP_409_CONFLICT,
)
import uuid

from requestor.models import db, RequestStatusEnum, Request as RequestModel


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


class UpdateRequestInput(BaseModel):
    """
    Create a request.
    status (str)
    """

    status: str


@router.get("/request")
async def list_requests():
    requests = db.session.query(RequestModel).all()
    res = [
        {
            "request_id": r.request_id,
            "username": r.username,
            "resource_path": r.resource_path,
            "resource_name": r.resource_name,
            "status": r.status.value,
        }
        for r in requests
    ]
    return res


@router.post("/request", status_code=HTTP_201_CREATED)
async def create_request(
    request: Request, body: CreateRequestInput, response: Response
):
    """
    TODO
    """
    request_id = str(uuid.uuid4())
    status = RequestStatusEnum.DRAFT
    with db():
        client = RequestModel(
            request_id=request_id,
            username=body.username,
            resource_path=body.resource_path,
            resource_name=body.resource_name,
            status=status,
        )
        db.session.add(client)

        try:
            db.session.commit()
        except IntegrityError as e:
            response.status_code = HTTP_409_CONFLICT
            return dict(
                error="Please try again"
            )  # TODO should retry generating unique request_id automatically

    return dict(request_id=request_id)


@router.put("/request/{request_id:path}", status_code=HTTP_204_NO_CONTENT)
async def update_request(request_id: str, body: UpdateRequestInput, response: Response):
    """
    TODO
    """
    status = body.status.lower()
    try:
        request_status = RequestStatusEnum(status).name
    except ValueError:
        response.status_code = HTTP_400_BAD_REQUEST
        return {
            f"'{status}' is not an allowed request status ({[e.value for e in RequestStatusEnum]})"
        }

    with db():
        request = (
            db.session.query(RequestModel)
            .filter(RequestModel.request_id == request_id)
            .first()
        )
        if not request:
            response.status_code = HTTP_404_NOT_FOUND
            return dict(error=f"Request ID '{request_id}' does not exist")

        # TODO update arborist if status is "approved"

        # update request status
        request.status = request_status
        db.session.add(request)
        db.session.commit()

    return dict(request_id=request_id, status=request_status)
