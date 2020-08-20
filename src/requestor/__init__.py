import logging
from . import config


logger = logging.getLogger("requestor")
logging.basicConfig(level=logging.WARNING)


if config.DEBUG:
    logger.setLevel(logging.DEBUG)
    logging.basicConfig(level=logging.DEBUG)
