from gen3authz.client.arborist.client import ArboristClient
from gen3authz.client.arborist.errors import ArboristError

from . import logger


def is_path_prefix_of_path(resource_prefix, resource_path):
    """
    Return True if the arborist resource path "resource_prefix" is a
    prefix of the arborist resource path "resource_path".
    """
    prefix_list = resource_prefix.rstrip("/").split("/")
    path_list = resource_path.rstrip("/").split("/")
    if len(prefix_list) > len(path_list):
        return False
    for i, prefix_item in enumerate(prefix_list):
        if path_list[i] != prefix_item:
            return False
    return True


async def grant_user_access_to_resource(
    arborist_client: ArboristClient,
    username: str,
    resource_path: str,
    resource_description: str,
) -> int:
    # create the user
    logger.debug(f"Attempting to create user {username} in Arborist")
    await arborist_client.create_user_if_not_exist(username)

    # create the resource
    logger.debug(f"Attempting to create resource {resource_path} in Arborist")
    resources = resource_path.split("/")
    resource_name = resources[-1]
    parent_path = "/".join(resources[:-1])
    resource = {
        "name": resource_name,
        "description": resource_description,
    }
    await arborist_client.create_resource(parent_path, resource, create_parents=True)

    # Create "reader" and "storage_reader" roles in Arborist.
    # If they already exist arborist would "Do Nothing"
    roles = [
        {
            "id": "reader",
            "permissions": [
                {"id": "reader", "action": {"service": "*", "method": "read"}}
            ],
        },
        {
            "id": "storage_reader",
            "permissions": [
                {
                    "id": "storage_reader",
                    "action": {"service": "*", "method": "read-storage"},
                }
            ],
        },
    ]

    for role in roles:
        try:
            await arborist_client.update_role(role["id"], role)
        except ArboristError as e:
            logger.info(
                "An error occured while updating role - '{}', '{}'".format(
                    {role["id"]}, str(e)
                )
            )
            logger.debug(f"Attempting to create role '{role['id']}' in Arborist")
            await arborist_client.create_role(role)

    # create the policy
    policy_id = ".".join(resources[1:]) + "_reader"
    logger.debug(f"Attempting to create policy {policy_id} in Arborist")

    policy = {
        "id": policy_id,
        "description": "policy created by requestor",
        "role_ids": ["reader", "storage_reader"],
        "resource_paths": [resource_path],
    }
    await arborist_client.create_policy(policy, skip_if_exists=True)

    # grant the user access to the resource
    logger.debug(f"Attempting to grant {username} access to {policy_id}")
    status_code = await arborist_client.grant_user_policy(username, policy_id)
    if status_code != 204:
        logger.error(f"Unable to grant access, got status code: {status_code}")

    return status_code == 204
