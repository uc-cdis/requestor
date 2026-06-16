from itertools import chain
from jsonschema import validate
import os

from gen3config import Config
from sqlalchemy.engine.url import URL

from . import logger


DEFAULT_CFG_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "config-default.yaml"
)

NON_EMPTY_STRING_SCHEMA = {"type": "string", "minLength": 1}


class RequestorConfig(Config):
    def __init__(self, *args, **kwargs):
        super(RequestorConfig, self).__init__(*args, **kwargs)

    def post_process(self) -> None:
        self.setdefault("REQUEST_BACKEND", "requestor")
        self.setdefault(
            "REMS",
            {
                "ENABLED": False,
                "URL": "",
                "API_KEY": "",
                "USER_ID": "requestor",
                "ORGANIZATION_ID": "gen3",
                "WORKFLOW_ID": None,
                "FORM_ID": None,
                "LANGUAGE": "en",
                "LICENSE_IDS": [],
                "CREATE_APPLICATION": False,
                "CATALOGUE_ITEM_URL_TEMPLATE": "",
                "APPLICATION_URL_TEMPLATE": "",
            },
        )

        # generate DB_URL from DB configs or env vars
        self["DB_URL"] = URL.create(
            os.environ.get("DB_DRIVER", self["DB_DRIVER"]),
            host=os.environ.get("DB_HOST", self["DB_HOST"]),
            port=os.environ.get("DB_PORT", self["DB_PORT"]),
            username=os.environ.get("DB_USER", self["DB_USER"]),
            password=os.environ.get("DB_PASSWORD", self["DB_PASSWORD"]),
            database=os.environ.get("DB_DATABASE", self["DB_DATABASE"]),
        ).render_as_string(hide_password=False)

    def validate(self) -> None:
        """
        Perform a series of sanity checks on a loaded config.
        """
        logger.info("Validating configuration")

        from .db import Request as RequestModel

        self.allowed_params_from_db = [
            column.key for column in RequestModel.__table__.columns
        ]

        self.validate_statuses()
        self.validate_request_backend()
        self.validate_rems()
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


    def validate_request_backend(self) -> None:
        logger.info("Validating configuration: request backend")
        allowed_backends = ["requestor", "rems", "dual"]
        assert (
            self["REQUEST_BACKEND"] in allowed_backends
        ), f"REQUEST_BACKEND must be one of {allowed_backends}"

    def validate_rems(self) -> None:
        logger.info("Validating configuration: REMS")
        rems = self["REMS"]
        schema = {
            "type": "object",
            "additionalProperties": False,
            "required": [
                "ENABLED",
                "URL",
                "API_KEY",
                "USER_ID",
                "ORGANIZATION_ID",
                "WORKFLOW_ID",
                "LANGUAGE",
                "LICENSE_IDS",
                "CREATE_APPLICATION",
            ],
            "properties": {
                "ENABLED": {"type": "boolean"},
                "URL": {"type": "string"},
                "API_KEY": {"type": "string"},
                "USER_ID": {"type": "string"},
                "ORGANIZATION_ID": {"type": "string"},
                "WORKFLOW_ID": {"type": ["integer", "null"]},
                "FORM_ID": {"type": ["integer", "null"]},
                "LANGUAGE": NON_EMPTY_STRING_SCHEMA,
                "LICENSE_IDS": {"type": "array", "items": {"type": "integer"}},
                "CREATE_APPLICATION": {"type": "boolean"},
                "CATALOGUE_ITEM_URL_TEMPLATE": {"type": "string"},
                "APPLICATION_URL_TEMPLATE": {"type": "string"},
                "DEFAULT_ACCESS_DURATION_DAYS": {"type": ["integer", "number"]},
                "ENTITLEMENT_BACKEND": {"type": "string", "enum": ["arborist", "lambda"]},
                "ENTITLEMENT_LAMBDA_NAME": {"type": "string"},
                "GROUP_NAME_TEMPLATE": {"type": "string"},
                "AUTH0_ROLE_TEMPLATE": {"type": "string"},
            },
        }
        validate(instance=rems, schema=schema)

        rems_backend_enabled = self["REQUEST_BACKEND"] in ["rems", "dual"] or rems["ENABLED"]
        if rems_backend_enabled:
            assert rems["URL"], "REMS.URL is required when REQUEST_BACKEND is rems or dual"
            assert rems["API_KEY"], "REMS.API_KEY is required when REQUEST_BACKEND is rems or dual"
            assert rems["ORGANIZATION_ID"], "REMS.ORGANIZATION_ID is required when REQUEST_BACKEND is rems or dual"
            assert rems["WORKFLOW_ID"] is not None, "REMS.WORKFLOW_ID is required when REQUEST_BACKEND is rems or dual"

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
try:
    if os.environ.get("REQUESTOR_CONFIG_PATH"):
        config.load(config_path=os.environ["REQUESTOR_CONFIG_PATH"])
    else:
        CONFIG_SEARCH_FOLDERS = [
            "/src",
            "{}/.gen3/requestor".format(os.path.expanduser("~")),
        ]
        config.load(search_folders=CONFIG_SEARCH_FOLDERS)
except Exception:
    logger.warning("Unable to load config, using default config...", exc_info=True)
    config.load(config_path=DEFAULT_CFG_PATH)