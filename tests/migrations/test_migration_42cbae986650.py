from alembic.config import main as alembic_main
from datetime import datetime
import pytest
from sqlalchemy import text

from requestor.arborist import get_auto_policy_id
from tests.migrations.conftest import MigrationRunner


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "resource_path",
    ["/my/resource/path", "/path/with/single'|'quotes", "/path/with/2/single''quotes"],
)
async def test_42cbae986650_upgrade(
    db_session, access_token_user_only_patcher, resource_path
):
    # before "Add policy_id and revoke columns to request table" migration
    migration_runner = MigrationRunner()
    await migration_runner.upgrade("c0a92da5ac69")

    # insert a request
    uuid = "571c6a1a-f21f-11ea-adc1-0242ac120002"
    date = str(datetime.now())
    sql_resource_path = resource_path.replace("'", "''")  # escape single quotes
    insert_stmt = f"INSERT INTO requests(\"request_id\", \"username\", \"resource_path\", \"resource_id\", \"resource_display_name\", \"status\", \"created_time\", \"updated_time\") VALUES ('{uuid}', 'username', '{sql_resource_path}', 'my_resource', 'My Resource', 'DRAFT', '{date}', '{date}')"
    await db_session.execute(text(insert_stmt))

    # check that the request data was inserted correctly
    # NOTE: listing columns instead of "select *" so that the "select *" statement isn't
    # cached and can be used later. If we use it before AND after the migration, we get an
    # error `asyncpg.exceptions.InvalidCachedStatementError`
    data = list(
        (
            await db_session.execute(
                text(
                    "SELECT request_id, username, resource_id, resource_display_name, status, resource_path, created_time, updated_time FROM requests"
                )
            )
        ).all()
    )
    assert len(data) == 1
    request = {k: str(v) for k, v in data[0]._mapping.items()}
    assert request == {
        "request_id": uuid,
        "username": "username",
        "resource_id": "my_resource",
        "resource_display_name": "My Resource",
        "status": "DRAFT",
        "resource_path": resource_path,
        "created_time": date,
        "updated_time": date,
    }
    await db_session.commit()

    # run "Add policy_id and revoke columns to request table" migration
    await migration_runner.upgrade("42cbae986650")

    # check that the migration updated the request data correctly
    data = list((await db_session.execute(text("SELECT * FROM requests"))).all())
    assert len(data) == 1
    request = {k: str(v) for k, v in data[0]._mapping.items()}
    assert resource_path not in request
    assert request["policy_id"] == get_auto_policy_id([resource_path])
    assert request["revoke"] == "False"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "resource_path",
    ["/my/resource/path", "/path/with/single'|'quotes", "/path/with/2/single''quotes"],
)
async def test_42cbae986650_downgrade(
    db_session, access_token_user_only_patcher, resource_path
):
    # after "Add policy_id and revoke columns to request table" migration
    migration_runner = MigrationRunner()
    await migration_runner.upgrade("42cbae986650")

    # insert a request
    uuid = "571c6a1a-f21f-11ea-adc1-0242ac120002"
    date = str(datetime.now())
    # escape single quotes
    sql_policy = get_auto_policy_id([resource_path]).replace("'", "''")
    insert_stmt = f"INSERT INTO requests(\"request_id\", \"username\", \"policy_id\", \"resource_id\", \"resource_display_name\", \"status\", \"revoke\", \"created_time\", \"updated_time\") VALUES ('{uuid}', 'username', '{sql_policy}', 'my_resource', 'My Resource', 'DRAFT', 'false', '{date}', '{date}')"
    await db_session.execute(text(insert_stmt))

    # check that the request data was inserted correctly
    data = list(
        (
            await db_session.execute(
                text(
                    "SELECT request_id, username, resource_id, resource_display_name, status, policy_id, revoke, created_time, updated_time FROM requests"
                )
            )
        ).all()
    )
    assert len(data) == 1
    request = {k: str(v) for k, v in data[0]._mapping.items()}
    assert request == {
        "request_id": uuid,
        "username": "username",
        "resource_id": "my_resource",
        "resource_display_name": "My Resource",
        "status": "DRAFT",
        "policy_id": get_auto_policy_id([resource_path]),
        "revoke": "False",
        "created_time": date,
        "updated_time": date,
    }
    await db_session.commit()

    # downgrade to before "Add policy_id and revoke columns to request table" migration
    await migration_runner.downgrade("c0a92da5ac69")

    # check that the migration updated the request data correctly
    data = list((await db_session.execute(text("SELECT * FROM requests"))).all())
    assert len(data) == 1
    request = {k: str(v) for k, v in data[0]._mapping.items()}
    assert "policy_id" not in request
    assert "revoke" not in request
    assert request["resource_path"] == "/test/resource/path"  # hardcoded in migration
