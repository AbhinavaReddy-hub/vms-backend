"""All configuration comes from environment variables (.env file).
Nothing secret is ever hardcoded here."""
import os
from functools import lru_cache

from dotenv import load_dotenv

# Without this, `.env` is inert when running via `uvicorn app.main:app` directly
# (only docker-compose substitutes it, and only for the vars it references).
load_dotenv()


class Settings:
    APP_NAME: str = os.getenv("APP_NAME", "Visitor Management System")
    COMPANY_NAME: str = os.getenv("COMPANY_NAME", "404")
    ENV: str = os.getenv("ENV", "dev")

    # SQLite by default so it runs with zero setup.
    # For production set DATABASE_URL to a Postgres URL - nothing else changes.
    DATABASE_URL: str = os.getenv("DATABASE_URL", "sqlite:///./vms.db")

    JWT_SECRET: str = os.getenv("JWT_SECRET", "change-me-in-production")
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_MINUTES: int = int(os.getenv("ACCESS_TOKEN_MINUTES", "15"))
    REFRESH_TOKEN_DAYS: int = int(os.getenv("REFRESH_TOKEN_DAYS", "7"))

    # Face service - internal network only, never exposed publicly
    FACE_SERVICE_URL: str = os.getenv("FACE_SERVICE_URL", "http://localhost:8001")
    FACE_MATCH_THRESHOLD: float = float(os.getenv("FACE_MATCH_THRESHOLD", "0.70"))

    # This must be the visitor app's origin (vms-visitor-app, default Vite port
    # 5174) since /register/:token and /pass/:token are routes in that SPA -
    # not http://localhost:8000, which is this API and has no such routes.
    PUBLIC_BASE_URL: str = os.getenv("PUBLIC_BASE_URL", "http://localhost:5174")
    FRONTEND_ORIGIN: str = os.getenv("FRONTEND_ORIGIN", "http://localhost:5173")

    # Browser origins allowed to call this API. Both SPAs need to be listed -
    # the staff frontend AND the visitor app - and in production they are two
    # different hosts, so one FRONTEND_ORIGIN is not enough. Comma-separated;
    # never set this to "*" (allow_credentials=True makes "*" invalid anyway).
    CORS_ORIGINS: list = [
        o.strip()
        for o in os.getenv(
            "CORS_ORIGINS",
            "http://localhost:3000,http://localhost:5173,http://localhost:5174",
        ).split(",")
        if o.strip()
    ]

    # Outside services. Left empty in dev - the clients then just log instead of sending.
    SENDGRID_API_KEY: str = os.getenv("SENDGRID_API_KEY", "")
    FROM_EMAIL: str = os.getenv("FROM_EMAIL", "no-reply@vms.local")
    TWILIO_SID: str = os.getenv("TWILIO_SID", "")
    TWILIO_TOKEN: str = os.getenv("TWILIO_TOKEN", "")
    TWILIO_FROM: str = os.getenv("TWILIO_FROM", "")

    LOGIN_MAX_ATTEMPTS: int = 5
    LOGIN_LOCKOUT_MINUTES: int = 15
    OTP_LENGTH: int = 6
    OTP_EXPIRY_MINUTES: int = 5
    OTP_MAX_ATTEMPTS: int = 5
    APPROVAL_TIMEOUT_MINUTES: int = 3
    AUTO_CLOSE_HOUR: int = 21
    FACE_RETENTION_DAYS: int = 30


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
