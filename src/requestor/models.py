from datetime import datetime
from gino.ext.starlette import Gino
from sqlalchemy import Column, DateTime, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.sql.sqltypes import Boolean

from .config import config

db = Gino(
    dsn=config["DB_URL"],
    pool_min_size=config["DB_POOL_MIN_SIZE"],
    pool_max_size=config["DB_POOL_MAX_SIZE"],
    echo=config["DB_ECHO"],
    ssl=config["DB_SSL"],
    use_connection_for_request=config["DB_USE_CONNECTION_FOR_REQUEST"],
    retry_limit=config["DB_RETRY_LIMIT"],
    retry_interval=config["DB_RETRY_INTERVAL"],
)


class Request(db.Model):
    __tablename__ = "requests"

    request_id = Column(UUID, primary_key=True)
    username = Column(String, nullable=False)
    policy_id = Column(String, nullable=False)
    revoke = Column(Boolean, default=False, nullable=False)
    status = Column(String, nullable=False)
    created_time = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_time = Column(DateTime, default=datetime.utcnow, nullable=False)

    # keep for backwards compatibility:
    resource_id = Column(String)
    resource_display_name = Column(String)
