# Requestor — REMS Integration

Requestor supports integration with [REMS (Resource Entitlement Management System)](https://github.com/CSCfi/rems)
for Data Access Committee (DAC)-controlled access to Gen3 resources.

This page is a summary. See [REMS Integration](rems_integration.md) for full
configuration and deployment details.

## Request creation

When `REQUEST_BACKEND` is set to `rems` or `dual`, a request from the Gen3
portal is handled by the REMS adapter:

1. Ensures a matching REMS **resource** and **catalogue item** exist for the
   Gen3 resource path (created on first use).
2. Optionally creates the REMS application directly as the applicant, when
   `REMS.CREATE_APPLICATION` is enabled (default: `false`). This requires
   REMS-side prerequisites — see [REMS Integration](rems_integration.md).
3. Returns a `redirect_url` in the response body. The portal performs the
   redirect client-side (CORS prevents a server-side redirect).

## Entitlement propagation

Independently of `REQUEST_BACKEND`, Requestor exposes
`PUT /api/v1/rems-webhook`, which REMS calls on application state changes.
The endpoint is always mounted; it is authenticated by the
`REMS_WEBHOOK_SECRET` shared secret and must be registered as an
`:event-notification-target` in the REMS `config.edn`.

On `approved` the entitlement is granted; on `revoked` / `closed` / `expired` /
`deleted` it is revoked. How the entitlement is applied is set by
`REMS.ENTITLEMENT_BACKEND`:

| Backend | Grant | Revoke |
|---|---|---|
| `arborist` | Direct Arborist group add (`authz_provider=requestor`) | Direct Arborist group remove |
| `lambda` | AWS Lambda → Auth0 role assignment; Arborist membership follows on the next `access_token_updater` sync | Lambda role removal **and** provider-agnostic Arborist group remove (hybrid) — both must succeed |

Arborist groups and their policies must be defined in `user.yaml` for **both**
backends — see [user.yaml](rems_integration.md#useryaml-both-backends).

## Key documentation

* [REMS Integration — full configuration and deployment](rems_integration.md)
* [Functionality and flow](functionality_and_flow.md)
* [Requestor Statuses](statuses.md)
* [Local installation](local_installation.md)
* [Controlling authorization](authorization.md)
* [Detailed API Documentation](http://petstore.swagger.io/?url=https://raw.githubusercontent.com/uc-cdis/requestor/master/docs/openapi.yaml)
