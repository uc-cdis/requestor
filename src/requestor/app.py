import asyncio
from contextlib import asynccontextmanager
from fastapi import FastAPI
# from fastapi.routing import APIRoute
import httpx
import importlib
# from importlib.metadata import entry_points, version
import os

from cdislogging import get_logger
from gen3authz.client.arborist.async_client import ArboristClient

from . import logger
from .config import config, DEFAULT_CFG_PATH  # TODO move config to __init__ for simpler import
from .models import initialize_db

# Load the configuration *before* importing models  # TODO update comment
# try:
#     if os.environ.get("REQUESTOR_CONFIG_PATH"):
#         config.load(config_path=os.environ["REQUESTOR_CONFIG_PATH"])
#     else:
#         CONFIG_SEARCH_FOLDERS = [
#             "/src",
#             "{}/.gen3/requestor".format(os.path.expanduser("~")),
#         ]
#         print('CONFIG_SEARCH_FOLDERS', CONFIG_SEARCH_FOLDERS)
#         config.load(search_folders=CONFIG_SEARCH_FOLDERS)
#         print('config', config)
# except Exception:
#     logger.warning("Unable to load config, using default config...", exc_info=True)
#     config.load(config_path=DEFAULT_CFG_PATH)

# from .models import db


def load_modules(app: FastAPI = None) -> None:
    for module_name in [
        "manage",
        "query",
        "system",
    ]:  # TODO auto iterate over directory
        mod = importlib.import_module("requestor.routes." + module_name)
        if app:
            # print(mod)
            # print(dir(mod))
            init_app = getattr(mod, "init_app", None)
            # print(module_name, init_app)
            if init_app:
                init_app(app)
    return

    # FIXME: Identify the cause for duplicate entry points (PXP-8443)
    # Added a set on entry points to dodge the intermittent duplicate modules issue
    for ep in set(entry_points()["requestor.modules"]):
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

    # db.init_app(app)
    load_modules(app)

    # @app.on_event("shutdown")
    # async def shutdown_event():
    #     logger.info("Closing async client.")
    #     await app.async_client.aclose()

    return app


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Parse the configuration, setup and instantiate necessary classes.

    This is FastAPI's way of dealing with startup logic before the app
    starts receiving requests.

    https://fastapi.tiangolo.com/advanced/events/#lifespan

    Args:
        app (fastapi.FastAPI): The FastAPI app object
    """
    # startup

    await initialize_db()
    # await check_db_connection()

    # if config["PULL_FROM_QUEUE"] and config["QUEUE_CONFIG"].get("type") == "aws_sqs":
    #     logger.info("Initiating SQS pull.")
    #     await initiate_sqs_pull()

    yield

    # teardown
    # logger.info("Closing async client.")
    await app.async_client.aclose()
    # logger.info("[Completed] Closing async client.")


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
