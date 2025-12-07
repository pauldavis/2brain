from __future__ import annotations

from typing import Annotated, Any, Dict

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel

from app.config import get_settings

# Scheme defines how the client should send the token (Bearer header)
security = HTTPBearer()


class User(BaseModel):
    email: str
    name: str | None = None


def get_current_user(
    token: Annotated[HTTPAuthorizationCredentials, Depends(security)],
) -> User:
    """
    Validates the JWT token sent in the Authorization header.
    Returns the user info if valid, otherwise raises 401.
    """
    settings = get_settings()

    # 1. Check for API Key (for scripts/cron)
    # This allows automation tools to bypass JWT checks if they possess the secret key.
    if settings.admin_api_key and token.credentials == settings.admin_api_key:
        return User(email="admin@system", name="System Admin")

    # Fail secure if no secret is configured
    if not settings.auth_secret:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Server authentication configuration is missing (AUTH_SECRET).",
        )

    try:
        # Decode and verify the token signature
        payload = jwt.decode(
            token.credentials,
            settings.auth_secret,
            algorithms=["HS256"],
            audience="2brain-api",
            issuer="2brain-viewer",
        )

        email = payload.get("sub")
        if not email:
            raise jwt.InvalidTokenError("Token payload missing 'sub' (email).")

        # Defense in depth: Check allowlist again on backend
        if settings.allowed_users and email not in settings.allowed_users:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="User email is not in the allowlist.",
            )

        return User(email=email, name=payload.get("name"))

    except jwt.ExpiredSignatureError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token has expired.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    except jwt.PyJWTError as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Invalid authentication credentials: {str(e)}",
            headers={"WWW-Authenticate": "Bearer"},
        )
