from urllib.parse import quote, urljoin

import httpx
from fastapi import HTTPException
from starlette.status import HTTP_502_BAD_GATEWAY

from . import logger


class RemsClient:
    """
    Small async REMS API client used by the optional REMS request backend.

    REMS uses headers for API authentication and user impersonation. The API key
    identifies this service; x-rems-user-id identifies the REMS actor for the
    current call. For admin catalogue/resource setup we use REMS.USER_ID. For
    user-facing application creation, pass the applicant as user_id.
    """

    def __init__(self, http_client: httpx.AsyncClient, rems_config: dict):
        self.http_client = http_client
        self.base_url = rems_config["URL"].rstrip("/") + "/"
        self.api_key = rems_config["API_KEY"]
        self.service_user_id = rems_config.get("USER_ID", "requestor")

    def _url(self, path: str) -> str:
        return urljoin(self.base_url, path.lstrip("/"))

    def _headers(self, user_id: str | None = None) -> dict:
        return {
            "x-rems-api-key": self.api_key,
            "x-rems-user-id": user_id or self.service_user_id,
            "content-type": "application/json",
            "accept": "application/json",
        }

    async def _request(
        self,
        method: str,
        path: str,
        *,
        user_id: str | None = None,
        **kwargs,
    ) -> dict | list:
        try:
            response = await self.http_client.request(
                method,
                self._url(path),
                headers=self._headers(user_id),
                **kwargs,
            )
            response.raise_for_status()
            if response.text:
                return response.json()
            return {}
        except httpx.HTTPStatusError as exc:
            body = exc.response.text
            logger.error(
                f"REMS API call failed: {method} {path} -> "
                f"{exc.response.status_code}: {body}"
            )
            raise HTTPException(
                HTTP_502_BAD_GATEWAY,
                f"REMS API call failed: {exc.response.status_code}",
            ) from exc
        except httpx.HTTPError as exc:
            logger.error(f"REMS API call failed: {method} {path}: {exc}")
            raise HTTPException(
                HTTP_502_BAD_GATEWAY,
                "Unable to reach REMS API",
            ) from exc

    async def get_resource_by_resid(self, resid: str) -> dict | None:
        resources = await self._request(
            "GET",
            f"/api/resources?disabled=true&archived=true&resid={quote(resid)}",
        )
        if not resources:
            return None
        return resources[0]

    async def create_resource(
        self,
        *,
        resid: str,
        organization_id: str,
        license_ids: list[int] | None = None,
    ) -> dict:
        return await self._request(
            "POST",
            "/api/resources/create",
            json={
                "resid": resid,
                "organization": {"organization/id": organization_id},
                "licenses": license_ids or [],
            },
        )

    async def ensure_resource(
        self,
        *,
        resid: str,
        organization_id: str,
        license_ids: list[int] | None = None,
    ) -> dict:
        existing = await self.get_resource_by_resid(resid)
        if existing:
            return existing

        created = await self.create_resource(
            resid=resid,
            organization_id=organization_id,
            license_ids=license_ids,
        )
        if not created.get("success"):
            raise HTTPException(
                HTTP_502_BAD_GATEWAY,
                f"REMS resource creation failed: {created.get('errors')}",
            )
        return {"id": created["id"], "resid": resid}

    async def get_catalogue_items_for_resource(self, resid: str) -> list[dict]:
        return await self._request(
            "GET",
            f"/api/catalogue-items?disabled=true&archived=true&resource={quote(resid)}",
        )

    async def create_catalogue_item(
        self,
        *,
        resource_id: int,
        workflow_id: int,
        form_id: int | None,
        organization_id: str,
        title: str,
        info_url: str | None,
        language: str = "en",
    ) -> dict:
        localization = {"title": title}
        if info_url:
            localization["infourl"] = info_url

        payload = {
            "resid": resource_id,
            "wfid": workflow_id,
            "organization": {"organization/id": organization_id},
            "localizations": {language: localization},
            "enabled": True,
            "archived": False,
        }
        if form_id is not None:
            payload["form"] = form_id

        return await self._request(
            "POST",
            "/api/catalogue-items/create",
            json=payload,
        )

    async def ensure_catalogue_item(
        self,
        *,
        resid: str,
        resource_id: int,
        workflow_id: int,
        form_id: int | None,
        organization_id: str,
        title: str,
        info_url: str | None,
        language: str = "en",
    ) -> dict:
        existing = await self.get_catalogue_items_for_resource(resid)
        if existing:
            return existing[0]

        created = await self.create_catalogue_item(
            resource_id=resource_id,
            workflow_id=workflow_id,
            form_id=form_id,
            organization_id=organization_id,
            title=title,
            info_url=info_url,
            language=language,
        )
        if not created.get("success"):
            raise HTTPException(
                HTTP_502_BAD_GATEWAY,
                f"REMS catalogue item creation failed: {created.get('errors')}",
            )
        return {"id": created["id"]}

    async def create_application(self, *, catalogue_item_id: int, applicant_user_id: str) -> dict:
        return await self._request(
            "POST",
            "/api/applications/create",
            user_id=applicant_user_id,
            json={"catalogue-item-ids": [catalogue_item_id]},
        )
