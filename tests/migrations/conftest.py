import os

from alembic import command
from alembic.config import Config
from asyncpg.exceptions import UndefinedTableError
from sqlalchemy import text
from sqlalchemy.exc import ProgrammingError
from sqlalchemy.ext.asyncio import create_async_engine
import pytest_asyncio

from requestor.config import config
from requestor.db import Base, get_db_engine_and_sessionmaker


@pytest_asyncio.fixture(autouse=True, scope="function")
async def reset(db_session):
    """
    Before every migration test, drop all tables and remove the current version from the `alembic_version` table, if it exists
    """
    engine, _ = get_db_engine_and_sessionmaker()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)

    try:
        await db_session.execute(text("DELETE FROM alembic_version"))
        await db_session.commit()
    except (ProgrammingError, UndefinedTableError) as e:
        if "UndefinedTableError" in str(e):
            await db_session.rollback()
        else:
            raise


class MigrationRunner:
    def __init__(self):
        self.action: str = ""
        self.target: str = ""
        current_dir = os.path.dirname(os.path.realpath(__file__))
        self.alembic_ini_path = os.path.join(current_dir, "../../alembic.ini")

    async def upgrade(self, target: str):
        self.action = "upgrade"
        self.target = target
        await self._run_alembic_command()

    async def downgrade(self, target: str):
        self.action = "downgrade"
        self.target = target
        await self._run_alembic_command()

    async def _run_alembic_command(self):
        """
        Args:
            action (str): "upgrade" or "downgrade"
            target (str): "base", "head" or revision ID
        """

        def _run_command(connection):
            alembic_cfg = Config(self.alembic_ini_path)
            alembic_cfg.attributes["connection"] = connection
            if self.action == "upgrade":
                command.upgrade(alembic_cfg, self.target)
            elif self.action == "downgrade":
                command.downgrade(alembic_cfg, self.target)
            else:
                raise Exception(f"Unknown MigrationRunner action '{self.action}'")

        engine = create_async_engine(config["DB_URL"], echo=True)
        async with engine.begin() as conn:
            await conn.run_sync(_run_command)
        await engine.dispose()
