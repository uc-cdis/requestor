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
    get_auto_policy_id_for_resource_path,
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


def upgrade():
    # get the list of existing policies from Arborist
    if not config["LOCAL_MIGRATION"]:
        existing_policies = list_policies(arborist_client)

    # add the new columns
    op.add_column("requests", sa.Column("policy_id", sa.String()))
    op.add_column("requests", sa.Column("revoke", Boolean))

    # get the list of existing resource_paths in the database
    connection = op.get_bind()
    results = connection.execute("SELECT resource_path FROM requests").fetchall()
    existing_resource_paths = set(r[0] for r in results)

    # add the `policy_id` corresponding to each row's `resource_path`
    # and default `revoke` to False
    for resource_path in existing_resource_paths:
        policy_id = get_auto_policy_id_for_resource_path(resource_path)
        if not config["LOCAL_MIGRATION"] and policy_id not in existing_policies:
            create_arborist_policy(arborist_client, resource_path)
        connection.execute(
            f"UPDATE requests SET policy_id='{policy_id}', revoke=False WHERE resource_path='{resource_path}'"
        )

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

    # get the list of existing policy_ids in the database
    connection = op.get_bind()
    results = connection.execute("SELECT policy_id FROM requests").fetchall()
    existing_policy_ids = set(r[0] for r in results)

    for policy_id in existing_policy_ids:
        if not config["LOCAL_MIGRATION"]:
            resource_paths = get_resource_paths_for_policy(
                existing_policies["policies"], policy_id
            )
            assert len(resource_paths) > 0, f"No resource_paths for policy {policy_id}"
        else:
            resource_paths = ["/test/resource/path"]
        # use the first item in the policy’s list of resources, because this
        # schema only allows 1 resource_path
        connection.execute(
            f"UPDATE requests SET resource_path='{resource_paths[0]}' WHERE policy_id='{policy_id}'"
        )

    # now that there are no null values, make the column non-nullable
    op.alter_column("requests", "resource_path", nullable=False)

    # drop the `policy_id` and `revoke` columns
    op.drop_column("requests", "policy_id")
    op.drop_column("requests", "revoke")
