from gen3authz.client.arborist.client import ArboristClient

from . import logger


async def grant_user_access_to_resource(
    arborist_client: ArboristClient,
    username: str,
    resource_path: str,
    resource_description: str,
) -> int:
    """
    TODO: cache things that already exist
    """
    # create the user
    await arborist_client.create_user_if_not_exist(username)

    # create the resource
    resources = resource_path.split("/")
    resource_name = resources[-1]
    parent_path = "/".join(resources[:-1])
    resource = {
        "name": resource_name,
        "description": resource_description,
    }
    await arborist_client.create_resource(parent_path, resource, create_parents=True)

    # create the policy
    policy_id = ".".join(resources[1:]) + "_reader"
    # assume "reader" and "storage_reader" roles already exist,
    # what could go wrong :-) (TODO)
    policy = {
        "id": policy_id,
        "role_ids": ["reader", "storage_reader"],
        "resource_paths": [resource_path],
    }
    await arborist_client.create_policy(policy, skip_if_exists=True)

    # grant the user access to the resource
    status_code = await arborist_client.grant_user_policy(username, policy_id)
    if status_code != 204:
        logger.error(f"Unable to grant access, got status code: {status_code}")

    return status_code == 204
