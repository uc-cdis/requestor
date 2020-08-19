import logging
from . import config


logger = logging.getLogger("requestor")


if config.DEBUG:
    logger.setLevel(logging.DEBUG)
