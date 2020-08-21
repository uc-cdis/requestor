"""create request table

Revision ID: c0a92da5ac69
Revises:
Create Date: 2020-08-18 13:40:12.031174

"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "c0a92da5ac69"
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "requests",
        sa.Column("request_id", postgresql.UUID(), nullable=False),
        sa.Column("username", sa.String(), nullable=False),
        sa.Column("resource_path", sa.String(), nullable=False),
        sa.Column("resource_name", sa.String()),
        sa.Column("status", sa.String()),
        sa.PrimaryKeyConstraint("request_id"),
        sa.UniqueConstraint("username", "resource_path"),
    )


def downgrade():
    op.drop_table("requests")
