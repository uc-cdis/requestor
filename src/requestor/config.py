import os
from sqlalchemy.engine.url import make_url, URL

from gen3config import Config

DEFAULT_CFG_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "config-default.yaml"
)

# TODO find a way to get these automamatically from the model instead
ALLOWED_PARAMS_FROM_DB = [
    "request_id",
    "username",
    "policy_id",
    "revoke",
    "status",
    "created_time",
    "updated_time",
    "resource_id",
    "resource_display_name",
]


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
        # TODO validate REDIRECT_CONFIGS and EXTERNAL_CALL_CONFIGS
        # method should be attr of `requests` lib. And only "form"

    def validate_statuses(self) -> None:
        msg = "'{}' is not one of {}"
        allowed_statuses = self["ALLOWED_REQUEST_STATUSES"]

        draft_statuses = self["DRAFT_STATUSES"]
        for s in draft_statuses:
            assert s in allowed_statuses, msg.format(s, allowed_statuses)

        assert self["DEFAULT_INITIAL_STATUS"] in allowed_statuses, msg.format(
            self["DEFAULT_INITIAL_STATUS"], allowed_statuses
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
        """
        Expected format:
            ACTION_ON_UPDATE:
                /resource/path:
                    status:
                        redirect_configs:
                            - abc
                        external_call_configs:
                            - def
        """
        msg = "Configuration validation - '{}' is not one of {}"
        allowed_statuses = self["ALLOWED_REQUEST_STATUSES"]
        allowed_actions = ["redirect_configs", "external_call_configs"]

        assert isinstance(self["ACTION_ON_UPDATE"], dict)
        for resource_path, action in self["ACTION_ON_UPDATE"].items():
            assert resource_path.startswith(
                "/"
            ), f"ACTION_ON_UPDATE resource path '{resource_path}' should start with '/'"
            assert isinstance(action, dict)
            for (status, rules) in action.items():
                assert status in allowed_statuses, msg.format(status, allowed_statuses)
                assert isinstance(rules, dict)
                for (key, rule_list) in rules.items():
                    assert key in allowed_actions, msg.format(key, allowed_actions)
                    assert isinstance(rule_list, list)
                    for rule in rule_list:
                        if key == "redirect_configs":
                            assert rule in self["REDIRECT_CONFIGS"], msg.format(
                                rule, self["REDIRECT_CONFIGS"].keys()
                            )
                            validate_redirect_config(
                                rule, self["REDIRECT_CONFIGS"][rule]
                            )
                        elif key == "external_call_configs":
                            assert rule in self["EXTERNAL_CALL_CONFIGS"], msg.format(
                                rule, self["EXTERNAL_CALL_CONFIGS"].keys()
                            )
                            validate_external_call_config(
                                rule, self["EXTERNAL_CALL_CONFIGS"][rule]
                            )

                redirects = rules.get("redirect_configs", [])
                assert len(redirects) <= 1, f"Can only do one redirect! Got {redirects}"


def validate_redirect_config(rule_name, config):
    """
    Expected format:
        REDIRECT_CONFIGS:
            my_redirect: <--------------- rule_name
                redirect_url: http://url.com
                params:
                    - request_id
    """
    assert isinstance(config, dict)
    expected_fields = ["redirect_url", "params"]
    required_fields = ["redirect_url"]
    for field in required_fields:
        assert field in config, f"REDIRECT_CONFIGS.{rule_name} is missing '{field}'"
    for field in config:
        assert (
            field in expected_fields
        ), f"REDIRECT_CONFIGS.{rule_name} contains unexpected field '{field}'"
        assert config[field], f"REDIRECT_CONFIGS.{rule_name} '{field}' is null"
    assert isinstance(config.get("params", []), list)
    for param in config.get("params", []):
        assert param in ALLOWED_PARAMS_FROM_DB


def validate_external_call_config(rule_name, config):
    """
    Expected format:
        EXTERNAL_CALL_CONFIGS
            let_someone_know: <---------- rule_name
                method: POST
                url: http://url.com
                form:
                    - name: dataset
                    param: resource_id
    """

    def validate_form_config(rule_name, config):
        """
        Expected format:
            name: dataset
            param: resource_id
        """
        required_fields = ["name", "param"]
        for field in required_fields:
            assert (
                field in config
            ), f"EXTERNAL_CALL_CONFIGS.{rule_name}.form {config} is missing '{field}'"
        for field in config:
            assert config[
                field
            ], f"EXTERNAL_CALL_CONFIGS.{rule_name}.form '{field}' is null"
            assert (
                field in required_fields
            ), f"EXTERNAL_CALL_CONFIGS.{rule_name}.form contains unexpected field '{field}'"
        assert config["param"] in ALLOWED_PARAMS_FROM_DB

    assert isinstance(config, dict)
    expected_fields = ["method", "url", "form"]
    required_fields = ["method", "url"]
    for field in required_fields:
        assert (
            field in config
        ), f"EXTERNAL_CALL_CONFIGS.{rule_name} is missing '{field}'"
    for field in config:
        assert (
            field in expected_fields
        ), f"EXTERNAL_CALL_CONFIGS.{rule_name} contains unexpected field '{field}'"
        assert config[field], f"EXTERNAL_CALL_CONFIGS.{rule_name} '{field}' is null"
    supported_methods = ["delete", "get", "patch", "post", "put"]
    assert (
        config["method"].lower() in supported_methods
    ), f"EXTERNAL_CALL_CONFIGS method '{config['method']}' is not supported ({supported_methods})"
    assert isinstance(config.get("form", []), list)
    for form_config in config.get("form", []):
        validate_form_config(rule_name, form_config)


config = RequestorConfig(DEFAULT_CFG_PATH)
