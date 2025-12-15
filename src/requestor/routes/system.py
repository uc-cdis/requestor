from fastapi import APIRouter, Depends, FastAPI, Request
from sqlalchemy import text

from ..models import Request as RequestModel, DataAccessLayer, get_data_access_layer


router = APIRouter()


@router.get("/_version")
def get_version(request: Request) -> dict:
    return dict(version=request.app.version)


@router.get("/_status")
async def get_status(
    data_access_layer: DataAccessLayer = Depends(get_data_access_layer),
) -> dict:
    await data_access_layer.db_session.execute(text("SELECT 1;"))
    return dict(status="OK")


def init_app(app: FastAPI) -> None:
    app.include_router(router, tags=["System"])
