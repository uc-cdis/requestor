import asyncio
import httpx
import logging
from fastapi import FastAPI

try:
    from importlib.metadata import entry_points, version
except ImportError:
    from importlib_metadata import entry_points, version

from gen3authz.client.arborist.client import ArboristClient

from . import config, logger
from .models import db


def load_modules(app=None):
    for ep in entry_points()["requestor.modules"]:
        logger.info("Loading module: %s", ep.name)
        mod = ep.load()
        if app:
            init_app = getattr(mod, "init_app", None)
            if init_app:
                init_app(app)


def app_init():
    logger.info("Initializing app")
    app = FastAPI(
        title="Requestor",
        version=version("requestor"),
        debug=config.DEBUG,
        root_path=config.URL_PREFIX,
    )
    app.add_middleware(ClientDisconnectMiddleware)
    app.async_client = httpx.AsyncClient()
    db.init_app(app)
    load_modules(app)

    if config.ARBORIST_URL:
        app.arborist_client = ArboristClient(
            arborist_base_url=config.ARBORIST_URL, logger=logger
        )
    else:
        app.arborist_client = ArboristClient(logger=logger)

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
