import os
from sqlalchemy.engine.url import make_url, URL

from gen3config import Config

DEFAULT_CFG_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "config-default.yaml"
)


class RequestorConfig(Config):
    def __init__(self, *args, **kwargs):
        super(RequestorConfig, self).__init__(*args, **kwargs)

    def post_process(self) -> None:
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

    def validate(self) -> None:
        """
        Perform a series of sanity checks on a loaded config.
        """
        self.validate_statuses()
        self.validate_actions()

    def validate_statuses(self) -> None:
        msg = "'{}' is not one of {}"
        allowed_statuses = self["ALLOWED_REQUEST_STATUSES"]

        draft_statuses = self["DRAFT_STATUSES"]
        for s in draft_statuses:
            assert s in allowed_statuses, msg.format(s, allowed_statuses)

        assert self["DEFAULT_INITIAL_STATUS"] in allowed_statuses, msg.format(
            self["DEFAULT_INITIAL_STATUS"], allowed_statuses
        )
        assert self["DEFAULT_INITIAL_STATUS"] in draft_statuses, msg.format(
            self["DEFAULT_INITIAL_STATUS"], draft_statuses
        )

        update_access_statuses = self["UPDATE_ACCESS_STATUSES"]
        for s in update_access_statuses:
            assert s in allowed_statuses, msg.format(s, allowed_statuses)
        assert (
            self["DEFAULT_INITIAL_STATUS"] not in update_access_statuses
        ), "DEFAULT_INITIAL_STATUS cannot be one of UPDATE_ACCESS_STATUSES (if we need this, we need to add logic in `create_request`)"

        final_statuses = self["FINAL_STATUSES"]
        for s in final_statuses:
            assert s in allowed_statuses, msg.format(s, allowed_statuses)

    def validate_actions(self) -> None:
        msg = "'{}' is not one of {}"
        allowed_statuses = self["ALLOWED_REQUEST_STATUSES"]
        allowed_actions = [
            "redirect_configs",
            "external_call_configs",
            "email_configs",
        ]

        for action in self["ACTION_ON_UPDATE"].values():
            for (status, rules) in action.items():
                assert status in allowed_statuses, msg.format(status, allowed_statuses)
                for (key, rule_list) in rules.items():
                    assert key in allowed_actions, msg.format(key, allowed_actions)
                    for rule in rule_list:
                        if key == "redirect_configs":
                            assert rule in self["REDIRECT_CONFIGS"], msg.format(
                                rule, self["REDIRECT_CONFIGS"]
                            )
                        elif key == "external_call_configs":
                            assert rule in self["EXTERNAL_CALL_CONFIGS"], msg.format(
                                rule, self["EXTERNAL_CALL_CONFIGS"]
                            )
                        elif key == "email_configs":
                            assert rule in self["EMAIL_CONFIGS"], msg.format(
                                rule, self["EMAIL_CONFIGS"]
                            )

                redirects = rules.get("redirect_configs", [])
                assert len(redirects) <= 1, f"Can only do one redirect! Got {redirects}"


config = RequestorConfig(DEFAULT_CFG_PATH)
