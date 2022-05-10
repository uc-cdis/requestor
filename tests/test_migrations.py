from alembic.config import main as alembic_main
from datetime import datetime
import pytest

from requestor.arborist import get_auto_policy_id_for_resource_path
from requestor.models import db


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "resource_path",
    ["/my/resource/path", "/path/with/single'|'quotes", "/path/with/2/single''quotes"],
)
async def test_42cbae986650_upgrade(resource_path):
    # before "Add policy_id and revoke columns to request table" migration
    alembic_main(["--raiseerr", "downgrade", "c0a92da5ac69"])

    # insert a request
    uuid = "571c6a1a-f21f-11ea-adc1-0242ac120002"
    date = str(datetime.now())
    sql_resource_path = resource_path.replace("'", "''")  # escape single quotes
    insert_stmt = f"INSERT INTO requests(\"request_id\", \"username\", \"resource_path\", \"resource_id\", \"resource_display_name\", \"status\", \"created_time\", \"updated_time\") VALUES ('{uuid}', 'username', '{sql_resource_path}', 'my_resource', 'My Resource', 'DRAFT', '{date}', '{date}')"
    await db.scalar(db.text(insert_stmt))

    # check that the request data was inserted correctly
    data = await db.all(db.text("SELECT * FROM requests"))
    request = {k: str(v) for row in data for k, v in row.items()}
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

    # run "Add policy_id and revoke columns to request table" migration
    alembic_main(["--raiseerr", "upgrade", "42cbae986650"])

    # check that the migration updated the request data correctly
    data = await db.all(db.text("SELECT * FROM requests"))
    assert len(data) == 1
    request = {k: v for k, v in data[0].items()}
    assert resource_path not in request
    assert request["policy_id"] == get_auto_policy_id_for_resource_path(resource_path)
    assert request["revoke"] == False


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "resource_path",
    ["/my/resource/path", "/path/with/single'|'quotes", "/path/with/2/single''quotes"],
)
async def test_42cbae986650_downgrade(resource_path):
    # after "Add policy_id and revoke columns to request table" migration
    alembic_main(["--raiseerr", "downgrade", "42cbae986650"])

    # insert a request
    uuid = "571c6a1a-f21f-11ea-adc1-0242ac120002"
    date = str(datetime.now())
    # escape single quotes
    sql_policy = get_auto_policy_id_for_resource_path(resource_path).replace("'", "''")
    insert_stmt = f"INSERT INTO requests(\"request_id\", \"username\", \"policy_id\", \"resource_id\", \"resource_display_name\", \"status\", \"revoke\", \"created_time\", \"updated_time\") VALUES ('{uuid}', 'username', '{sql_policy}', 'my_resource', 'My Resource', 'DRAFT', 'false', '{date}', '{date}')"
    await db.scalar(db.text(insert_stmt))

    # check that the request data was inserted correctly
    data = await db.all(db.text("SELECT * FROM requests"))
    request = {k: str(v) for row in data for k, v in row.items()}
    assert request == {
        "request_id": uuid,
        "username": "username",
        "resource_id": "my_resource",
        "resource_display_name": "My Resource",
        "status": "DRAFT",
        "policy_id": get_auto_policy_id_for_resource_path(resource_path),
        "revoke": "False",
        "created_time": date,
        "updated_time": date,
    }

    # downgrade to before "Add policy_id and revoke columns to request table" migration
    alembic_main(["--raiseerr", "downgrade", "c0a92da5ac69"])

    # check that the migration updated the request data correctly
    data = await db.all(db.text("SELECT * FROM requests"))
    assert len(data) == 1
    request = {k: v for k, v in data[0].items()}
    assert "policy_id" not in request
    assert "revoke" not in request
    assert request["resource_path"] == "/test/resource/path"  # hardcoded in migration
