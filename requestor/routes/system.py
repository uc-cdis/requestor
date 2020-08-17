from fastapi import APIRouter

from requestor.models import db, Request as RequestModel


router = APIRouter()


@router.get("/_version")
def get_version():
    version = "0.0.0"
    # TODO
    # return pkg_resources.get_distribution("requestor").version
    return dict(version=version)


@router.get("/_status")
async def get_status():
    db.session.query(RequestModel).all()
    return dict(status="OK")
