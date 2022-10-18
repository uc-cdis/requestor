"""Add policy_id and revoke columns to request table

Revision ID: 42cbae986650
Revises: c0a92da5ac69
Create Date: 2021-10-04 16:39:02.821216

"""
from alembic import op
import os
import sqlalchemy as sa
from sqlalchemy.sql.sqltypes import Boolean

from cdislogging import get_logger
from gen3authz.client.arborist.client import ArboristClient

from requestor.arborist import (
    create_arborist_policy,
    get_auto_policy_id,
    get_resource_paths_for_policy,
    list_policies,
)
from requestor.config import config


# revision identifiers, used by Alembic.
revision = "42cbae986650"
down_revision = "c0a92da5ac69"
branch_labels = None
depends_on = None


logger = get_logger("requestor-migrate", log_level="debug")

custom_arborist_url = os.environ.get("ARBORIST_URL", config["ARBORIST_URL"])
if custom_arborist_url:
    arborist_client = ArboristClient(
        arborist_base_url=custom_arborist_url,
        authz_provider="requestor",
        logger=logger,
    )
else:
    arborist_client = ArboristClient(authz_provider="requestor", logger=logger)


def escape(str):
    # escape single quotes for SQL statement
    return str.replace("'", "''")


def upgrade():
    # get the list of existing policies from Arborist
    if not config["LOCAL_MIGRATION"]:
        existing_policies = list_policies(arborist_client)

    # add the new columns
    op.add_column("requests", sa.Column("policy_id", sa.String()))
    op.add_column("requests", sa.Column("revoke", Boolean))

    # get the list of existing resource_paths in the database
    connection = op.get_bind()
    offset = 0
    limit = 500
    query = f"SELECT request_id, resource_path FROM requests ORDER by request_id LIMIT {limit} OFFSET {offset}"
    results = connection.execute(query).fetchall()
    while results:
        for r in results:
            request_id, resource_path = r[0], r[1]

            # add the `policy_id` corresponding to each row's `resource_path`
            # and default `revoke` to False
            policy_id = get_auto_policy_id([resource_path])
            if not config["LOCAL_MIGRATION"] and policy_id not in existing_policies:
                created_policy_id = create_arborist_policy(
                    arborist_client=arborist_client,
                    resource_paths=[resource_path],
                )
                existing_policies.append(created_policy_id)
            connection.execute(
                f"UPDATE requests SET policy_id='{escape(policy_id)}', revoke=False WHERE request_id='{request_id}'"
            )

        # Grab another batch of rows
        offset += limit
        query = f"SELECT request_id, resource_path FROM requests ORDER by request_id LIMIT {limit} OFFSET {offset}"
        results = connection.execute(query).fetchall()

    # now that there are no null values, make the columns non-nullable
    op.alter_column("requests", "policy_id", nullable=False)
    op.alter_column("requests", "revoke", nullable=False)

    # drop the `resource_path` column, replaced by `policy_id`
    op.drop_column("requests", "resource_path")


def downgrade():
    # get the list of existing policies from Arborist
    if not config["LOCAL_MIGRATION"]:
        existing_policies = list_policies(arborist_client, expand=True)

    # get the resource_paths for the existing policies and store in dict
    if not config["LOCAL_MIGRATION"]:
        policy_resource = {}
        for policy_id in existing_policies:
            resource_paths = get_resource_paths_for_policy(
                existing_policies["policies"], policy_id
            )
            assert len(resource_paths) > 0, f"No resource_paths for policy {policy_id}"
            policy_resource[policy_id] = resource_paths

    # add the `resource_path` column back
    op.add_column("requests", sa.Column("resource_path", sa.String()))

    # convert policy_id to resource_path
    connection = op.get_bind()
    offset = 0
    limit = 500
    query = f"SELECT request_id, policy_id FROM requests ORDER by request_id LIMIT {limit} OFFSET {offset}"
    results = connection.execute(query).fetchall()
    while results:
        for r in results:
            request_id, policy_id = r[0], r[1]

            if not config["LOCAL_MIGRATION"]:
                resource_paths = policy_resource[policy_id]
            else:
                # hardcoded to avoid querying Arborist
                resource_paths = ["/test/resource/path"]
            # use the first item in the policy’s list of resources, because this
            # schema only allows 1 resource_path
            connection.execute(
                f"UPDATE requests SET resource_path='{escape(resource_paths[0])}' WHERE request_id='{request_id}'"
            )

        # Grab another batch of rows
        offset += limit
        query = f"SELECT request_id, policy_id FROM requests ORDER by request_id LIMIT {limit} OFFSET {offset}"
        results = connection.execute(query).fetchall()

    # now that there are no null values, make the column non-nullable
    op.alter_column("requests", "resource_path", nullable=False)

    # drop the `policy_id` and `revoke` columns
    op.drop_column("requests", "policy_id")
    op.drop_column("requests", "revoke")
