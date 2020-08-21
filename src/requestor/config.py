import os
from os.path import expanduser
from sqlalchemy.engine.url import make_url, URL

from gen3config import Config

DEFAULT_CFG_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "config-default.yaml"
)
CONFIG_SEARCH_FOLDERS = ["/var/www/fence", "{}/.gen3/requestor".format(expanduser("~"))]


class RequestorConfig(Config):
    def __init__(self, *args, **kwargs):
        super(RequestorConfig, self).__init__(*args, **kwargs)

    def post_process(self):
        # generate DB_URL from DB configs
        self["DB_URL"] = make_url(
            URL(
                drivername=self["DB_DRIVER"],
                host=self["DB_HOST"],
                port=self["DB_PORT"],
                username=self["DB_USER"],
                password=self["DB_PASSWORD"],
                database=self["DB_DATABASE"],
            ),
        )


config = RequestorConfig(DEFAULT_CFG_PATH)
if os.environ.get("REQUESTOR_CONFIG_PATH"):
    config.load(
        search_folders=CONFIG_SEARCH_FOLDERS,
        config_path=os.environ["REQUESTOR_CONFIG_PATH"],
    )
else:
    config.load(search_folders=CONFIG_SEARCH_FOLDERS)
