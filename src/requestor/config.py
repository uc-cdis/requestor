from jsonschema import validate
import os
from sqlalchemy.engine.url import make_url, URL

from gen3config import Config

DEFAULT_CFG_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "config-default.yaml"
)

NON_EMPTY_STRING_SCHEMA = {"type": "string", "minLength": 1}


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

    def validate(self, logger) -> None:
        """
        Perform a series of sanity checks on a loaded config.
        """
        logger.info("Validating configuration")

        from .models import Request as RequestModel

        self.allowed_params_from_db = [
            column.key for column in RequestModel.__table__.columns
        ]

        self.validate_statuses()
        self.validate_actions()

    def validate_statuses(self) -> None:
        msg = "'{}' is not one of ALLOWED_REQUEST_STATUSES {}"
        allowed_statuses = self["ALLOWED_REQUEST_STATUSES"]
        assert isinstance(
            allowed_statuses, list
        ), "ALLOWED_REQUEST_STATUSES should be a list"

        assert self["DEFAULT_INITIAL_STATUS"] in allowed_statuses, msg.format(
            self["DEFAULT_INITIAL_STATUS"], allowed_statuses
        )

        for s in self["DRAFT_STATUSES"]:
            assert s in allowed_statuses, msg.format(s, allowed_statuses)

        for s in self["UPDATE_ACCESS_STATUSES"]:
            assert s in allowed_statuses, msg.format(s, allowed_statuses)

        for s in self["FINAL_STATUSES"]:
            assert s in allowed_statuses, msg.format(s, allowed_statuses)

    def validate_actions(self) -> None:
        """
        Example:
            ACTION_ON_UPDATE:
                /resource/path:
                    status:
                        redirect_configs:
                            - abc
                        external_call_configs:
                            - def
        """
        self.validate_redirect_configs()
        self.validate_external_call_configs()

        allowed_statuses = self["ALLOWED_REQUEST_STATUSES"]
        schema = {
            "type": "object",
            "additionalProperties": False,
            "propertyNames": {"pattern": "/.*"},  # resource path starts with '/'
            "patternProperties": {
                ".*": {  # resource path
                    "type": "object",
                    "additionalProperties": False,
                    "propertyNames": {"pattern": f"^({'|'.join(allowed_statuses)})$"},
                    "patternProperties": {
                        ".*": {  # status
                            "type": "object",
                            "additionalProperties": False,
                            "properties": {
                                "redirect_configs": {
                                    "type": "array",
                                    "items": {
                                        "enum": list(self["REDIRECT_CONFIGS"].keys())
                                    },
                                    "maxItems": 1,  # can only do one redirect
                                },
                                "external_call_configs": {
                                    "type": "array",
                                    "items": {
                                        "enum": list(
                                            self["EXTERNAL_CALL_CONFIGS"].keys()
                                        )
                                    },
                                },
                            },
                        }
                    },
                }
            },
        }
        validate(instance=self["ACTION_ON_UPDATE"], schema=schema)

    def validate_redirect_configs(self):
        """
        Example:
            REDIRECT_CONFIGS:
                my_redirect:
                    redirect_url: http://url.com
                    params:
                        - request_id
        """
        schema = {
            "type": "object",
            "patternProperties": {
                ".*": {  # unique ID
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["redirect_url"],
                    "properties": {
                        "redirect_url": NON_EMPTY_STRING_SCHEMA,
                        "params": {
                            "type": "array",
                            "items": {"enum": self.allowed_params_from_db},
                        },
                    },
                }
            },
        }
        validate(instance=self["REDIRECT_CONFIGS"], schema=schema)

    def validate_external_call_configs(self):
        """
        Example:
            EXTERNAL_CALL_CONFIGS
                let_someone_know:
                    method: POST
                    url: http://url.com
                    form:
                        - name: dataset
                          param: resource_id
        """
        schema = {
            "type": "object",
            "patternProperties": {
                ".*": {  # unique ID
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["method", "url"],
                    "properties": {
                        "method": NON_EMPTY_STRING_SCHEMA,
                        "url": NON_EMPTY_STRING_SCHEMA,
                        "form": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "additionalProperties": False,
                                "required": ["name", "param"],
                                "properties": {
                                    "name": NON_EMPTY_STRING_SCHEMA,
                                    "param": {"enum": self.allowed_params_from_db},
                                },
                            },
                        },
                    },
                }
            },
        }
        validate(instance=self["EXTERNAL_CALL_CONFIGS"], schema=schema)

        supported_methods = ["delete", "get", "patch", "post", "put"]
        for config in self["EXTERNAL_CALL_CONFIGS"].values():
            assert (
                config["method"].lower() in supported_methods
            ), f"EXTERNAL_CALL_CONFIGS method {config['method']} is not one of {supported_methods}"


config = RequestorConfig(DEFAULT_CFG_PATH)
