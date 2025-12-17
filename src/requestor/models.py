from collections.abc import AsyncIterable
from datetime import datetime, timezone

from sqlalchemy import Column, DateTime, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import declarative_base
from sqlalchemy.sql.sqltypes import Boolean

from .config import config


Base = declarative_base()
# TODO rename to 'db.py'?


engine = None
async_sessionmaker_instance = None


def initialize_db() -> None:
    """
    Initialize the database enigne.
    """
    global engine, async_sessionmaker_instance
    engine = create_async_engine(
        url=config["DB_URL"],
        pool_size=config.get("DB_POOL_MIN_SIZE", 15),
        max_overflow=config["DB_POOL_MAX_SIZE"] - config["DB_POOL_MIN_SIZE"],
        echo=config["DB_ECHO"],
        connect_args={"ssl": config["DB_SSL"]} if config["DB_SSL"] else {},
        pool_pre_ping=True,
    )

    # creates AsyncSession instances
    async_sessionmaker_instance = async_sessionmaker(
        bind=engine, expire_on_commit=False
    )


def get_db_engine_and_sessionmaker() -> tuple[AsyncEngine, async_sessionmaker]:
    """
    Get the db engine and sessionmaker instances.
    """
    global engine, async_sessionmaker_instance
    if engine is None or async_sessionmaker_instance is None:
        raise Exception("Database not initialized. Call initialize_db() first.")
    return engine, async_sessionmaker_instance


class Request(Base):
    class Config:
        # Fix for error: no validator found for <class 'sqlalchemy.sql.schema.Column'>,
        # see `arbitrary_types_allowed` in Config
        arbitrary_types_allowed = True

    __tablename__ = "requests"

    request_id = Column(UUID, primary_key=True)
    username = Column(String, nullable=False)
    policy_id = Column(String, nullable=False)
    revoke = Column(Boolean, default=False, nullable=False)
    status = Column(String, nullable=False)
    created_time = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
    updated_time = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    # keep for backwards compatibility:
    resource_id = Column(String)
    resource_display_name = Column(String)

    def to_dict(self):
        d = {
            column.name: getattr(self, column.name) for column in self.__table__.columns
        }
        if hasattr(self, "redirect_url"):
            d["redirect_url"] = self.redirect_url
        return d


class DataAccessLayer:
    """
    Defines an abstract interface to manipulate the database. Instances are given a session to
    act within.
    """

    def __init__(self, db_session: AsyncSession):
        self.db_session = db_session


# TODO rename to "db"? in injected function params
async def get_data_access_layer() -> AsyncIterable[DataAccessLayer]:
    """
    Create an AsyncSession and yield an instance of the Data Access Layer,
    which acts as an abstract interface to manipulate the database.

    Can be injected as a dependency in FastAPI endpoints.
    """
    async with async_sessionmaker_instance() as session:
        async with session.begin():
            yield DataAccessLayer(session)
