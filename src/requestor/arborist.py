"""
Utils to interact with Arborist
"""


from functools import wraps
import inspect
import sniffio

from gen3authz.client.arborist.async_client import ArboristClient
from gen3authz.client.arborist.errors import ArboristError

from . import logger


def maybe_sync(m):
    """
    Function calls in the API code are aynsc (FastAPI), but functions calls
    in the DB migrations code are sync. Use the @maybe_sync decorator for
    functions that are called by both.
    """

    @wraps(m)
    def _wrapper(*args, **kwargs):
        coro = m(*args, **kwargs)
        try:
            sniffio.current_async_library()
        except sniffio.AsyncLibraryNotFoundError:
            pass
        else:
            return coro

        result = None
        try:
            while True:
                result = coro.send(result)
        except StopIteration as si:
            return si.value

    return _wrapper


def is_path_prefix_of_path(resource_prefix: str, resource_path: str) -> bool:
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


@maybe_sync
async def list_policies(arborist_client: ArboristClient, expand: bool = False) -> dict:
    """
    We can cache this data later if needed, but it's tricky - the length
    we can cache depends on the source of the information, so this MUST
    invalidate the cache whenever Arborist changes a policy.
    For now, just make a call to Arborist every time we need this information.
    """
    res = arborist_client.list_policies(expand=expand)
    if inspect.isawaitable(res):
        res = await res
    return res


def get_policy_for_id(existing_policies: list, policy_id: str) -> dict:
    for p in existing_policies:
        if p["id"] == policy_id:
            return p
    return None


def get_resource_paths_for_policy(expanded_policies: list, policy_id: str) -> list:
    policy = get_policy_for_id(expanded_policies, policy_id)
    if policy:
        return policy["resource_paths"]
    return []


def get_auto_policy_id_for_resource_path(resource_path: str) -> str:
    """
    For backwards compatibility, when given a `resource_path` instead of a
    `policy_id`, we automatically generate a policy with `read` and
    `read-storage` access to the provided `resource_path`.
    """
    resources = resource_path.split("/")
    policy_id = ".".join(resources[1:]) + "_accessor"
    return policy_id


async def user_has_policy(
    arborist_client: ArboristClient, username: str, policy_id: str
) -> bool:
    user = await arborist_client.get_user(username)
    for policy_data in user["policies"]:
        if policy_data["policy"] == policy_id:
            return True
    return False


@maybe_sync
async def create_arborist_policy(
    arborist_client: ArboristClient,
    resource_path: str,
    resource_description: str = None,
):
    await create_resource(arborist_client, resource_path, resource_description)

    # Create the roles needed to query and download data.
    # If they already exist arborist would "Do Nothing"
    roles = [
        {
            "id": "peregrine_reader",
            "permissions": [
                {"id": "reader", "action": {"service": "peregrine", "method": "read"}}
            ],
        },
        {
            "id": "guppy_reader",
            "permissions": [
                {"id": "reader", "action": {"service": "guppy", "method": "read"}}
            ],
        },
        {
            "id": "fence_storage_reader",
            "permissions": [
                {
                    "id": "storage_reader",
                    "action": {"service": "fence", "method": "read-storage"},
                }
            ],
        },
    ]

    for role in roles:
        try:
            res = arborist_client.update_role(role["id"], role)
            if inspect.isawaitable(res):
                await res
        except ArboristError as e:
            logger.info(
                "An error occured while updating role - '{}', '{}'".format(
                    {role["id"]}, str(e)
                )
            )
            logger.debug(f"Attempting to create role '{role['id']}' in Arborist")
            res = arborist_client.create_role(role)
            if inspect.isawaitable(res):
                await res

    # create the policy
    policy_id = get_auto_policy_id_for_resource_path(resource_path)
    logger.debug(f"Attempting to create policy {policy_id} in Arborist")
    policy = {
        "id": policy_id,
        "description": "policy created by requestor",
        "role_ids": ["peregrine_reader", "guppy_reader", "fence_storage_reader"],
        "resource_paths": [resource_path],
    }
    res = arborist_client.create_policy(policy, skip_if_exists=True)
    if inspect.isawaitable(res):
        await res

    return policy_id


@maybe_sync
async def create_arborist_policy_for_role_id(
    arborist_client: ArboristClient,
    role_id: str,
    resource_path: str,
    resource_description: str = None,
):
    await create_resource(arborist_client, resource_path, resource_description)

    # create the policy
    policy_id = get_auto_policy_id_for_role_id_and_resource_path(role_id, resource_path)
    logger.debug(f"Attempting to create policy {policy_id} in Arborist")
    policy = {
        "id": policy_id,
        "description": "policy created by requestor",
        "role_ids": [role_id],
        "resource_paths": [resource_path],
    }
    res = arborist_client.create_policy(policy, skip_if_exists=True)
    if inspect.isawaitable(res):
        await res

    return policy_id


@maybe_sync
async def create_resource(
    arborist_client: ArboristClient,
    resource_path: str,
    resource_description: str = None,
):
    # create the resource
    logger.debug(f"Attempting to create resource {resource_path} in Arborist")
    resources = resource_path.split("/")
    resource_name = resources[-1]
    parent_path = "/".join(resources[:-1])
    resource = {
        "name": resource_name,
        "description": resource_description,
    }
    res = arborist_client.create_resource(parent_path, resource, create_parents=True)
    if inspect.isawaitable(res):
        await res


def get_auto_policy_id_for_role_id_and_resource_path(
    role_id: str, resource_path: str
) -> str:
    """
    Create a policy_name given a role_id and resource path with format
    'study.[resource_path]_[role_id]'.
    For example a role_id='study_registrant' and resource_path='/study/123456'
    should have
    policy_id = 'study.123456_study_registrant'
    """
    resources = resource_path.split("/")
    policy_id = ".".join(resources[1:]) + "_" + role_id
    return policy_id


@maybe_sync
async def list_roles(arborist_client: ArboristClient) -> dict:
    """
    We can cache this data later if needed, but it's tricky - the length
    we can cache depends on the source of the information, so this MUST
    invalidate the cache whenever Arborist adds a role.
    For now, just make a call to Arborist every time we need this information.
    """
    res = arborist_client.list_roles()
    if inspect.isawaitable(res):
        res = await res

    # TODO: remove the .json after updating to newer version of gen3authz
    return res.json


def get_role_for_id(existing_roles: list, role_id: str) -> dict:
    for r in existing_roles:
        if r["id"] == role_id:
            return r
    return None


async def grant_user_access_to_policy(
    arborist_client: ArboristClient,
    username: str,
    policy_id: str,
) -> bool:
    # create the user
    logger.debug(f"Attempting to create user {username} in Arborist")
    await arborist_client.create_user_if_not_exist(username)

    # grant the user access to the resource
    logger.debug(f"Attempting to grant {username} access to {policy_id}")
    status_code = await arborist_client.grant_user_policy(username, policy_id)
    if status_code != 204:
        logger.error(f"Unable to grant access, got status code: {status_code}")

    return status_code == 204


async def revoke_user_access_to_policy(
    arborist_client: ArboristClient,
    username: str,
    policy_id: str,
) -> bool:
    # TODO: this will fail if the authz_provider is not Requestor. How to
    # handle it? Could we handle it earlier (during the request creation)?
    logger.debug(f"Attempting to revoke {username}'s access to {policy_id}")
    success = await arborist_client.revoke_user_policy(username, policy_id)
    return success == True
