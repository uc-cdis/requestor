from fastapi.responses import RedirectResponse
from urllib.parse import urlparse, urlencode, parse_qsl

from . import logger
from .arborist import is_path_prefix_of_path
from .config import config


def post_status_update(status: str, data: dict, resource_paths: list):
    """
    Handle actions after a successful status update.
    """
    redirects = []
    for resource_prefix, status_actions in config["ACTION_ON_UPDATE"].items():
        for resource_path in resource_paths:
            if (
                is_path_prefix_of_path(resource_prefix, resource_path)
                and status in status_actions
            ):
                actions = status_actions[status]
                for redirect_action in actions.get("redirect_configs", []):
                    redirects.append((redirect_action, data))
                for external_call_action in actions.get("external_call_configs", []):
                    raise NotImplementedError("TODO")
                for email_action in actions.get("email_configs", []):
                    raise NotImplementedError("TODO")
                break  # So that we only do the action once, even if more than 1 resource_path matches

    # redirect *after* doing other actions
    if redirects:
        # assume there is only one redirect config.
        # this is checked during config.validate()
        (redirect_action, data) = redirects[0]
        return get_redirect_url(redirect_action, data)


def get_redirect_url(action_id: str, data: dict) -> str:
    conf = config["REDIRECT_CONFIGS"][action_id]
    redirect_url = conf["redirect_url"]
    base_query_params = parse_qsl(urlparse(redirect_url).query, keep_blank_values=True)
    redirect_query_params = [
        (key, str(data[key])) for key in conf["params"] if data[key]
    ]
    final_query_params = urlencode(base_query_params + redirect_query_params)
    final_redirect_url = redirect_url.split("?")[0] + "?" + final_query_params
    logger.debug(f"End user should be redirected to: {final_redirect_url}")
    return final_redirect_url
