"""Application settings validated via Pydantic Settings."""
from __future__ import annotations

from pathlib import Path

from pydantic import SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """All runtime configuration for the ingestion pipeline.

    Every field maps 1-to-1 to an environment variable (case-insensitive).
    Secrets are SecretStr so they are redacted in repr/logs.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",          # silently ignore unknown env vars
        case_sensitive=False,
    )

    # ── Pipeline database (CDM + manifest) ───────────────────────────────────
    pipeline_db_url: SecretStr = SecretStr(
        "postgresql://pipeline:pipeline@pipeline_db:5432/pipeline"
    )

    # ── CKAN open data portal ─────────────────────────────────────────────────
    ckan_url: str = "http://localhost:5000"
    ckan_api_key: SecretStr | None = None
    ckan_org_id: str = "nigeriaopendata"

    # ── Catalogue backend ─────────────────────────────────────────────────────
    # 'ckan'  : publish to a CKAN server (needs CKAN_API_KEY).
    # 'local' : publish to the built-in catalogue in the pipeline database and
    #           serve it from this app. No CKAN, Solr or Redis needed.
    catalog_backend: str = "ckan"

    # ── Prefect orchestration ─────────────────────────────────────────────────
    prefect_api_url: str = "http://prefect-server:4200/api"

    # ── Frontend Security ─────────────────────────────────────────────────────
    frontend_url: str = "http://localhost:3000"

    # ── Landing zone ──────────────────────────────────────────────────────────
    landing_root: Path = Path("data/raw")

    # ── Object Storage (S3 / Cloudflare R2) ────────────────────────────────────
    s3_endpoint_url: str | None = None
    s3_access_key_id: SecretStr | None = None
    s3_secret_access_key: SecretStr | None = None
    s3_bucket_name: str = "nigeria-open-data"
    s3_cdn_domain: str = "https://cdn.nigeriaopendata.gov.ng"

    # ── HTTP behaviour ────────────────────────────────────────────────────────
    request_timeout_seconds: int = 60
    request_max_retries: int = 3

    # ── Logging ───────────────────────────────────────────────────────────────
    log_level: str = "INFO"

    # ── Validators ───────────────────────────────────────────────────────────

    @field_validator("log_level")
    @classmethod
    def validate_log_level(cls, v: str) -> str:
        valid = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}
        upper = v.upper()
        if upper not in valid:
            raise ValueError(f"log_level must be one of {valid}, got '{v}'")
        return upper

    @field_validator("catalog_backend")
    @classmethod
    def validate_catalog_backend(cls, v: str) -> str:
        value = v.strip().lower()
        if value not in {"ckan", "local"}:
            raise ValueError(f"catalog_backend must be 'ckan' or 'local', got '{v}'")
        return value

    @field_validator("landing_root", mode="before")
    @classmethod
    def resolve_landing_root(cls, v) -> Path:
        return Path(v).resolve()

    @model_validator(mode="after")
    def ensure_landing_root_exists(self) -> Settings:
        """Create landing zone root directory on startup."""
        self.landing_root.mkdir(parents=True, exist_ok=True)
        return self

    # ── Convenience helpers ───────────────────────────────────────────────────

    def db_url(self) -> str:
        """Return the plain DB URL string (needed by SQLAlchemy)."""
        return self.pipeline_db_url.get_secret_value()

    def ckan_key(self) -> str | None:
        """Return the plain CKAN API key string, or None."""
        return self.ckan_api_key.get_secret_value() if self.ckan_api_key else None

    def s3_access_key(self) -> str | None:
        """Return the plain S3 Access Key ID, or None."""
        return self.s3_access_key_id.get_secret_value() if self.s3_access_key_id else None

    def s3_secret_key(self) -> str | None:
        """Return the plain S3 Secret Access Key, or None."""
        return self.s3_secret_access_key.get_secret_value() if self.s3_secret_access_key else None

    def __repr__(self) -> str:
        """Safe repr — secrets replaced with ***."""
        return (
            f"Settings("
            f"ckan_url={self.ckan_url!r}, "
            f"prefect_api_url={self.prefect_api_url!r}, "
            f"landing_root={self.landing_root!r}, "
            f"log_level={self.log_level!r}"
            f")"
        )


# ── Singleton ─────────────────────────────────────────────────────────────────
# Import this object everywhere instead of calling Settings() repeatedly.
# Pydantic reads env vars once on first import.
settings = Settings()
