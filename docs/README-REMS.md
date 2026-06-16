# Requestor

![version](https://img.shields.io/github/release/uc-cdis/requestor.svg) [![Apache license](http://img.shields.io/badge/license-Apache-blue.svg?style=flat)](LICENSE) [![Coverage Status](https://coveralls.io/repos/github/uc-cdis/requestor/badge.svg?branch=master)](https://coveralls.io/github/uc-cdis/requestor?branch=master)

Requestor exposes an API to manage access requests.

An introduction to Requestor's functionality, as well as diagrams of example flows, can be found in the ["Functionality and flow" documentation](docs/functionality_and_flow.md).

The server is built with [FastAPI](https://fastapi.tiangolo.com/) and packaged with [Poetry](https://poetry.eustace.io/).

## Key documentation

The documentation can be browsed in the [docs](docs) folder, and key documents are linked below.

* [Detailed API Documentation](http://petstore.swagger.io/?url=https://raw.githubusercontent.com/uc-cdis/requestor/master/docs/openapi.yaml)
* [Functionality and flow](docs/functionality_and_flow.md)
* [Requestor Statuses](docs/statuses.md)
* [Local installation](docs/local_installation.md)
* [Controlling authorization](docs/authorization.md)
* [REMS Integration](docs/rems_integration.md)

## REMS Integration

Requestor supports integration with [REMS (Resource Entitlement Management System)](https://github.com/CSCfi/rems) for data access committee (DAC)-controlled access to Gen3 resources.

When `REQUEST_BACKEND` is set to `rems` or `dual`, Requestor:

1. Creates a REMS application when a user requests access from the Gen3 portal
2. Redirects the user to REMS to complete their application
3. Receives a webhook notification from REMS when the DAC approves or revokes access
4. Grants or revokes the user's Gen3/Arborist group membership automatically

Two entitlement backends are supported via `REMS.ENTITLEMENT_BACKEND`:

| Backend | Grant | Revoke |
|---|---|---|
| `arborist` | Direct Arborist group add (`authz_provider=requestor`) | Direct Arborist group remove |
| `lambda` | AWS Lambda → identity provider (e.g. Auth0) role assignment | Lambda role removal + direct Arborist group remove (hybrid) |

See [REMS Integration](docs/rems_integration.md) for full configuration and deployment details.
