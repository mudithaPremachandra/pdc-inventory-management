

"""Password hashing with bcrypt (salted, deliberately slow)."""

import bcrypt

from inventory.domain.errors import InvalidInput

MIN_PASSWORD_LENGTH = 6


def hash_password(plain: str) -> str:
    if len(plain or "") < MIN_PASSWORD_LENGTH:
        raise InvalidInput(f"password must be at least {MIN_PASSWORD_LENGTH} characters")
    return bcrypt.hashpw(plain.encode(), bcrypt.gensalt()).decode()


def verify_password(plain: str, hashed: str) -> bool:
    if not plain or not hashed:
        return False
    return bcrypt.checkpw(plain.encode(), hashed.encode())