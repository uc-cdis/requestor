import os
from sqlalchemy.engine.url import make_url, URL

from gen3config import Config

DEFAULT_CFG_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "config-default.yaml"
)


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

    def validate(self):
        allowed_statuses = self["ALLOWED_REQUEST_STATUSES"]
        msg = "Status '{}' is not in allowed statuses {}"
        assert self["DEFAULT_INITIAL_STATUS"] in allowed_statuses, msg.format(
            self["DEFAULT_INITIAL_STATUS"], allowed_statuses
        )
        assert self["GRANT_ACCESS_STATUS"] in allowed_statuses, msg.format(
            self["GRANT_ACCESS_STATUS"], allowed_statuses
        )

        for action in self["ACTION_ON_UPDATE"].values():
            for (status, rules) in action.items():
                assert status in allowed_statuses, msg.format(status, allowed_statuses)
                for (key, rule_list) in rules.items():
                    assert key in [
                        "redirect_configs",
                        "external_call_configs",
                        "email_configs",
                    ]
                    for rule in rule_list:
                        if key == "redirect_configs":
                            assert rule in self["REDIRECT_CONFIGS"]
                        elif key == "external_call_configs":
                            assert rule in self["EXTERNAL_CALL_CONFIGS"]
                        elif key == "email_configs":
                            assert rule in self["EMAIL_CONFIGS"]


config = RequestorConfig(DEFAULT_CFG_PATH)
