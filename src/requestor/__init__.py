from cdislogging import get_logger

from . import config


log_level = "debug" if config.DEBUG else "info"
logger = get_logger("requestor", log_level=log_level)
