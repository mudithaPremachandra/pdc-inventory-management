
import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    database_url: str
    jwt_secret: str
    jwt_expiry_minutes: int
    admin_username: str
    admin_password: str
    command_api_url: str
    query_api_url: str
    projector_poll_seconds: float


def load_settings() -> Settings:
    return Settings(
        database_url=os.getenv("DATABASE_URL", "postgresql://inventory:inventory@localhost:5432/inventory"),
        jwt_secret=os.getenv("JWT_SECRET", "change-me-to-a-long-random-string"),
        jwt_expiry_minutes=int(os.getenv("JWT_EXPIRY_MINUTES", "120")),
        admin_username=os.getenv("ADMIN_USERNAME", "admin"),
        admin_password=os.getenv("ADMIN_PASSWORD", "admin123"),
        command_api_url=os.getenv("COMMAND_API_URL", "http://localhost:8001"),
        query_api_url=os.getenv("QUERY_API_URL", "http://localhost:8002"),
        projector_poll_seconds=float(os.getenv("PROJECTOR_POLL_SECONDS", "2")),
    )


settings = load_settings()
