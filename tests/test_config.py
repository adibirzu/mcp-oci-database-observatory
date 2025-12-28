"""Tests for configuration module."""

import pytest
from pydantic import ValidationError


def test_settings_defaults():
    """Test that settings have sensible defaults."""
    from src.core.config import Settings

    # Create settings without .env file
    settings = Settings(_env_file=None)

    assert settings.port == 3001
    assert settings.log_level == "info"
    assert settings.otel_tracing_enabled is True
    assert settings.otel_service_name == "oci-obs-api"
    assert settings.llm_provider == "oracle_code_assist"


def test_settings_from_env(monkeypatch):
    """Test settings from environment variables."""
    from src.core.config import Settings

    monkeypatch.setenv("PORT", "8080")
    monkeypatch.setenv("LOG_LEVEL", "debug")
    monkeypatch.setenv("LLM_PROVIDER", "anthropic")

    settings = Settings(_env_file=None)

    assert settings.port == 8080
    assert settings.log_level == "debug"
    assert settings.llm_provider == "anthropic"


def test_settings_oci_profile(monkeypatch):
    """Test OCI profile settings."""
    from src.core.config import Settings

    monkeypatch.setenv("OCI_CLI_PROFILE", "PROD")

    settings = Settings(_env_file=None)

    assert settings.oci_profile == "PROD"
