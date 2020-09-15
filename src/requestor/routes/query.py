import uuid

from datetime import datetime
from fastapi import APIRouter, FastAPI, HTTPException, Security
from fastapi.security import HTTPAuthorizationCredentials
from pydantic import BaseModel
from starlette.requests import Request
from starlette.status import (
    HTTP_200_OK,
    HTTP_404_NOT_FOUND,
)

from .. import logger, arborist
from ..config import config
from ..models import Request as RequestModel
from ..auth import bearer, authorize


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


# @router.get("/request/{request_id}", status_code=HTTP_200_OK)
# async def get_user_request(
#     request_id: uuid.UUID,
#     api_request: Request,
#     bearer_token: HTTPAuthorizationCredentials = Security(bearer),
# ) -> dict:
#     logger.debug(f"Getting request '{request_id}'")

#     request = await RequestModel.query.where(
#         RequestModel.request_id == request_id
#     ).gino.first()

#     if request:
#         authorized = await authorize(
#             api_request.app.arborist_client,
#             bearer_token,
#             "read",
#             [request.to_dict()["resource_path"]],
#             throw=False,
#         )

#     if not request or not authorized:
#         # return the same error for unauthorized and not found
#         raise HTTPException(
#             HTTP_404_NOT_FOUND,
#             "Not found",
#         )

#     return request.to_dict()


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
    app.include_router(router, tags=["Query"])
