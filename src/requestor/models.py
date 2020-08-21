import enum

from gino.ext.starlette import Gino
from sqlalchemy import Column, String, Enum, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID

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


class RequestStatusEnum(enum.Enum):
    DRAFT = "draft"
    SUBMITTED = "submitted"
    APPROVED = "approved"
    SIGNED = "signed"
    REJECTED = "rejected"


class Request(db.Model):
    __tablename__ = "requests"

    request_id = Column(UUID, primary_key=True)
    username = Column(String, nullable=False)
    resource_path = Column(String, nullable=False)
    resource_name = Column(String)
    status = Column(Enum(RequestStatusEnum), nullable=False)

    # users can only request access to a resource once
    _uniq = UniqueConstraint("username", "resource_path")
