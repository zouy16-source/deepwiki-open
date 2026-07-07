import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from .config import settings

bearer = HTTPBearer(auto_error=False)


def current_subject(
    cred: HTTPAuthorizationCredentials | None = Depends(bearer),
) -> str:
    """Resolve the acting user from the internal JWT issued by the web/ BFF."""
    if not settings.internal_jwt_secret:
        return "dev"
    if cred is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "missing bearer token")
    try:
        payload = jwt.decode(
            cred.credentials, settings.internal_jwt_secret, algorithms=["HS256"]
        )
    except jwt.PyJWTError as e:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, f"invalid token: {e}")
    sub = payload.get("sub")
    if not sub:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "token has no subject")
    return sub
