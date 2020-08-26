from authutils.token.fastapi import access_token
from fastapi import HTTPException
from fastapi.security import HTTPBearer
from starlette.status import HTTP_401_UNAUTHORIZED

from .. import logger


# auto_error=False prevents FastAPI from raising a 403 when the request
# is missing an Authorization header. Instead, we want to return a 401
# to signify that we did not recieve valid credentials
bearer = HTTPBearer(auto_error=False)


async def get_token_claims(bearer_token):
    if not bearer_token:
        err_msg = "Must provide an access token."
        logger.error(err_msg)
        raise HTTPException(
            HTTP_401_UNAUTHORIZED, err_msg,
        )

    try:
        # NOTE: token can be None if no Authorization header was provided, we
        # expect this to cause a downstream exception since it is invalid
        token_claims = await access_token("user", "openid", purpose="access")(
            bearer_token
        )
    except Exception as e:
        logger.error(f"Could not get token claims:\n{e}", exc_info=True)
        raise HTTPException(
            HTTP_401_UNAUTHORIZED,
            "Could not verify, parse, and/or validate scope from provided access token.",
        )

    return token_claims
