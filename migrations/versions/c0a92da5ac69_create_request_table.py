"""create request table

Revision ID: c0a92da5ac69
Revises:
Create Date: 2020-08-14 16:58:51.718639

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID


# revision identifiers, used by Alembic.
revision = "c0a92da5ac69"
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "request",
        sa.Column("request_id", UUID(), nullable=False),
        sa.Column("username", sa.VARCHAR(), nullable=False),
        sa.Column("resource_path", sa.VARCHAR(), nullable=False),
        sa.Column("resource_name", sa.VARCHAR(), nullable=False),
        sa.Column("status", sa.VARCHAR(), nullable=False),
        sa.PrimaryKeyConstraint("request_id", name="request_pkey"),
    )


def downgrade():
    op.drop_table("request")
