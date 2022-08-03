import uuid

from asyncpg.exceptions import UniqueViolationError
from datetime import datetime
from fastapi import APIRouter, Body, Depends, FastAPI, HTTPException
from pydantic import BaseModel
from starlette.requests import Request
from starlette.status import (
    HTTP_200_OK,
    HTTP_201_CREATED,
    HTTP_400_BAD_REQUEST,
    HTTP_409_CONFLICT,
    HTTP_500_INTERNAL_SERVER_ERROR,
)
import traceback

from .. import logger, arborist
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
    resource_paths: list[str] = None
    resource_id: str = None
    resource_display_name: str = None
    status: str = None
    policy_id: str = None
    role_ids: list[str] = None


async def grant_or_revoke_arborist_policy(arborist_client, policy_id, username, revoke):
    # assume we are always granting a user access to a resource.
    # in the future we may want to handle more use cases
    logger.debug(f"username: {username}, policy_id: {policy_id}")
    if revoke:
        success = await arborist.revoke_user_access_to_policy(
            arborist_client,
            username,
            policy_id,
        )
    else:
        success = await arborist.grant_user_access_to_policy(
            arborist_client,
            username,
            policy_id,
        )

    if not success:
        action = "revoke" if revoke else "grant"
        logger.error(f"Unable to {action} access. Check previous logs for errors")
        raise HTTPException(
            HTTP_500_INTERNAL_SERVER_ERROR,
            f"Something went wrong, unable to {action} access",
        )


@router.post("/request", status_code=HTTP_201_CREATED)
async def create_request(
    api_request: Request,
    body: CreateRequestInput,
    auth=Depends(Auth),
) -> dict:
    """
    Create a new access request.

    Use the "revoke" query parameter to create a request to revoke access
    instead of a request to grant access.

    If no "status" is specified in the request body, will use the configured
    DEFAULT_INITIAL_STATUS. Because users can only request access to a
    policy once, each ("username", "policy_id") combination must be
    unique unless past requests' statuses are in FINAL_STATUSES.

    If no "username" is specified in the request body, will create an access
    request for the user who provided the token.
    """
    data = body.dict()
    request_id = str(uuid.uuid4())
    logger.info(
        f"Creating request. request_id: {request_id}. Received body: {data}. Revoke: {'revoke' in api_request.query_params}"
    )

    # error (if we have both policy_id and (resource_path or resource_paths))
    # OR (if we have neither)
    if bool(data.get("policy_id")) == (
        bool(data.get("resource_paths")) or bool(data.get("resource_path"))
    ):
        msg = f"The request must have either resource_paths or a policy_id."
        raise_error(logger, msg, body)

    # error if we have both role_ids and policy_id
    if data.get("role_ids") and data.get("policy_id"):
        msg = f"The request cannot have both role_ids and policy_id."
        raise_error(logger, msg, body)

    # cast resource_path as list if resource_paths is not present
    if data.get("resource_path") and not data.get("resource_paths"):
        data["resource_paths"] = [data["resource_path"]]

    resource_paths = None
    client = api_request.app.arborist_client

    if not data["policy_id"]:
        if data.get("role_ids") and data.get("resource_paths"):

            existing_roles = await arborist.list_roles(client)
            existing_role_ids = [item["id"] for item in existing_roles["roles"]]
            # Check if any role_id does not exist in arborist
            roles_not_found = list(set(data["role_ids"]) - set(existing_role_ids))
            if roles_not_found:
                raise HTTPException(
                    HTTP_400_BAD_REQUEST,
                    f"Request creation failed. The roles {roles_not_found} do not exist.",
                )

            data["policy_id"] = await arborist.create_arborist_policy_for_role_ids(
                client, data["role_ids"], data["resource_paths"]
            )
            resource_paths = data["resource_paths"]
        else:
            # else fallback to body `resource_paths` for backwards compatibility
            data["policy_id"] = await arborist.create_arborist_policy(
                client, data["resource_paths"]
            )
            resource_paths = data["resource_paths"]
    else:
        existing_policies = await arborist.list_policies(client, expand=True)

        if not arborist.get_policy_for_id(
            existing_policies["policies"], data["policy_id"]
        ):
            # Raise an exception if the policy does not exist in arborist
            raise HTTPException(
                HTTP_400_BAD_REQUEST,
                f"Request creation failed. The policy '{data['policy_id']}' does not exist.",
            )

        resource_paths = arborist.get_resource_paths_for_policy(
            existing_policies["policies"], data["policy_id"]
        )

    await auth.authorize("create", resource_paths)

    if not data.get("status"):
        data["status"] = config["DEFAULT_INITIAL_STATUS"]

    if not data.get("username"):
        logger.debug("No username provided in body, using token username")
        token_claims = await auth.get_token_claims()
        token_username = token_claims.get("context", {}).get("user", {}).get("name")
        if not token_username:
            raise HTTPException(
                HTTP_400_BAD_REQUEST,
                "Must provide a username in the request body or token",
            )
        logger.debug(f"Got username from token: {token_username}")
        data["username"] = token_username

    if "revoke" in api_request.query_params:
        if api_request.query_params["revoke"]:
            raise HTTPException(
                HTTP_400_BAD_REQUEST,
                f"The 'revoke' parameter should not be assigned a value. Received '{api_request.query_params['revoke']}'",
            )
        if data.get("resource_path"):
            # no technical reason for this; it's just not implemented/tested
            raise HTTPException(
                HTTP_400_BAD_REQUEST,
                f"The 'revoke' parameter is not compatible with the 'resource_path' body field",
            )
        data["revoke"] = True

        # check if the user has the policy we want to revoke
        if not await arborist.user_has_policy(
            client, data["username"], data["policy_id"]
        ):
            raise HTTPException(
                HTTP_400_BAD_REQUEST,
                f"Unable to revoke access: '{data['username']}' does not have access to policy '{data['policy_id']}'",
            )

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
                RequestModel.revoke == data.get("revoke", False),
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

    # remove any fields that are not stored in requests table
    [data.pop(key) for key in ["resource_path", "resource_paths", "role_ids"]]

    if draft_previous_requests:
        # reuse the draft request
        logger.debug(
            f"Found a draft request with request_id: {draft_previous_requests[0].request_id}"
        )
        request = draft_previous_requests[0]
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

    if request.status in config["UPDATE_ACCESS_STATUSES"]:
        # the access request is approved: grant/revoke access
        action = "revoke" if request.revoke else "grant"
        logger.debug(
            f"Status '{request.status}' is one of UPDATE_ACCESS_STATUSES {config['UPDATE_ACCESS_STATUSES']}, attempting to {action} access in Arborist"
        )
        await grant_or_revoke_arborist_policy(
            api_request.app.arborist_client,
            request.policy_id,
            request.username,
            request.revoke,
        )

    try:
        redirect_url = post_status_update(request.status, res, resource_paths)
    except Exception:  # if external calls or other actions fail: revert
        logger.error("Something went wrong during post-status-update actions")
        if not draft_previous_requests:
            logger.warning(f"Deleting the request that was just created ({request_id})")
            await RequestModel.delete.where(
                RequestModel.request_id == request_id
            ).gino.status()
        if request.status in config["UPDATE_ACCESS_STATUSES"]:
            logger.warning(f"Reverting the previous access {action} action")
            await grant_or_revoke_arborist_policy(
                api_request.app.arborist_client,
                request.policy_id,
                request.username,
                not request.revoke,  # revert the access we just granted or revoked
            )
        traceback.print_exc()
        raise HTTPException(
            HTTP_500_INTERNAL_SERVER_ERROR,
            "Something went wrong during post-status-update actions",
        )

    # CORS limits redirections, so we redirect on the client side
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
    logger.info(f"Updating request '{request_id}' with status '{status}'")

    existing_policies = await arborist.list_policies(
        api_request.app.arborist_client, expand=True
    )

    # only allow 1 update request at a time on the same row
    async with db.transaction():
        request = (
            await RequestModel.query.where(RequestModel.request_id == request_id)
            # lock the row by using FOR UPDATE clause
            .execution_options(populate_existing=True)
            .with_for_update()
            .gino.first_or_404()
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

        allowed_statuses = config["ALLOWED_REQUEST_STATUSES"]
        if status not in allowed_statuses:
            raise HTTPException(
                HTTP_400_BAD_REQUEST,
                f"Status '{status}' is not an allowed request status ({allowed_statuses})",
            )

        if status in config["UPDATE_ACCESS_STATUSES"]:
            # the access request is approved: grant/revoke access
            action = "revoke" if request.revoke else "grant"
            logger.debug(
                f"Status '{status}' is one of UPDATE_ACCESS_STATUSES {config['UPDATE_ACCESS_STATUSES']}, attempting to {action} access in Arborist"
            )
            await grant_or_revoke_arborist_policy(
                api_request.app.arborist_client,
                request.policy_id,
                request.username,
                request.revoke,
            )

        old_status = request.status
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

    try:
        redirect_url = post_status_update(status, res, resource_paths)
    except Exception:  # if external calls or other actions fail: revert
        logger.error("Something went wrong during post-status-update actions")
        logger.warning(f"Reverting to the previous status: {old_status}")
        request = await (
            RequestModel.update.where(RequestModel.request_id == request_id)
            .values(status=old_status, updated_time=datetime.utcnow())
            .returning(*RequestModel)
            .gino.first()
        )
        if status in config["UPDATE_ACCESS_STATUSES"]:
            logger.warning(f"Reverting the previous access {action} action")
            await grant_or_revoke_arborist_policy(
                api_request.app.arborist_client,
                request.policy_id,
                request.username,
                not request.revoke,  # revert the access we just granted or revoked
            )
        traceback.print_exc()
        raise HTTPException(
            HTTP_500_INTERNAL_SERVER_ERROR,
            "Something went wrong during post-status-update actions",
        )

    # CORS limits redirections, so we redirect on the client side
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
    logger.info(f"Deleting request '{request_id}'")
    existing_policies = await arborist.list_policies(
        api_request.app.arborist_client, expand=True
    )

    async with db.transaction():
        request = (
            await RequestModel.delete.where(RequestModel.request_id == request_id)
            .returning(*RequestModel)
            .gino.first_or_404()
        )

        # if not authorized, the exception raised by `auth.authorize`
        # triggers a transaction rollback, so we don't delete
        await auth.authorize(
            "delete",
            arborist.get_resource_paths_for_policy(
                existing_policies["policies"], request.policy_id
            ),
        )

    return {"request_id": request_id}


def raise_error(logger, msg: str, body: CreateRequestInput):
    logger.error(
        msg + f" body: {body}",
        exc_info=True,
    )
    raise HTTPException(
        HTTP_400_BAD_REQUEST,
        msg,
    )


def init_app(app: FastAPI):
    app.include_router(router, tags=["Manage"])
