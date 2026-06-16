# REMS Integration

Requestor integrates with [REMS (Resource Entitlement Management System)](https://github.com/CSCfi/rems)
to support Data Access Committee (DAC)-controlled access to Gen3 resources.
When a user requests access, they are redirected to REMS to submit a formal
application. The DAC reviews and approves or rejects it. On approval or
revocation, REMS notifies Requestor via a webhook, and Requestor
automatically grants or revokes the user's Gen3 access — no manual admin
intervention required.

---

## Flow diagrams

### Grant flow

```
User clicks "Request Access" in Gen3 portal
        │
        ▼
POST /request  (Requestor)
        │  creates REMS application, returns redirect URL
        ▼
User redirected to REMS → completes application form
        │
        ▼
DAC reviews application in REMS
        │
        ▼  on approval
REMS fires PUT /requestor/api/v1/rems-webhook
        │  authenticated via x-rems-webhook-secret header
        ▼
Requestor webhook handler
        │
        ├─ [arborist backend] ──────────────────────────────────────────┐
        │    add_user_to_group(username, group, expires_at=+365d)        │
        │    authz_provider='requestor' tagged on usr_grp row            │
        │    → user has access immediately                               │
        │                                                                │
        └─ [lambda backend] ────────────────────────────────────────────┘
             invoke Lambda(action=grant, entitlement=acdc/program_project)
             Lambda → Auth0 Management API → assigns role
             access_token_updater syncs Auth0 role → Arborist (≤30 min)
             → user has access within 30 minutes
```

### Revoke flow

```
DAC revokes/closes/expires application in REMS
        │
        ▼
REMS fires PUT /requestor/api/v1/rems-webhook
        │
        ▼
Requestor webhook handler
        │
        ├─ [arborist backend] ──────────────────────────────────────────┐
        │    remove_user_from_group(username, group)                     │
        │    → access removed immediately                                │
        │                                                                │
        └─ [lambda backend — hybrid] ───────────────────────────────────┘
             Step 1: invoke Lambda(action=revoke)
                     Lambda → Auth0 → removes role
                     (stops future token grants)
             Step 2: provider-agnostic Arborist DELETE
                     omits X-AuthZ-Provider header so it matches
                     any usr_grp row for this user+group regardless
                     of which provider originally created it
                     (see Known Issues below)
             Step 3: verify via get_user() that group is gone
             → access removed immediately (within token TTL ~20 min)
             If Step 2 fails: Auth0 role already removed; Arborist
             row expires naturally within 24h as fallback
```

---

## Configuration

### requestor `config.yaml`

```yaml
REQUEST_BACKEND: rems          # or "dual" to use both requestor and rems backends

REMS_WEBHOOK_SECRET: "<shared-secret>"   # must match REMS config.edn

REMS:
  ENABLED: true
  URL: "https://rems.example.org"
  API_KEY: "<rems-api-key>"
  USER_ID: "administrator"               # REMS admin user for API calls
  ORGANIZATION_ID: "MyOrg"
  WORKFLOW_ID: 1
  FORM_ID: 1
  LANGUAGE: "en"
  LICENSE_IDS: []
  CREATE_APPLICATION: true
  CATALOGUE_ITEM_URL_TEMPLATE: "https://rems.example.org/catalogue"
  APPLICATION_URL_TEMPLATE: "https://rems.example.org/application/{application_id}"
  DEFAULT_ACCESS_DURATION_DAYS: 365

  # Entitlement backend — controls how access is granted/revoked in Gen3
  ENTITLEMENT_BACKEND: arborist           # arborist | lambda

  # arborist backend: derive Arborist group name from resource path
  # <program> and <project> are substituted from /programs/<p>/projects/<q>
  GROUP_NAME_TEMPLATE: "<program>_<project>_readonly"

  # lambda backend only: Lambda ARN to invoke for Auth0 role assignment
  ENTITLEMENT_LAMBDA_NAME: "arn:aws:lambda:ap-southeast-2:123456789:function:rems-entitlement-sync"

  # lambda backend only: Auth0 role name template (must match Auth0 exactly)
  AUTH0_ROLE_TEMPLATE: "acdc/<program>_<project>_readonly"
```

### REMS `config.edn`

```clojure
:event-notification-targets
[{:url "https://data.example.org/requestor/api/v1/rems-webhook"
  :event-types [:application.event/approved
                :application.event/revoked
                :application.event/closed
                :application.event/expired]
  :headers {"x-rems-webhook-secret" "<shared-secret>"}}]
```

### nginx (revproxy)

The webhook endpoint must bypass CSRF protection since it is a
server-to-server call. Add a dedicated location block **before** the
general `/requestor/` block:

```nginx
location /requestor/api/v1/rems-webhook {
    set $proxy_service "requestor-service";
    set $upstream http://requestor-service$des_domain;
    rewrite ^/requestor/(.*) /$1 break;
    proxy_pass $upstream;
    proxy_redirect http://$host/ https://$host/requestor/;
}
```

Authentication is handled by the `x-rems-webhook-secret` shared secret
header, which Requestor validates before processing any event.

### user.yaml (arborist backend only)

For the `arborist` backend, Arborist groups must exist before the webhook
can add users to them. Define them in `user.yaml` (fence helm values):

```yaml
groups:
  - name: program1_ausdiab_readonly
    policies:
      - program1_ausdiab_reader
    users: []   # managed by webhook, not usersync

policies:
  - id: program1_ausdiab_reader
    role_ids:
      - peregrine_reader
      - guppy_reader
      - fence_storage_reader
    resource_paths:
      - /programs/program1/projects/AusDiab
```

For the `lambda` backend, groups are created by Fence's `access_token_updater`
via Auth0 role sync — no `user.yaml` group definition is required, but
matching Auth0 roles must exist in the tenant.

---

## IAM requirements (lambda backend)

The Requestor pod's IAM role must have `lambda:InvokeFunction` on the
entitlement Lambda ARN:

```json
{
  "Effect": "Allow",
  "Action": "lambda:InvokeFunction",
  "Resource": "arn:aws:lambda:ap-southeast-2:123456789:function:rems-entitlement-sync"
}
```

The Lambda itself requires:
- Secrets Manager read access for Auth0 Management API credentials
- Auth0 Management API M2M application with `read:roles` and `update:users` scopes

---

## Resource path convention

REMS resource `ext-id` values must follow the Gen3 resource path convention:

```
/programs/<program>/projects/<project>
```

Examples:
- `/programs/program1/projects/AusDiab`
- `/programs/program1/projects/BioHEART-CT`

Requestor derives the entitlement name from this path using the configured
template, substituting `<program>` and `<project>` (project is lowercased
with hyphens replaced by underscores):

```
/programs/program1/projects/BioHEART-CT
  → GROUP_NAME_TEMPLATE: "<program>_<project>_readonly"
  → group: "program1_bioheart_ct_readonly"

  → AUTH0_ROLE_TEMPLATE: "acdc/<program>_<project>_readonly"
  → Auth0 role: "acdc/program1_bioheart_ct_readonly"
```

Note: angle-bracket placeholders (`<program>`, `<project>`) are used
instead of curly braces because gen3config treats curly braces as its
own template syntax.

---

## Known issues

### Arborist DELETE provider mismatch (lambda backend)

Arborist's `DELETE /group/{group}/user/{username}` endpoint filters by the
`X-AuthZ-Provider` request header. When a `usr_grp` row has
`authz_provider=NULL` (the case for rows created by Fence's
`access_token_updater` via Auth0 role sync) and the DELETE request carries
`X-AuthZ-Provider: requestor` (sent automatically by the `gen3authz`
Python client), Arborist finds no matching rows and silently no-ops —
returning `204 No Content` without removing the row.

**Workaround (implemented):** The `_revoke_rems_entitlement()` helper in
`rems_webhook.py` calls `arborist.delete(url, authz_provider=None)`,
which suppresses the `X-AuthZ-Provider` header entirely, allowing the
DELETE to match on `(username, group)` alone. A post-delete verification
step via `arborist.get_user()` confirms the row is actually gone.

This is safe for REMS-managed groups because REMS is the authoritative
source of truth for who should have access to these resources, regardless
of which system last wrote the Arborist row.

**Upstream fix required:** Arborist's DELETE handler should return a
non-2xx response (e.g. 404) when the provider filter matches zero rows,
rather than returning 204 unconditionally. Filed for upstream attention.
