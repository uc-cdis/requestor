from sqlalchemy.engine.url import make_url, URL
from starlette.config import Config

# from starlette.datastructures import CommaSeparatedStrings
from starlette.datastructures import Secret


config = Config(".env")


# Server

DEBUG = config("DEBUG", cast=bool, default=True)
TESTING = config("TESTING", cast=bool, default=False)
URL_PREFIX = config("URL_PREFIX", default="/" if DEBUG else "/requestor")


# Database

DB_DRIVER = config("DB_DRIVER", default="postgresql")
DB_HOST = config("DB_HOST", default=None)
DB_PORT = config("DB_PORT", cast=int, default=None)
DB_USER = config("DB_USER", default=None)
DB_PASSWORD = config("DB_PASSWORD", cast=Secret, default=None)
DB_DATABASE = config("DB_DATABASE", default="requestor")

if TESTING:
    DB_DATABASE = DB_DATABASE + "_test"
    TEST_KEEP_DB = config("TEST_KEEP_DB", cast=bool, default=False)

DB_URL = config(
    "DB_URL",
    cast=make_url,
    default=URL(
        drivername=DB_DRIVER,
        host=DB_HOST,
        port=DB_PORT,
        username=DB_USER,
        password=DB_PASSWORD,
        database=DB_DATABASE,
    ),
)
