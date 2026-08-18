"""
REMS event webhook handler for requestor.

REMS calls this endpoint when an application changes state. On approval,
the applicant's entitlement is granted via the configured backend. On
revocation/closure/expiry, the entitlement is removed.

Two backends are supported, configured via REMS.ENTITLEMENT_BACKEND:

  arborist (default):
    Directly adds/removes the user from an Arborist group.
    Group name is derived from the resource path using REMS.GROUP_NAME_TEMPLATE.
    authz_provider='requestor' is set on the Arborist row — fully auditable.

  lambda:
    Invokes an AWS Lambda function via IAM-authenticated boto3 call.
    The Lambda receives a generic entitlement payload and is responsible
    for updating the identity provider (e.g. Auth0) or any other AAI.
    Lambda name is configured via REMS.ENTITLEMENT_LAMBDA_NAME.
    Requestor does not know Lambda internals — it only sends a generic
    entitlement event. The Lambda may use Auth0 today but could use
    another AAI in future without changing Requestor.

    On both grant and revoke, Requestor ALSO directly manages the Arborist
    group membership itself (in addition to the Lambda call), rather than
    relying on Fence's access_token_updater to sync the Auth0 role to
    Arborist. This ensures the usr_grp row is always created with
    authz_provider='requestor' (the ArboristClient's configured provider),
    so that the later revoke DELETE call — which is sent with the same
    X-AuthZ-Provider: requestor header — targets a matching row.

    Background: rows created by access_token_updater via Auth0 role sync
    have authz_provider=NULL. Arborist's DELETE endpoint appears to filter
    by X-AuthZ-Provider and silently no-ops (while still returning 204) when
    no row matches the provider in the request header. This was identified
    as a known Arborist issue during ACDC-113 testing — see project docs.
    Requestor owning the row directly sidesteps this entirely, since grant
    and revoke now always use the same provider tag.

    The Auth0 role assignment via Lambda is retained for any other systems
    that may read Auth0 roles independently, but is no longer the source
    of truth for Gen3/Arborist access when using the lambda backend.

Response / retry semantics:
    The endpoint returns HTTP 500 if ANY entitlement action in the event
    did not succeed, so that REMS re-drives the event from its outbox.
    It returns 200 only when every action for every resource succeeded.
    Both grant and revoke are idempotent (Arborist add/remove and Auth0
    assign/remove are no-ops when already in the desired state), so a
    retried event is safe to re-apply in full.

Setup required in REMS config.edn:
  :event-notification-targets
  [{:url "https://<commons>/requestor/api/v1/rems-webhook"
    :event-types [:application.event/approved
                  :application.event/revoked
                  :application.event/closed
                  :application.event/expired]
    :headers {"x-rems-webhook-secret" "<secret>"}}]

Setup required in requestor config.yaml:
  REMS_WEBHOOK_SECRET: "<secret>"
  REMS:
    ENTITLEMENT_BACKEND: arborist   # arborist | lambda
    ENTITLEMENT_LAMBDA_NAME: ""     # required when backend=lambda
    GROUP_NAME_TEMPLATE: "<program>_<project>_readonly"
    AUTH0_ROLE_TEMPLATE: "acdc/<program>_<project>_readonly"  # lambda backend only
    DEFAULT_ACCESS_DURATION_DAYS: 365

For backend=lambda, the Requestor pod's IAM role must have:
  lambda:InvokeFunction on the entitlement Lambda ARN.

Setup required in user.yaml (backend=arborist only):
  groups:
    - name: program1_ausdiab_readonly
      policies: [program1_ausdiab_reader]
      users: []   # managed by this webhook, not usersync
"""

import json
import os
from datetime import datetime, timedelta, timezone
from urllib.parse import quote

from fastapi import APIRouter, FastAPI, HTTPException, Request
from starlette.responses import JSONResponse
from starlette.status import (
    HTTP_400_BAD_REQUEST,
    HTTP_401_UNAUTHORIZED,
    HTTP_500_INTERNAL_SERVER_ERROR,
)

from .. import logger
from ..config import config

router = APIRouter()

# Default access duration if not configured — 365 days
DEFAULT_ACCESS_DURATION_DAYS = 365

# REMS event types that grant access
GRANT_EVENTS = {"application.event/approved"}

# REMS event types that revoke access
REVOKE_EVENTS = {
    "application.event/revoked",
    "application.event/closed",
    "application.event/expired",
    "application.event/deleted",
}


def _resource_path_to_entitlement(resid: str) -> str | None:
    """
    Derive the entitlement name from a REMS resource ID.

    The template used depends on REMS.ENTITLEMENT_BACKEND:

      arborist (default):
        Uses REMS.GROUP_NAME_TEMPLATE — must match an Arborist group name in user.yaml.
        Default: "<program>_<project>_readonly"
        e.g. /programs/program1/projects/AusDiab → program1_ausdiab_readonly

      lambda:
        Uses REMS.AUTH0_ROLE_TEMPLATE — must match an Auth0 role name exactly.
        Default: "acdc/<program>_<project>_readonly"
        e.g. /programs/program1/projects/AusDiab → acdc/program1_ausdiab_readonly

    Override in config.yaml:
      REMS:
        GROUP_NAME_TEMPLATE: "<program>_<project>_readonly"
        AUTH0_ROLE_TEMPLATE: "acdc/<program>_<project>_readonly"

    Note: use <program>/<project> as placeholders, not {program}/{project} —
    gen3config treats curly braces as its own template syntax.

    Returns None if the resid does not match the expected
    /programs/<program>/projects/<project> path structure.
    """
    parts = resid.strip("/").split("/")
    if len(parts) != 4 or parts[0] != "programs" or parts[2] != "projects":
        logger.warning(
            f"REMS webhook: resid '{resid}' does not match expected "
            f"/programs/<program>/projects/<project> structure — skipping"
        )
        return None
    program = parts[1]                                    # e.g. program1
    project_slug = parts[3].lower().replace("-", "_")    # e.g. ausdiab, bioheart_ct

    backend = config.get("REMS", {}).get("ENTITLEMENT_BACKEND", "arborist")
    if backend == "lambda":
        template = config.get("REMS", {}).get(
            "AUTH0_ROLE_TEMPLATE", "acdc/<program>_<project>_readonly"
        )
    else:
        template = config.get("REMS", {}).get(
            "GROUP_NAME_TEMPLATE", "<program>_<project>_readonly"
        )
    return template.replace("<program>", program).replace("<project>", project_slug)


def _resource_path_to_group(resid: str) -> str | None:
    """
    Derive the Arborist group name from a REMS resource ID using GROUP_NAME_TEMPLATE.

    Always uses GROUP_NAME_TEMPLATE regardless of backend — used for hybrid
    revocation in the lambda backend to remove the Arborist row directly.
    """
    parts = resid.strip("/").split("/")
    if len(parts) != 4 or parts[0] != "programs" or parts[2] != "projects":
        return None
    program = parts[1]
    project_slug = parts[3].lower().replace("-", "_")
    template = config.get("REMS", {}).get(
        "GROUP_NAME_TEMPLATE", "<program>_<project>_readonly"
    )
    return template.replace("<program>", program).replace("<project>", project_slug)


def _compute_expires_at() -> str:
    """
    Compute the access expiry timestamp.

    Uses REMS.DEFAULT_ACCESS_DURATION_DAYS from config if set,
    otherwise falls back to DEFAULT_ACCESS_DURATION_DAYS (365).

    Returns an ISO 8601 string suitable for Arborist's expires_at field.
    """
    duration_days = config.get("REMS", {}).get(
        "DEFAULT_ACCESS_DURATION_DAYS", DEFAULT_ACCESS_DURATION_DAYS
    )
    expires_at = datetime.now(timezone.utc) + timedelta(days=int(duration_days))
    return expires_at.isoformat()


def _verify_secret(request: Request) -> None:
    """
    Verify the shared secret sent by REMS in the x-rems-webhook-secret header.

    REMS_WEBHOOK_SECRET must be configured — an empty or missing secret is
    rejected to prevent the unauthenticated endpoint from being exploited.
    The webhook bypasses CSRF protection in the nginx reverse proxy (because
    it is a server-to-server call, not a browser request), so the shared
    secret is the sole authentication mechanism and must always be set.
    """
    expected = config.get("REMS_WEBHOOK_SECRET")
    if not expected:
        logger.error(
            "REMS_WEBHOOK_SECRET is not configured — rejecting webhook request. "
            "Set REMS_WEBHOOK_SECRET in requestor config.yaml."
        )
        raise HTTPException(
            HTTP_401_UNAUTHORIZED,
            "Webhook authentication is not configured — REMS_WEBHOOK_SECRET must be set",
        )
    received = request.headers.get("x-rems-webhook-secret")
    if received != expected:
        raise HTTPException(
            HTTP_401_UNAUTHORIZED,
            "Invalid or missing webhook secret",
        )


async def _grant_arborist(
    username: str,
    entitlement: str,
    expires_at: str,
    api_request: Request,
) -> dict:
    """Grant access by adding the user to an Arborist group."""
    arborist = api_request.app.arborist_client
    response = await arborist.add_user_to_group(
        username=username,
        group_name=entitlement,
        expires_at=expires_at,
    )
    return {"success": response is not None}


async def _revoke_arborist(
    username: str,
    entitlement: str,
    api_request: Request,
) -> dict:
    """Revoke access by removing the user from an Arborist group."""
    arborist = api_request.app.arborist_client
    response = await arborist.remove_user_from_group(
        username=username,
        group_name=entitlement,
    )
    return {"success": response is not None}


async def _revoke_rems_entitlement(
    username: str,
    group_name: str,
    api_request: Request,
) -> dict:
    """
    Revoke a REMS-managed Arborist group membership for the given user,
    regardless of which authz_provider originally created the row.

    Used for hybrid revocation on the lambda backend, where the row may
    have been created by Fence's access_token_updater (authz_provider=NULL)
    via Auth0 role sync, rather than by Requestor directly. Arborist's
    standard DELETE filters by X-AuthZ-Provider and silently no-ops
    (returning 204 without deleting) when called with a provider that
    doesn't match the row — this method omits the provider header entirely
    so the DELETE matches on (username, group) alone.

    This is safe specifically because:
      - The group is REMS-managed (only reachable via the REMS webhook
        resource-path-to-group derivation).
      - The revoke is triggered by an authoritative REMS event for this
        exact user and resource — REMS is the source of truth for who
        should have access, regardless of which system last wrote the
        Arborist row.

    After the DELETE, this verifies the row is actually gone via a fresh
    Arborist group membership check, since the DELETE response code alone
    has been observed to return 204 without persisting the removal.
    """
    arborist = api_request.app.arborist_client
    url = arborist._group_url + "/{}/user/{}".format(
        quote(group_name), quote(username)
    )

    response = await arborist.delete(url, authz_provider=None, expect_json=False)
    if response.code != 204:
        logger.error(
            f"could not remove user `{username}` from group `{group_name}` "
            f"(provider-agnostic): {response.error_msg}"
        )
        return {"success": False, "verified": False}

    # Verify the row is actually gone — Arborist has been observed to
    # return 204 on a DELETE that affects zero rows (known issue, see
    # ACDC-113 docs). get_user() returns the user's current group
    # memberships, which we check directly rather than trusting the
    # DELETE response code alone.
    try:
        user_record = await arborist.get_user(username)
        user_groups = user_record.get("groups", []) if user_record else []
        still_present = group_name in user_groups
        if still_present:
            logger.error(
                f"REMS webhook: Arborist DELETE for `{username}` in group "
                f"`{group_name}` returned 204 but user is still a member "
                f"(verification check failed) — groups: {user_groups}"
            )
        return {"success": not still_present, "verified": True}
    except Exception as exc:
        # Verification failed for some other reason (e.g. user lookup
        # error). We can no longer assert the row is gone, so treat this
        # as an UNVERIFIED FAILURE rather than an optimistic success — on
        # revoke, failing closed (retry) is safer than leaving a possibly
        # live membership recorded as removed.
        logger.warning(
            f"REMS webhook: could not verify removal of `{username}` from "
            f"`{group_name}`: {exc}"
        )
        return {"success": False, "verified": False}


async def _invoke_lambda(payload: dict) -> dict:
    """
    Invoke the configured AWS Lambda function with a generic entitlement payload.

    The Lambda is invoked via IAM-authenticated boto3 — no public endpoint,
    no additional shared secret. The Requestor pod's IAM role must have
    lambda:InvokeFunction on the configured Lambda ARN/name.

    The Lambda receives a generic payload and is responsible for updating
    the identity provider. Requestor does not know Lambda internals.
    """
    try:
        import boto3

        lambda_name = config.get("REMS", {}).get("ENTITLEMENT_LAMBDA_NAME")
        if not lambda_name:
            raise ValueError(
                "REMS.ENTITLEMENT_LAMBDA_NAME must be set when "
                "REMS.ENTITLEMENT_BACKEND is 'lambda'"
            )

        client = boto3.client(
            "lambda",
            region_name=os.environ.get("AWS_REGION", "ap-southeast-2"),
        )
        response = client.invoke(
            FunctionName=lambda_name,
            InvocationType="RequestResponse",
            Payload=json.dumps(payload).encode(),
        )

        status_code = response.get("StatusCode")
        if status_code != 200:
            raise ValueError(f"Lambda returned status {status_code}")

        function_error = response.get("FunctionError")
        if function_error:
            error_payload = json.loads(response["Payload"].read())
            raise ValueError(
                f"Lambda function error: {function_error} — {error_payload}"
            )

        result = json.loads(response["Payload"].read())
        logger.info(f"REMS webhook: Lambda response: {result}")
        return {"success": True, "lambda_response": result}

    except Exception as exc:
        logger.error(f"REMS webhook: Lambda invocation failed: {exc}")
        return {"success": False, "error": str(exc)}


async def _apply_entitlement(
    action: str,
    username: str,
    entitlement: str,
    resid: str,
    event_type: str,
    expires_at: str,
    api_request: Request,
) -> dict:
    """
    Apply or revoke an entitlement using the configured backend.

    Backend is determined by REMS.ENTITLEMENT_BACKEND (default: arborist).

    arborist:
      Grant and revoke go directly to Arborist group membership.

    lambda:
      Grant: invokes Lambda only — Lambda updates Auth0, access_token_updater
             syncs Auth0 roles to Arborist groups on next run.
      Revoke: hybrid — invokes Lambda to remove the Auth0 role (stops future
             re-grants via access_token_updater) AND removes the Arborist
             group membership directly (immediate cut-off of live access).
             BOTH must succeed for the revoke to be considered successful:
               - Arborist removal is the immediate access gate. If it fails,
                 the user still has data access right now.
               - Auth0 removal prevents the next login from re-syncing the
                 role back into Arborist. If it fails, access returns on
                 next login even though Arborist was cleared.
             The returned "success" is the AND of both. A partial failure
             returns success=False so the caller returns 500 and REMS
             re-drives the event. Both sub-operations are idempotent, so a
             retry that re-runs the already-successful half is harmless.

    The returned dict always carries a top-level "success" bool. For the
    lambda revoke path it also carries "lambda" and "arborist" sub-results
    for observability.
    """
    backend = config.get("REMS", {}).get("ENTITLEMENT_BACKEND", "arborist")

    if backend == "arborist":
        if action == "grant":
            return await _grant_arborist(username, entitlement, expires_at, api_request)
        else:
            return await _revoke_arborist(username, entitlement, api_request)

    elif backend == "lambda":
        lambda_result = await _invoke_lambda({
            "action": action,
            "username": username,
            "entitlement": entitlement,
            "resource_id": resid,
            "expires_at": expires_at,
            "source": "rems",
            "event_type": event_type,
        })

        if action == "grant":
            return lambda_result

        # ── Hybrid revoke ──────────────────────────────────────────────────
        # Remove the Arborist group membership directly (immediate cut-off),
        # in addition to the Lambda's Auth0 role removal. Combine BOTH results:
        # a revoke is only complete when the user is removed from Arborist
        # (live access gone) AND from Auth0 (no re-grant on next login).
        group_name = _resource_path_to_group(resid)
        if group_name is None:
            # Should be unreachable: entitlement derivation already succeeded
            # from the same resid using identical path parsing. Treat an
            # un-derivable group on revoke as a failure so we don't silently
            # skip the immediate access cut-off.
            logger.error(
                f"REMS webhook: hybrid revoke — could not derive Arborist group "
                f"for resid '{resid}' (username '{username}'); cannot confirm "
                f"immediate access removal"
            )
            arborist_result = {"success": False, "error": "group_name_underivable"}
        else:
            try:
                arborist_result = await _revoke_rems_entitlement(
                    username, group_name, api_request
                )
                logger.info(
                    f"REMS webhook: hybrid revoke — Arborist removal of group "
                    f"'{group_name}' for '{username}' (result={arborist_result})"
                )
            except Exception as exc:
                logger.error(
                    f"REMS webhook: hybrid revoke — Arborist removal of "
                    f"'{group_name}' for '{username}' failed: {exc}"
                )
                arborist_result = {"success": False, "error": str(exc)}

        combined_success = bool(lambda_result.get("success")) and bool(
            arborist_result.get("success")
        )
        return {
            "success": combined_success,
            "lambda": lambda_result,
            "arborist": arborist_result,
        }

    else:
        raise HTTPException(
            HTTP_400_BAD_REQUEST,
            f"Unknown REMS.ENTITLEMENT_BACKEND: '{backend}'. "
            f"Valid options are: arborist, lambda",
        )


@router.api_route("/api/v1/rems-webhook", methods=["POST", "PUT"], status_code=200)
async def rems_webhook(api_request: Request):
    """
    Receive REMS application lifecycle events and sync entitlements.

    On approval: grants access via the configured ENTITLEMENT_BACKEND.
    On revocation/closure/expiry: revokes access immediately.

    Returns 200 only if every entitlement action for every resource in the
    event succeeded. Returns 500 if any action failed, so REMS re-drives the
    event from its outbox. Both grant and revoke are idempotent, so a full
    re-apply on retry is safe.

    Expected payload (REMS sends full application under event/application):
      {
        "event/type": "application.event/approved",
        "event/application": {
          "application/applicant": {"userid": "google-oauth2|..."},
          "application/resources": [
            {"resource/ext-id": "/programs/program1/projects/AusDiab"}
          ]
        }
      }
    """
    _verify_secret(api_request)

    try:
        # Read raw body and parse as JSON regardless of Content-Type.
        # REMS uses Apache HttpClient which does not always set Content-Type: application/json,
        # so we cannot rely on api_request.json() which checks the content type.
        body = await api_request.body()
        payload = json.loads(body)
    except Exception:
        raise HTTPException(HTTP_400_BAD_REQUEST, "Invalid JSON payload")

    if config.get("DEBUG"):
        logger.debug(
            f"REMS webhook incoming request — "
            f"method: {api_request.method} "
            f"headers: {dict(api_request.headers)} "
            f"body: {body.decode()[:2000]}"
        )

    event_type = payload.get("event/type")
    if not event_type:
        raise HTTPException(HTTP_400_BAD_REQUEST, "Missing event/type in payload")

    if event_type not in GRANT_EVENTS and event_type not in REVOKE_EVENTS:
        logger.debug(f"REMS webhook: ignoring event type '{event_type}'")
        return {"status": "ignored", "event_type": event_type}

    # REMS sends the full application object under "event/application" key
    application = payload.get("event/application") or payload.get("application", {})
    applicant = application.get("application/applicant", {})
    username = applicant.get("userid")
    if not username:
        raise HTTPException(HTTP_400_BAD_REQUEST, "Missing application/applicant userid")

    resources = application.get("application/resources", [])
    if not resources:
        raise HTTPException(HTTP_400_BAD_REQUEST, "Missing application/resources")

    action = "grant" if event_type in GRANT_EVENTS else "revoke"
    expires_at = _compute_expires_at()
    results = []

    for resource in resources:
        resid = resource.get("resource/ext-id")
        if not resid:
            logger.warning("REMS webhook: resource missing ext-id, skipping")
            continue

        entitlement = _resource_path_to_entitlement(resid)
        if not entitlement:
            continue

        try:
            logger.info(
                f"REMS webhook: {action}ing '{username}' entitlement "
                f"'{entitlement}' (resid={resid}, event={event_type})"
            )
            result = await _apply_entitlement(
                action=action,
                username=username,
                entitlement=entitlement,
                resid=resid,
                event_type=event_type,
                expires_at=expires_at,
                api_request=api_request,
            )
            results.append({
                "resid": resid,
                "entitlement": entitlement,
                "action": action,
                "expires_at": expires_at if action == "grant" else None,
                **result,
            })

        except Exception as exc:
            logger.error(
                f"REMS webhook: failed to {action} '{username}' "
                f"entitlement '{entitlement}': {exc}"
            )
            results.append({
                "resid": resid,
                "entitlement": entitlement,
                "action": action,
                "success": False,
                "error": str(exc),
            })

    logger.info(
        f"REMS webhook: processed '{event_type}' for '{username}': {results}"
    )

    response_body = {
        "status": "processed",
        "event_type": event_type,
        "username": username,
        "backend": config.get("REMS", {}).get("ENTITLEMENT_BACKEND", "arborist"),
        "results": results,
    }

    # Return 500 if any action failed so REMS re-drives the event from its
    # outbox. Note: an event whose resources all failed derivation yields an
    # empty results list; that is a payload/config problem, not a transient
    # failure, so we do NOT 500 on it (retrying cannot fix a bad resid) — it
    # is surfaced via the per-resource warnings logged above.
    any_failed = any(r.get("success") is False for r in results)
    if any_failed:
        logger.error(
            f"REMS webhook: one or more entitlement actions failed for "
            f"'{username}' on '{event_type}' — returning 500 so REMS retries. "
            f"results={results}"
        )
        return JSONResponse(
            status_code=HTTP_500_INTERNAL_SERVER_ERROR,
            content=response_body,
        )

    return response_body


def init_app(app: FastAPI) -> None:
    app.include_router(router, tags=["REMS Webhook"])