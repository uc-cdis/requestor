import enum
from fastapi_sqlalchemy import db
from sqlalchemy import Column, String, Enum, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.ext.declarative import declarative_base


Base = declarative_base()


class RequestStatusEnum(enum.Enum):
    DRAFT = "draft"
    SUBMITTED = "submitted"
    APPROVED = "approved"
    SIGNED = "signed"
    REJECTED = "rejected"


class Request(Base):
    __tablename__ = "request"

    request_id = Column(UUID, primary_key=True)
    username = Column(String)
    resource_path = Column(String)
    resource_name = Column(String)
    status = Column(Enum(RequestStatusEnum))

    # users can only request access to a resource once
    UniqueConstraint("username", "resource_path")
