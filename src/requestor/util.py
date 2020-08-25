from fastapi.responses import RedirectResponse
from urllib.parse import urlparse, urlencode, parse_qsl

from .config import config


def post_status_update(status: str, data: dict):
    resource_path = data["resource_path"]
    redirects = []
    for resource_prefix, status_actions in config["ACTION_ON_UPDATE"].items():
        if not resource_path.startswith(resource_prefix):
            continue
        if status not in status_actions:
            return

        actions = status_actions[status]
        for redirect_action in actions.get("redirect_configs", []):
            redirects.append((redirect_action, data))
        for external_call_action in actions.get("external_call_configs", []):
            raise NotImplementedError("TODO")
        for email_action in actions.get("email_configs", []):
            raise NotImplementedError("TODO")

    # redirect *after* doing other actions
    if redirects:
        # TODO move this check to config validation:
        assert len(redirects) == 1, "Can only do one redirect!"
        (redirect_action, data) = redirects[0]
        return do_redirect_action(redirect_action, data)


def do_redirect_action(action_id, data):
    conf = config["REDIRECT_CONFIGS"][action_id]
    redirect_url = conf["redirect_url"]
    base_query_params = parse_qsl(urlparse(redirect_url).query, keep_blank_values=True)
    redirect_query_params = [(key, str(data[key])) for key in conf["params"]]
    final_query_params = urlencode(base_query_params + redirect_query_params)
    final_redirect_url = redirect_url.split("?")[0] + "?" + final_query_params
    return RedirectResponse(final_redirect_url)
