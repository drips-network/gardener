"""
Configuration management using Pydantic Settings
"""

from typing import Optional

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings

# Python 3.9+ stdlib import with a consistent alias to avoid mypy redefinition issues
try:  # Python 3.9+ stdlib
    from importlib.metadata import PackageNotFoundError as _PkgNotFound, version as _pkg_version
except Exception:  # pragma: no cover - very old envs
    _pkg_version = None

    class _PkgNotFound(Exception):
        pass


# Public alias used in the code below
PackageNotFoundError = _PkgNotFound


class WorkerConfig(BaseSettings):
    """
    Configuration settings for the Celery worker

    Controls resource limits and timeouts for background analysis jobs
    """

    MAX_ANALYSIS_DURATION: int = 3600  # 1 hour
    MAX_REPO_SIZE_MB: int = 500
    CLONE_TIMEOUT: int = 300  # 5 minutes
    SUBPROCESS_TIMEOUT: int = 3600  # 1 hour for subprocess execution


class APIConfig(BaseSettings):
    """
    Configuration settings for the FastAPI server

    Controls API behavior, rate limiting, and network configuration
    """

    RATE_LIMIT_PER_MINUTE: int = 60
    API_HOST: str = "0.0.0.0"
    API_PORT: int = 8000
    MAX_REQUEST_SIZE: int = Field(50_000_000, env="MAX_REQUEST_SIZE")  # 50MB
    ALLOWED_HOSTS_RAW: str = Field("*", env="ALLOWED_HOSTS")
    RUNNING_JOB_STALE_SECONDS: int = Field(900, env="RUNNING_JOB_STALE_SECONDS")  # Mark RUNNING jobs stale after 15m

    @property
    def ALLOWED_HOSTS(self):
        """
        Parse comma-separated hosts into list

        Returns:
            List of allowed hosts, with '*' meaning all hosts
        """
        if self.ALLOWED_HOSTS_RAW == "*":
            return ["*"]
        elif self.ALLOWED_HOSTS_RAW == "":
            return []  # Empty string means no external hosts
        return [h.strip() for h in self.ALLOWED_HOSTS_RAW.split(",") if h.strip()]


class DatabaseConfig(BaseSettings):
    """
    Database configuration for PostgreSQL connections

    Supports both Railway cloud deployment and local development environments
    """

    # Railway provides DATABASE_URL directly, or build from components
    DATABASE_URL: Optional[str] = Field(None, env="DATABASE_URL")

    # Individual components for local development
    POSTGRES_USER: str = Field("gardener", env="POSTGRES_USER")
    POSTGRES_PASSWORD: str = Field("gardener_dev", env="POSTGRES_PASSWORD")
    POSTGRES_DB: str = Field("gardener_db", env="POSTGRES_DB")
    POSTGRES_HOST: str = Field("postgres", env="POSTGRES_HOST")
    POSTGRES_PORT: int = Field(5432, env="POSTGRES_PORT")

    # Railway-specific env vars (optional)
    PGDATABASE: Optional[str] = Field(None, env="PGDATABASE")
    PGHOST: Optional[str] = Field(None, env="PGHOST")
    PGPASSWORD: Optional[str] = Field(None, env="PGPASSWORD")
    PGPORT: Optional[int] = Field(None, env="PGPORT")
    PGUSER: Optional[str] = Field(None, env="PGUSER")

    model_config = {"env_file": ".env", "secrets_dir": "/run/secrets"}


def _build_database_url(db):
    """
    Build DATABASE_URL from Railway PG* vars or local components

    Args:
        db (DatabaseConfig): Database configuration section

    Returns:
        str: Fully constructed database URL
    """
    if db.DATABASE_URL:
        return db.DATABASE_URL
    if db.PGHOST and db.PGUSER:
        password = db.PGPASSWORD or ""
        port = db.PGPORT or 5432
        database = db.PGDATABASE or "railway"
        return f"postgresql://{db.PGUSER}:{password}@{db.PGHOST}:{port}/{database}"
    return (
        f"postgresql://{db.POSTGRES_USER}:{db.POSTGRES_PASSWORD}@"
        f"{db.POSTGRES_HOST}:{db.POSTGRES_PORT}/{db.POSTGRES_DB}"
    )


class RedisConfig(BaseSettings):
    """
    Redis configuration for Celery broker and cache

    Manages Redis connections for job queuing and caching
    """

    # Railway provides REDIS_URL directly in production
    REDIS_URL: str = Field("redis://redis:6379/0", env="REDIS_URL")

    # Individual components for local development (optional)
    REDIS_HOST: str = Field("redis", env="REDIS_HOST")
    REDIS_PORT: int = Field(6379, env="REDIS_PORT")

    model_config = {"env_file": ".env"}


class SecurityConfig(BaseSettings):
    """
    Security-related configuration

    Manages HMAC authentication secrets and validation parameters
    """

    HMAC_SHARED_SECRET: str = Field(..., env="HMAC_SHARED_SECRET")  # Store as str
    HMAC_HASH_NAME: str = Field("sha256", env="HMAC_HASH_NAME")  # Correct hash name
    TOKEN_EXPIRY_SECONDS: int = Field(300, env="TOKEN_EXPIRY_SECONDS")

    model_config = {"env_file": ".env", "secrets_dir": "/run/secrets"}

    @field_validator("HMAC_SHARED_SECRET")
    @classmethod
    def validate_secret_strength(cls, v):
        """
        Validate that the HMAC shared secret meets minimum strength requirements

        Args:
            v (str): The secret value to validate

        Returns:
            The validated secret value

        Raises:
            ValueError: If secret is shorter than 32 characters
        """
        if len(v) < 32:
            raise ValueError("HMAC_SHARED_SECRET must be at least 32 characters")
        return v


class Settings(BaseSettings):
    """
    Main settings combining all configuration sections

    Aggregates all subsystem configurations and handles environment-specific setup
    """

    # Service identification
    SERVICE_NAME: str = "gardener-service"
    # Default; will be overridden in __init__ if package metadata is present
    SERVICE_VERSION: str = "0.1.0"

    # Sub-configurations
    worker: WorkerConfig = WorkerConfig()
    api: APIConfig = APIConfig()
    database: DatabaseConfig = DatabaseConfig()
    redis: RedisConfig = RedisConfig()
    security: SecurityConfig = SecurityConfig()

    # Environment
    ENVIRONMENT: str = "development"
    DEBUG: bool = True

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}

    def __init__(self, **kwargs):
        """
        Initialize settings with environment-specific database URL construction

        Args:
            **kwargs (dict): Additional configuration parameters
        """
        super().__init__(**kwargs)
        self.database.DATABASE_URL = _build_database_url(self.database)
        # Try to derive version from installed package metadata; fail gracefully
        try:
            if _pkg_version:
                self.SERVICE_VERSION = _pkg_version("gardener")
        except PackageNotFoundError:
            # Keep default '0.0.0' if not installed as a package
            pass
        # Apply basic production guardrails
        self._validate_production_safety()

    def _validate_production_safety(self):
        """Fail fast on unsafe production configuration

        Raises ValueError when running with ENVIRONMENT == 'production' if:
        - DEBUG is true, or
        - ALLOWED_HOSTS allows all ('*')

        HMAC secret length is validated separately; no content heuristics are applied
        """
        if str(self.ENVIRONMENT).lower() != "production":
            return

        # 1) DEBUG must be false in production
        if self.DEBUG:
            raise ValueError("DEBUG must be false in production")

        # 2) Do not allow wildcard hosts in production
        if self.api.ALLOWED_HOSTS == ["*"]:
            raise ValueError("ALLOWED_HOSTS must not be '*' in production")


# Global settings instance
settings = Settings()
