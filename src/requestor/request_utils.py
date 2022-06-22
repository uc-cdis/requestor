import requests
import time
from typing import Tuple
from urllib.parse import urlparse, urlencode, parse_qsl

from . import logger
from .arborist import is_path_prefix_of_path
from .config import config


def retry_wrapper(func):
    def retry_logic(*args, **kwargs):
        max_retries = kwargs.get("max_retries", config["DEFAULT_MAX_RETRIES"])
        retries = 0
        sleep_sec = 0.1
        while retries < max_retries:
            if retries != 0:
                time.sleep(sleep_sec)
                sleep_sec *= 2
            try:
                res = func(*args, **kwargs)
                return res
            except Exception as e:
                logger.error(f"  Exception {e}. Retrying...")
                retries += 1
                if retries == max_retries:
                    raise

    return retry_logic


def post_status_update(status: str, data: dict, resource_paths: list) -> str:
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
                    make_external_call(external_call_action, data)
                break  # So that we only do the action once, even if more than 1 resource_path matches

    if redirects:
        # assume there is only one redirect config. There could be more if
        # more than one action has a resource_path matching the current policy
        if len(redirects) > 1:
            logger.debug(
                f"More than one redirect actions found; will use the first one: {redirects}"
            )
        (redirect_action, data) = redirects[0]
        return get_redirect_url(redirect_action, data)
    else:
        return ""


def get_redirect_url(action_id: str, data: dict) -> str:
    conf = config["REDIRECT_CONFIGS"][action_id]
    redirect_url = conf["redirect_url"]
    base_query_params = parse_qsl(urlparse(redirect_url).query, keep_blank_values=True)
    redirect_query_params = [
        (key, str(data[key])) for key in conf.get("params", []) if data.get(key)
    ]
    final_query_params = urlencode(base_query_params + redirect_query_params)
    final_redirect_url = redirect_url.split("?")[0] + "?" + final_query_params
    logger.debug(f"End user should be redirected to: {final_redirect_url}")
    return final_redirect_url


def get_credentials(creds_id: str) -> Tuple[str, str]:
    # the config validation ensures the credentials exists
    creds = config["CREDENTIALS"][creds_id]
    if creds["type"] == "client_credentials":
        # TODO we get a fresh access token every time. A potential improvement
        # would be to cache/store the access tokens
        logger.debug(
            f"Attempting to get an access token from '{creds['config']['url']}'"
        )
        response = requests.post(
            creds["config"]["url"],
            data={
                "grant_type": "client_credentials",
                "scope": creds["config"]["scope"],
            },
            auth=(creds["config"]["client_id"], creds["config"]["client_secret"]),
        )
        response.raise_for_status()
        assert (
            "access_token" in response.json()
        ), f"Did not receive an access token from {creds['config']['url']}"
        return creds["type"], response.json()["access_token"]


@retry_wrapper
def make_external_call(external_call_id: str, data: dict) -> None:
    conf = config["EXTERNAL_CALL_CONFIGS"][external_call_id]
    requests_func = getattr(requests, conf["method"].lower())
    form_data = {
        e["name"]: data[e["param"]]
        for e in conf.get("form", [])
        if data.get(e["param"])
    } or None

    headers = {}
    if "creds" in conf:
        creds_type, creds = get_credentials(conf["creds"])
        if creds_type == "client_credentials":
            headers["authorization"] = f"bearer {creds}"

    logger.info(f"Making call to '{conf['url']}' with data: {form_data}")
    response = requests_func(
        conf["url"],
        data=form_data,
        headers=headers,
    )

    try:
        response.raise_for_status()
    except requests.exceptions.HTTPError as e:
        response_txt = response.text
        try:
            response_txt = response.json()
        except Exception:
            pass
        logger.error(f"Error making external call: {e} - {response_txt}")
        raise
    logger.debug(f"Response: {response.status_code} {response.json()}")
