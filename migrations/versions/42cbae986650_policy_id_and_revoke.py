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
    query = f"SELECT resource_path FROM requests ORDER by resource_path LIMIT {limit} OFFSET {offset}"
    results = connection.execute(sa.text(query)).fetchall()

    # add the `policy_id` corresponding to each row's `resource_path`
    # and default `revoke` to False
    while results:
        for resource_path in set(r[0] for r in results):
            policy_id = get_auto_policy_id([resource_path])
            if (
                not config["LOCAL_MIGRATION"]
                and policy_id not in existing_policies["policies"]
            ):
                created_policy_id = create_arborist_policy(
                    arborist_client=arborist_client,
                    resource_paths=[resource_path],
                )
                existing_policies["policies"].append(created_policy_id)
            connection.execute(
                sa.text(
                    f"UPDATE requests SET policy_id='{escape(policy_id)}', revoke=False WHERE resource_path='{escape(resource_path)}'"
                )
            )

        # Grab another batch of rows
        offset += limit
        query = f"SELECT resource_path FROM requests ORDER by resource_path LIMIT {limit} OFFSET {offset}"
        results = connection.execute(sa.text(query)).fetchall()

    # now that there are no null values, make the columns non-nullable
    op.alter_column("requests", "policy_id", nullable=False)
    op.alter_column("requests", "revoke", nullable=False)

    # drop the `resource_path` column, replaced by `policy_id`
    op.drop_column("requests", "resource_path")


def downgrade():
    # get the list of existing policies from Arborist
    if not config["LOCAL_MIGRATION"]:
        existing_policies = list_policies(arborist_client, expand=True)

    # add the `resource_path` column back
    op.add_column("requests", sa.Column("resource_path", sa.String()))

    # convert policy_id to resource_path
    connection = op.get_bind()
    offset = 0
    limit = 500
    query = f"SELECT policy_id FROM requests ORDER by policy_id LIMIT {limit} OFFSET {offset}"
    results = connection.execute(sa.text(query)).fetchall()

    while results:
        for policy_id in set(r[0] for r in results):
            if not config["LOCAL_MIGRATION"]:
                resource_paths = get_resource_paths_for_policy(
                    existing_policies["policies"], policy_id
                )
                assert (
                    len(resource_paths) > 0
                ), f"No resource_paths for policy {policy_id}"
            else:
                # hardcoded to avoid querying Arborist
                resource_paths = ["/test/resource/path"]
            # use the first item in the policy’s list of resources, because this
            # schema only allows 1 resource_path
            connection.execute(
                sa.text(
                    f"UPDATE requests SET resource_path='{escape(resource_paths[0])}' WHERE policy_id='{escape(policy_id)}'"
                )
            )

        # get another batch of rows
        offset += limit
        query = f"SELECT policy_id FROM requests ORDER by policy_id LIMIT {limit} OFFSET {offset}"
        results = connection.execute(sa.text(query)).fetchall()

    # now that there are no null values, make the column non-nullable
    op.alter_column("requests", "resource_path", nullable=False)

    # drop the `policy_id` and `revoke` columns
    op.drop_column("requests", "policy_id")
    op.drop_column("requests", "revoke")
