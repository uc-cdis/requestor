from urllib.parse import quote, urljoin

import httpx
from fastapi import HTTPException
from starlette.status import HTTP_502_BAD_GATEWAY

from . import logger


class RemsClient:
    """
    Small async REMS API client used by the optional REMS request backend.

    Scope: this client only *reads* REMS catalogue state and *creates
    applications* on behalf of applicants. It deliberately does NOT create
    organizations, resources, or catalogue items. Those are governance objects
    (each catalogue item binds a workflow, form, and licenses chosen by a data
    steward) and must be provisioned deliberately by an administrator, not
    minted as a side effect of a user access request.

    REMS uses headers for API authentication and user impersonation. The API key
    identifies this service; x-rems-user-id identifies the REMS actor for the
    current call. For user-facing application creation, the API key must be
    configured to allow all users (via `api-key set-users <key>` with no user
    list) and the service account must have the `user-owner` role (via
    `grant-role user-owner <userid>`). This allows the single API key to create
    applications on behalf of any user by setting x-rems-user-id to the
    applicant's userid.
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

    async def get_active_catalogue_item_for_resource(self, resid: str) -> dict | None:
        """
        Return the active (enabled, non-archived, non-expired) catalogue item
        whose underlying resource matches `resid`, or None if the resource is
        not provisioned for access requests in REMS.

        This is a read-only lookup. If the resource has no catalogue item, the
        caller is expected to fail loudly rather than create one.
        """
        items = await self._request(
            "GET",
            f"/api/catalogue-items?resource={quote(resid)}&archived=false",
        )
        for item in items:
            if (
                item.get("enabled", True)
                and not item.get("archived", False)
                and not item.get("expired", False)
            ):
                return item
        return None

    async def create_application(
        self, *, catalogue_item_id: int, applicant_user_id: str
    ) -> dict:
        """
        Create a REMS application on behalf of the actual applicant.

        Requires the API key to be configured with no user restrictions
        (`api-key set-users <key>` with no users = all users allowed) and
        the service account to have the `user-owner` role
        (`grant-role user-owner <service-userid>`).
        """
        return await self._request(
            "POST",
            "/api/applications/create",
            user_id=applicant_user_id,
            json={"catalogue-item-ids": [catalogue_item_id]},
        )
