# Requesting access on behalf of other users

Requestor restricts which users a caller may create access requests for. Deployments that need
callers to file requests naming somebody else must grant the policies below.

## What it adds

`create` access on service `requestor` for a resource path allows creating access requests: the
`username` in the request body is used as provided, and only falls back to the token's user when
it is absent. `create` on a resource path is the administrative permission for that resource, so
on its own that permission cannot be split.

A deployment that wants self-service requests for everyone, as in the
[example configuration](authorization.md#authorization-configuration-example) where
`all_users_policies` grants `requestor_creator` on `/programs`, would otherwise also grant every
authenticated user the ability to file requests naming somebody else. The separate
`/requestor/on_behalf` resource path expresses "these users may file requests for others,
everyone else may only file their own".

## The check

In `get_request_username` (`src/requestor/routes/manage.py`), when the `username` in the body
differs from the token's `context.user.name`:

```python
await auth.authorize("create", [f"/requestor/on_behalf/{body_username}"])
```

Two things about this check:

- It must run before the Arborist lookup of the named user in the `revoke` flow, so that an
  unauthorized caller cannot use the endpoint to learn whether that user holds a policy.
- It must run before `arborist.create_arborist_policy`, since resources and policies created
  there are not undone when the request fails.

Both hold because the check stays where the username is resolved, which is before those two
steps.

Client tokens are covered by the same rule rather than exempted: a client token has no
`context.user.name`, so every `username` it provides differs from its (absent) identity and goes
through the check. Arborist resolves the token to a client and evaluates its policies.

## Why the username is in the resource path

Arborist grants cover a resource path and everything beneath it, so putting the subject in the
path expresses both shapes with one check:

- a policy on `/requestor/on_behalf` allows acting for any user
- a policy on `/requestor/on_behalf/johndoe@example.com` allows acting for that user only

```yaml
authz:
  policies:
    - id: requestor_on_behalf_any_user
      description: Allows creating access requests for any user
      role_ids:
        - requestor_creator_role
      resource_paths:
        - /requestor/on_behalf
    - id: requestor_on_behalf_johndoe
      description: Allows creating access requests for johndoe@example.com
      role_ids:
        - requestor_creator_role
      resource_paths:
        - /requestor/on_behalf/johndoe@example.com

  users:
    datasteward@example.com:
      policies:
        - requestor_on_behalf_johndoe
```

## Usernames containing a slash

The username becomes a path segment, and a grant covers everything beneath a path, so a request
naming `alice/bob` would be authorized by a policy granted for the user `alice`. A username
containing `/` is rejected with a 400. Percent-encoding the segment would also close this, but it
changes the path a `user.yaml` policy has to name.

## Upgrading

The policies are additive - no existing permission is revoked - but until a deployment grants
them, callers can only file requests for themselves. That breaks any integration that files
requests for other users, including the administrator revocation flow documented in
[Removing access](authorization.md#removing-access). Grant the policy before upgrading.

## Testing notes

`mock_arborist_requests` in `tests/conftest.py` keys its responses on URL, so its
`authorized_resource_paths` parameter denies by resource path instead, matching Arborist's
descendant semantics rather than exact equality via `is_path_prefix_of_path` in
`src/requestor/arborist.py`. `tests/test_on_behalf.py` covers a caller with no on-behalf access,
a caller granted the whole subtree, a caller granted a single username (authorized for that
username, denied for another), a client token, a username containing `/`, a `revoke` request from
an unauthorized caller asserting `arborist.user_has_policy` is never called, and a denied request
asserting no policy is created.

## Alternatives considered

- **Require `update` on the request's resource paths instead.** No configuration change for any
  deployment, since the users who approve requests for a resource are already administrators of
  it. Rejected because it conflates approving a request with filing one for somebody else: a
  reviewer who should not originate requests would gain that ability, and a data steward who
  should file but not approve cannot be expressed.
- **A single flat `/requestor/on_behalf` switch.** Simpler to administer, but it cannot be scoped
  to particular users, which is the point of the feature.
- **Key the path on the token `sub` rather than the username.** More stable than a username,
  which can be reassigned, but Requestor has no username-to-`sub` mapping and neither does
  Arborist, whose users are keyed by name. The subject id would have to come from the request
  body, with nothing binding it to the `username` actually stored on the record.
