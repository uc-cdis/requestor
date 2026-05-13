from fastapi import HTTPException
from starlette.status import HTTP_400_BAD_REQUEST, HTTP_502_BAD_GATEWAY

from .config import config
from .rems_client import RemsClient


def _first(value):
    if isinstance(value, list):
        return value[0] if value else None
    return value


def _get_rems_resid(data: dict) -> str | None:
    # Prefer the Gen3 auth/resource path because it is stable and maps back to Arborist.
    return _first(data.get("resource_paths")) or data.get("resource_path") or data.get("resource_id")


def _get_title(data: dict, resid: str) -> str:
    return data.get("resource_display_name") or data.get("title") or resid


def _get_info_url(data: dict) -> str | None:
    return data.get("study_url") or data.get("info_url") or data.get("infourl")


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

    # REMS deployments can customize frontend routes, so keep this configurable.
    # This default sends the user to the catalogue with the relevant item id available.
    return f"{rems_config['URL'].rstrip('/')}/catalogue?items={catalogue_item_id}"


async def create_rems_request(api_request, data: dict, applicant_user_id: str) -> dict:
    rems_config = config["REMS"]
    resid = _get_rems_resid(data)
    if not resid:
        raise HTTPException(
            HTTP_400_BAD_REQUEST,
            "REMS request creation requires resource_path, resource_paths, or resource_id",
        )

    title = _get_title(data, resid)
    info_url = _get_info_url(data)
    client = RemsClient(api_request.app.async_client, rems_config)

    resource = await client.ensure_resource(
        resid=resid,
        organization_id=rems_config["ORGANIZATION_ID"],
        license_ids=rems_config.get("LICENSE_IDS", []),
    )

    catalogue_item = await client.ensure_catalogue_item(
        resid=resid,
        resource_id=resource["id"],
        workflow_id=rems_config["WORKFLOW_ID"],
        form_id=rems_config.get("FORM_ID"),
        organization_id=rems_config["ORGANIZATION_ID"],
        title=title,
        info_url=info_url,
        language=rems_config.get("LANGUAGE", "en"),
    )

    application_id = None
    if rems_config.get("CREATE_APPLICATION", False):
        application = await client.create_application(
            catalogue_item_id=catalogue_item["id"],
            applicant_user_id=applicant_user_id,
        )
        if not application.get("success"):
            raise HTTPException(
                HTTP_502_BAD_GATEWAY,
                f"REMS application creation failed: {application.get('errors')}",
            )
        application_id = application.get("application-id")

    return {
        "backend": "rems",
        "resource_id": resid,
        "catalogue_item_id": catalogue_item["id"],
        "application_id": application_id,
        "redirect_url": build_rems_redirect_url(
            rems_config,
            catalogue_item_id=catalogue_item["id"],
            application_id=application_id,
        ),
    }
