from fastapi import HTTPException
from starlette.status import (
    HTTP_400_BAD_REQUEST,
    HTTP_404_NOT_FOUND,
    HTTP_502_BAD_GATEWAY,
)

from . import logger
from .config import config
from .rems_client import RemsClient


def _first(value):
    if isinstance(value, list):
        return value[0] if value else None
    return value


def _get_rems_resid(data: dict) -> str | None:
    # Prefer the Gen3 auth/resource path because it is stable and maps back to Arborist.
    return _first(data.get("resource_paths")) or data.get("resource_path") or data.get("resource_id")


def build_rems_redirect_url(rems_config: dict, *, catalogue_item_id: int, application_id: int | None = None) -> str:
    if application_id and rems_config.get("APPLICATION_URL_TEMPLATE"):
        return rems_config["APPLICATION_URL_TEMPLATE"].format(
            application_id=application_id,
            catalogue_item_id=catalogue_item_id,
        )

    if rems_config.get("CATALOGUE_ITEM_URL_TEMPLATE"):
        return rems_config["CATALOGUE_ITEM_URL_TEMPLATE"].format(
            catalogue_item_id=catalogue_item_id,
        )

    return f"{rems_config['URL'].rstrip('/')}/catalogue?items={catalogue_item_id}"


async def create_rems_request(api_request, data: dict, applicant_user_id: str) -> dict:
    """
    Route an access request to REMS.

    This looks up the catalogue item already provisioned for the resource and,
    if configured, creates an application against it on behalf of the applicant.
    It does NOT create resources, catalogue items, or organizations — those must
    be provisioned deliberately by an administrator. If the resource has no
    active catalogue item, this fails with a clear error rather than fabricating
    one.
    """
    rems_config = config["REMS"]
    resid = _get_rems_resid(data)
    if not resid:
        raise HTTPException(
            HTTP_400_BAD_REQUEST,
            "REMS request creation requires resource_path, resource_paths, or resource_id",
        )

    client = RemsClient(api_request.app.async_client, rems_config)

    catalogue_item = await client.get_active_catalogue_item_for_resource(resid)
    if not catalogue_item:
        logger.error(
            f"No active REMS catalogue item is provisioned for resource '{resid}'"
        )
        raise HTTPException(
            HTTP_404_NOT_FOUND,
            f"Resource '{resid}' is not provisioned for access requests in REMS. "
            "A catalogue item must be configured by an administrator before this "
            "resource can be requested.",
        )

    catalogue_item_id = catalogue_item["id"]

    application_id = None
    if rems_config.get("CREATE_APPLICATION", False):
        # Create the application directly as the applicant.
        # Prerequisites (run once on REMS deployment):
        #   grant-role user-owner <USER_ID>
        #   api-key set-users <API_KEY>   (no users = all users allowed)
        application = await client.create_application(
            catalogue_item_id=catalogue_item_id,
            applicant_user_id=applicant_user_id,
        )
        if not application.get("success"):
            raise HTTPException(
                HTTP_502_BAD_GATEWAY,
                f"REMS application creation failed: {application.get('errors')}",
            )
        application_id = application.get("application-id")
        logger.info(
            f"Created REMS application {application_id} for user '{applicant_user_id}'"
        )

    return {
        "backend": "rems",
        "resource_id": resid,
        "catalogue_item_id": catalogue_item_id,
        "application_id": application_id,
        "redirect_url": build_rems_redirect_url(
            rems_config,
            catalogue_item_id=catalogue_item_id,
            application_id=application_id,
        ),
    }
