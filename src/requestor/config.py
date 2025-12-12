from itertools import chain
from jsonschema import validate
import os
from sqlalchemy.engine.url import make_url, URL

from gen3config import Config

from . import logger

DEFAULT_CFG_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "config-default.yaml"
)

NON_EMPTY_STRING_SCHEMA = {"type": "string", "minLength": 1}


class RequestorConfig(Config):
    def __init__(self, *args, **kwargs):
        super(RequestorConfig, self).__init__(*args, **kwargs)
        # self.post_process()

    def post_process(self) -> None:
        # raise Exception("here")
        # generate DB_URL from DB configs or env vars
        # print(self.keys())
        # print('self._configs', self._configs)
        # self["DB_URL"] = make_url(
        #     URL(
        #         drivername=os.environ.get("DB_DRIVER", self["DB_DRIVER"]),
        #         host=os.environ.get("DB_HOST", self["DB_HOST"]),
        #         port=os.environ.get("DB_PORT", self["DB_PORT"]),
        #         username=os.environ.get("DB_USER", self["DB_USER"]),
        #         password=os.environ.get("DB_PASSWORD", self["DB_PASSWORD"]),
        #         database=os.environ.get("DB_DATABASE", self["DB_DATABASE"]),
        #         query={},
        #     ),
        # )
        # TODO: f"{DB_DRIVER}://{DB_USER}:{DB_PASSWORD}@{DB_HOST}:{DB_PORT}/{DB_DATABASE}"
        self["DB_URL"] = "postgresql+asyncpg://postgres:postgres@localhost:5432/requestor_test"
        # print('self["DB_URL"]', self["DB_URL"])

    def validate(self) -> None:
        """
        Perform a series of sanity checks on a loaded config.
        """
        logger.info("Validating configuration")

        from .models import Request as RequestModel

        # print(dir(RequestModel))
        # self.allowed_params_from_db = list(RequestModel.__fields__.keys())
        self.allowed_params_from_db = [
            column.key for column in RequestModel.__table__.columns
        ]

        self.validate_statuses()
        self.validate_credentials()
        self.validate_actions()

    def validate_statuses(self) -> None:
        logger.info("Validating configuration: statuses")
        allowed_statuses = self["ALLOWED_REQUEST_STATUSES"]
        assert isinstance(
            allowed_statuses, list
        ), "ALLOWED_REQUEST_STATUSES should be a list"

        msg = "'{}' is not one of ALLOWED_REQUEST_STATUSES {}"
        for status in chain(
            [self["DEFAULT_INITIAL_STATUS"]],
            self["DRAFT_STATUSES"],
            self["UPDATE_ACCESS_STATUSES"],
            self["FINAL_STATUSES"],
        ):
            assert status in allowed_statuses, msg.format(status, allowed_statuses)

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
        logger.info("Validating configuration: actions")
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
            EXTERNAL_CALL_CONFIGS:
                let_someone_know:
                    method: POST
                    url: http://url.com
                    form:
                        - name: dataset
                          param: resource_id
                    creds: ""
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
                        "creds": {"enum": list(self["CREDENTIALS"].keys())},
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

    def validate_credentials(self):
        """
        Example:
            CREDENTIALS:
                unique_creds_id:
                    type: client_credentials
                    config:
                        client_id: ""
                        client_secret: ""
                        url: http://url.com/oauth2/token
                        scope: "space separated list of scopes"
        """
        logger.info("Validating configuration: credentials")
        schema = {
            "type": "object",
            "patternProperties": {
                ".*": {  # unique ID
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["type", "config"],
                    "properties": {
                        "type": {"enum": ["client_credentials"]},
                        "config": {},
                    },
                }
            },
        }
        validate(instance=self["CREDENTIALS"], schema=schema)

        for credentials_config in self["CREDENTIALS"].values():
            if credentials_config["type"] == "client_credentials":
                schema = {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["client_id", "client_secret", "url", "scope"],
                    "properties": {
                        "client_id": NON_EMPTY_STRING_SCHEMA,
                        "client_secret": NON_EMPTY_STRING_SCHEMA,
                        "url": NON_EMPTY_STRING_SCHEMA,
                        "scope": NON_EMPTY_STRING_SCHEMA,
                    },
                }
                validate(instance=credentials_config["config"], schema=schema)


config = RequestorConfig(DEFAULT_CFG_PATH)
