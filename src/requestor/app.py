import asyncio
from fastapi import FastAPI
import httpx
import importlib
from importlib.metadata import entry_points
import os

from cdislogging import get_logger
from gen3authz.client.arborist.async_client import ArboristClient

from . import logger
from .config import config
from .db import initialize_db


def load_modules(app: FastAPI = None) -> None:
    for ep in entry_points(group="requestor.modules"):
        logger.info(f"Loading module: {ep.name}")
        mod = ep.load()
        if app:
            init_app = getattr(mod, "init_app", None)
            if init_app:
                init_app(app)


def app_init() -> FastAPI:
    logger.info("Initializing app")
    config.validate()

    debug = config["DEBUG"]
    app = FastAPI(
        title="Requestor",
        version=importlib.metadata.version("requestor"),
        debug=debug,
        root_path=config["DOCS_URL_PREFIX"],
    )
    app.add_middleware(ClientDisconnectMiddleware)
    app.async_client = httpx.AsyncClient()

    # Following will update logger level, propagate, and handlers
    get_logger("requestor", log_level="debug" if debug == True else "info")

    logger.info("Initializing Arborist client")
    custom_arborist_url = os.environ.get("ARBORIST_URL", config["ARBORIST_URL"])
    if custom_arborist_url:
        app.arborist_client = ArboristClient(
            arborist_base_url=custom_arborist_url,
            authz_provider="requestor",
            logger=get_logger("requestor.gen3authz", log_level="debug"),
        )
    else:
        app.arborist_client = ArboristClient(
            authz_provider="requestor",
            logger=get_logger("requestor.gen3authz", log_level="debug"),
        )

    initialize_db()
    load_modules(app)

    @app.on_event("shutdown")
    async def shutdown_event():
        logger.debug("Closing async client.")
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
