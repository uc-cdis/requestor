import pytest

from sqlalchemy import select, text
from sqlalchemy.exc import ProgrammingError
from requestor.db import Request
from tests.migrations.conftest import MigrationRunner


@pytest.mark.asyncio
async def test_c0a92da5ac69_upgrade(db_session, access_token_user_only_patcher):
    # state before the migration
    migration_runner = MigrationRunner()
    await migration_runner.downgrade("base")

    # the requests table should not exist
    query = select(Request)
    with pytest.raises(ProgrammingError, match='relation "requests" does not exist'):
        await db_session.execute(query)
    await db_session.commit()

    # run the migration
    await migration_runner.upgrade("c0a92da5ac69")

    # the requests table should now exist
    result = await db_session.execute(text("SELECT * FROM requests"))
    assert list(result.all()) == []
