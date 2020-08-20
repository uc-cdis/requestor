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
DB_POOL_MIN_SIZE = config("DB_POOL_MIN_SIZE", cast=int, default=1)
DB_POOL_MAX_SIZE = config("DB_POOL_MAX_SIZE", cast=int, default=16)
DB_ECHO = config("DB_ECHO", cast=bool, default=False)
DB_SSL = config("DB_SSL", default=None)
DB_USE_CONNECTION_FOR_REQUEST = config(
    "DB_USE_CONNECTION_FOR_REQUEST", cast=bool, default=True
)
DB_RETRY_LIMIT = config("DB_RETRY_LIMIT", cast=int, default=1)
DB_RETRY_INTERVAL = config("DB_RETRY_INTERVAL", cast=int, default=1)

# Other

ARBORIST_URL = config("ARBORIST_URL", default=None)
