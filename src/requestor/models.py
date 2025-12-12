from collections.abc import AsyncIterable
from datetime import datetime, timezone
from pydantic import BaseModel

#from gino.ext.starlette import Gino
from sqlalchemy import Column, DateTime, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import declarative_base
from sqlalchemy.sql.sqltypes import Boolean

from .config import config


Base = declarative_base()


# db = Gino(
#     dsn=config["DB_URL"],
#     pool_min_size=config["DB_POOL_MIN_SIZE"],
#     pool_max_size=config["DB_POOL_MAX_SIZE"],
#     echo=config["DB_ECHO"],
#     ssl=config["DB_SSL"],
#     use_connection_for_request=config["DB_USE_CONNECTION_FOR_REQUEST"],
#     retry_limit=config["DB_RETRY_LIMIT"],
#     retry_interval=config["DB_RETRY_INTERVAL"],
# )


engine = create_async_engine(config["DB_URL"], echo=True)

# creates AsyncSession instances
async_sessionmaker = async_sessionmaker(engine, expire_on_commit=False)


class Request(Base):
    class Config:
        # Fix: no validator found for <class 'sqlalchemy.sql.schema.Column'>, see `arbitrary_types_allowed` in Config
        arbitrary_types_allowed = True

    __tablename__ = "requests"

    request_id = Column(UUID, primary_key=True)
    username = Column(String, nullable=False)
    policy_id = Column(String, nullable=False)
    revoke = Column(Boolean, default=False, nullable=False)
    status = Column(String, nullable=False)
    # created_time = Column(DateTime, default=datetime.utcnow, nullable=False)
    # updated_time = Column(DateTime, default=datetime.utcnow, nullable=False)
    # TODO fix sqlalchemy.exc.DBAPIError can't subtract offset-naive and offset-aware datetimes <= nvm
    created_time = Column(
        DateTime(timezone=True), default=datetime.now(timezone.utc), nullable=False
    )
    updated_time = Column(
        DateTime(timezone=True), default=datetime.now(timezone.utc), nullable=False
    )

    # keep for backwards compatibility:
    resource_id = Column(String)
    resource_display_name = Column(String)

    def to_dict(self):
        return {
            column.name: getattr(self, column.name) for column in self.__table__.columns
        }


class DataAccessLayer:
    """
    Defines an abstract interface to manipulate the database. Instances are given a session to
    act within.
    """

    def __init__(self, db_session: AsyncSession):
        self.db_session = db_session


async def get_data_access_layer() -> AsyncIterable[DataAccessLayer]:
    """
    Create an AsyncSession and yield an instance of the Data Access Layer,
    which acts as an abstract interface to manipulate the database.

    Can be injected as a dependency in FastAPI endpoints.
    """
    async with async_sessionmaker() as session:
        async with session.begin():
            yield DataAccessLayer(session)
