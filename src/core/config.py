"""Application configuration using Pydantic Settings.

All secrets are sourced from .env.local (dev) or OCI Vault (prod).
See documentation placeholders: [Link to Secure Variable: VAR_NAME]
"""

import os
from functools import lru_cache
from pathlib import Path

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


def _find_env_file() -> str | None:
    """Find .env.local file from multiple candidate locations.

    Searches in order:
    1. OCI_ENV_FILE environment variable (explicit override)
    2. Current working directory
    3. Project root (relative to this file)
    4. Parent directories up to 3 levels
    5. Common development locations

    Returns:
        Path to .env.local if found, None otherwise
    """
    # 1. Explicit override via environment variable
    explicit_path = os.getenv("OCI_ENV_FILE")
    if explicit_path:
        expanded = Path(explicit_path).expanduser()
        if expanded.exists():
            return str(expanded)

    # 2. Current working directory
    cwd_env = Path.cwd() / ".env.local"
    if cwd_env.exists():
        return str(cwd_env)

    # 3. Project root (this file is at src/core/config.py)
    project_root = Path(__file__).parent.parent.parent / ".env.local"
    if project_root.exists():
        return str(project_root)

    # 4. Search parent directories (up to 3 levels from cwd)
    current = Path.cwd()
    for _ in range(3):
        parent_env = current.parent / ".env.local"
        if parent_env.exists():
            return str(parent_env)
        current = current.parent

    # 5. Common development locations
    common_paths = [
        Path.home() / "dev" / "oci-coordinator" / ".env.local",
        Path.home() / "dev" / "oci-database-observatory" / ".env.local",
        Path.home() / ".oci" / ".env.local",
    ]
    for path in common_paths:
        if path.exists():
            return str(path)

    return None


class Settings(BaseSettings):
    """Application settings with environment variable binding."""

    model_config = SettingsConfigDict(
        env_file=_find_env_file(),
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # Core
    port: int = Field(default=3001, description="API server port")
    log_level: str = Field(default="info", description="Logging level")
    environment: str = Field(default="development", alias="NODE_ENV")

    # OCI Configuration
    # [Link to Secure Variable: OCI_CONFIG_FILE]
    oci_config_file: Path = Field(
        default=Path.home() / ".oci" / "config",
        description="Path to OCI config file"
    )
    oci_profile: str = Field(
        default="DEFAULT",
        validation_alias=AliasChoices("OCI_CLI_PROFILE", "OCI_PROFILE"),
    )

    # OCI Compartment
    # [Link to Secure Variable: OCI_COMPARTMENT_ID]
    oci_compartment_id: str | None = Field(default=None)
    oci_region: str = Field(default="us-ashburn-1")

    # OCI APM / OpenTelemetry
    # OCI APM uses Zipkin format, not OTLP
    # [Link to Secure Variable: OCI_APM_DATA_UPLOAD_ENDPOINT]
    oci_apm_data_upload_endpoint: str | None = Field(
        default=None,
        description="OCI APM data upload endpoint base URL (without path)"
    )
    # Legacy endpoint field (kept for backwards compatibility)
    oci_apm_endpoint: str | None = Field(default=None)
    # [Link to Secure Variable: OCI_APM_PRIVATE_DATA_KEY]
    oci_apm_private_key: str | None = Field(default=None, alias="OCI_APM_PRIVATE_DATA_KEY")
    # [Link to Secure Variable: OCI_APM_PUBLIC_DATA_KEY]
    oci_apm_public_key: str | None = Field(default=None, alias="OCI_APM_PUBLIC_DATA_KEY")
    oci_apm_domain_id: str | None = Field(default=None)
    otel_tracing_enabled: bool = Field(default=True)
    otel_service_name: str = Field(default="oci-obs-api")

    # OCI Logging - OCIDs required for production
    # [Link to Secure Variable: OCI_LOG_GROUP_ID]
    oci_logging_enabled: bool = Field(default=True)
    oci_log_group_id: str | None = Field(default=None, description="OCI Log Group OCID")
    # [Link to Secure Variable: OCI_LOG_ID]
    oci_log_id: str | None = Field(default=None, description="OCI Custom Log OCID")
    oci_logging_region: str = Field(default="eu-frankfurt-1", description="OCI Logging region")
    oci_log_group_name: str = Field(default="oci-database-observatory")
    oci_log_name: str = Field(default="mcp-server-logs")

    # Oracle Code Assist
    oca_idcs_url: str | None = Field(default=None)
    oca_client_id: str | None = Field(default=None)
    oca_redirect_uri: str | None = Field(default=None)
    oca_api_url: str | None = Field(default=None)
    oca_default_model: str = Field(default="oci.generativeai.cohere.command-r-plus")
    oca_callback_host: str = Field(default="127.0.0.1")
    oca_callback_port: int = Field(default=48801)

    # LLM Configuration
    llm_model: str = Field(default="claude-sonnet-4-20250514")

    # LLM Providers
    llm_provider: str = Field(default="oracle_code_assist")
    # [Link to Secure Variable: ANTHROPIC_API_KEY]
    anthropic_api_key: str | None = Field(default=None)
    # [Link to Secure Variable: OPENAI_API_KEY]
    openai_api_key: str | None = Field(default=None)
    # [Link to Secure Variable: GEMINI_API_KEY]
    gemini_api_key: str | None = Field(default=None)

    # MCP Servers
    opsi_http_url: str = Field(default="http://localhost:8000/mcp")
    logan_http_url: str = Field(
        default="http://localhost:8001/mcp",
        description="Canonical OCI Log Analytics MCP endpoint",
    )
    oci_mcp_http_url: str = Field(default="http://localhost:8002/mcp")
    mysql_mcp_url: str = Field(default="http://localhost:8003/mcp")
    postgres_mcp_url: str = Field(default="http://localhost:8004/mcp")
    sqlcl_path: str = Field(default="/Applications/sqlcl/bin/sql")

    # Caching
    redis_url: str = Field(
        default="redis://localhost:6379",
        validation_alias=AliasChoices("REDIS_URL", "MCP_REDIS_URL"),
    )

    # Session
    # [Link to Secure Variable: SESSION_SECRET]
    session_secret: str = Field(default="change-this-to-random-secret")
    session_secure: bool = Field(default=False)

    # Slack Integration (optional)
    # [Link to Secure Variable: SLACK_BOT_TOKEN]
    slack_bot_token: str | None = Field(default=None)
    # [Link to Secure Variable: SLACK_APP_TOKEN]
    slack_app_token: str | None = Field(default=None)
    # [Link to Secure Variable: SLACK_SIGNING_SECRET]
    slack_signing_secret: str | None = Field(default=None)


@lru_cache
def get_settings() -> Settings:
    """Get cached settings instance."""
    return Settings()


# Convenience alias
settings = get_settings()
