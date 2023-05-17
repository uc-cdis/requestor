# Controlling authorization

Requestor's endpoints are protected by Arborist policies:
- To create an access request, users must have `create` access on service `requestor` for the relevant resource paths (either the resource paths provided in the request, or the resource paths for the policy provided in the request).
- To update an access request, users must have `update` access on service `requestor` for the relevant resource paths.
- To delete an access request, users must have `delete` access on service `requestor` for the relevant resource paths.
- Users can see their own access requests regardless of their access in Arborist by hitting the `GET  /request/user` endpoint.
- To see other access requests (when `GET`ting a specific access request or when querying existing access rerquests), users must have `read` access on service `requestor` for the relevant resource paths.

### Authorization configuration example

User johndoe@example.com wants to request access to dataset D. The resource path for dataset D in the `user.yaml` file is `/programs/P/projects/D`.

The authorization is flexible: we can allow specific users to request access to specific datasets, or allow all users to request access to all datasets (see the example configuration below), or something in-between.


```yaml
authz:
  # policies automatically given to authenticated users
  all_users_policies:
    - requestor_creator

  resources:
    - name: programs
      subresources:
        - name: P
          subresources:
            - name: projects
              subresources:
                - name: D

  policies:
    - id: requestor_creator
      description: Allows requesting access to any resource under "/programs"
      role_ids:
        - requestor_creator_role
      resource_paths:
        - /programs
    - id: dataset_D_reader
      description: Allows access to dataset D
      role_ids:
        - reader
      resource_paths:
        - /programs/P/projects/D

  roles:
    - id: requestor_creator_role
      permissions:
        - id: requestor_creator_action
          action:
            service: requestor
            method: create
    - id: reader
      permissions:
        - id: reader_action
          action:
            service: '*'
            method: read
```

The user can request access to dataset D by requesting access to the `dataset_D_reader` policy. The resource path for this policy is `/programs/P/projects/D`, and since the user has access to `create` in service `requestor` for all resource paths under `/programs`, the user is allowed to request access to this policy. The resulting entry in the Requestor database looks something like this:

```json
{
    "request_id": "<unique ID>",
    "username": "johndoe@example.com",
    "policy_id": "dataset_D_reader",
    "status": "DRAFT"
}
```

An administrator now needs to review this access request and approve or reject it. We can add a policy to the `user.yaml` to grant `admin@example.com` access to manage access requests for dataset D:

```yaml
authz:
  policies:
    - id: requestor_dataset_D_updater
      role_ids:
        - requestor_updater
      resource_paths:
        - /programs/P/projects/D

  roles:
    - id: requestor_updater
      permissions:
        - id: requestor_updater_action
          action:
            service: requestor
            method: update

  users:
    admin@example.com:
      policies:
        - requestor_dataset_D_updater
```

The administrator now has access to update the status of the access request. If they approve the request, johndoe@example.com is granted access to the `dataset_D_reader` policy.
