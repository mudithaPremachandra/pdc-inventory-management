# Owner: Sandun (Authentication and access management).
"""JWT access tokens.

The command-api issues a token at login; both APIs verify it with the same shared
secret, so the query-api never has to call the command-api to check who you are.
"""

from datetime import datetime, timedelta, timezone

import jwt

from inventory.config import settings

ALGORITHM = "HS256"


class InvalidToken(Exception):
    pass


def issue_token(username: str, role: str) -> str:
    now = datetime.now(timezone.utc)
    claims = {
        "sub": username,
        "role": role,
        "iat": now,
        "exp": now + timedelta(minutes=settings.jwt_expiry_minutes),
    }
    return jwt.encode(claims, settings.jwt_secret, algorithm=ALGORITHM)


def verify_token(token: str) -> dict:
    try:
        return jwt.decode(token, settings.jwt_secret, algorithms=[ALGORITHM])
    except jwt.ExpiredSignatureError as exc:
        raise InvalidToken("session expired, please log in again") from exc
    except jwt.InvalidTokenError as exc:
        raise InvalidToken("invalid token") from exc
