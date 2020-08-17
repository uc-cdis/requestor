import asyncio
from fastapi import FastAPI, APIRouter
from fastapi_sqlalchemy import DBSessionMiddleware
import httpx
import logging

from requestor import config
from requestor.routes.system import router as system_router
from requestor.routes.request import router as request_router


logger = logging.getLogger("requestor")
if config.DEBUG:
    logger.setLevel(logging.DEBUG)


def app_init():
    logger.info("Initializing app")
    app = FastAPI(
        title="Requestor",
        # version=pkg_resources.get_distribution("mds").version,
        debug=config.DEBUG,
        root_path=config.URL_PREFIX,
    )
    app.add_middleware(ClientDisconnectMiddleware)
    app.add_middleware(DBSessionMiddleware, db_url=config.DB_URL)
    app.async_client = httpx.AsyncClient()

    # add routes
    app.include_router(system_router, tags=["System"])
    app.include_router(request_router, tags=["Request"])

    @app.on_event("shutdown")
    async def shutdown_event():
        logger.info("Closing async client.")
        await app.async_client.aclose()

    return app


class ClientDisconnectMiddleware:
    def __init__(self, app):
        self._app = app

    async def __call__(self, scope, receive, send):
        loop = asyncio.get_running_loop()
        rv = loop.create_task(self._app(scope, receive, send))
        waiter = None
        cancelled = False
        if scope["type"] == "http":

            def add_close_watcher():
                nonlocal waiter

                async def wait_closed():
                    nonlocal cancelled
                    while True:
                        message = await receive()
                        if message["type"] == "http.disconnect":
                            if not rv.done():
                                cancelled = True
                                rv.cancel()
                            break

                waiter = loop.create_task(wait_closed())

            scope["add_close_watcher"] = add_close_watcher
        try:
            await rv
        except asyncio.CancelledError:
            if not cancelled:
                raise
        if waiter and not waiter.done():
            waiter.cancel()
