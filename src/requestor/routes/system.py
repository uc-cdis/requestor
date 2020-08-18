from fastapi import APIRouter, FastAPI, Request

from ..models import Request as RequestModel

router = APIRouter()


@router.get("/_version")
def get_version(request: Request):
    return dict(version=request.app.version)


@router.get("/_status")
async def get_status():
    await RequestModel.query.gino.first()
    return dict(status="OK")


def init_app(app: FastAPI):
    app.include_router(router, tags=["System"])
