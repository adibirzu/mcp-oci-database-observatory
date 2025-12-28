"""Tests for LLM router."""

import pytest


def test_task_classification():
    """Test query classification."""
    from src.llm.router.router import LLMRouter, TaskType

    router = LLMRouter()

    # SQL queries
    assert router.classify_task("SELECT * FROM users") == TaskType.SQL_GENERATION
    assert router.classify_task("Write a SQL query") == TaskType.SQL_GENERATION

    # Performance queries
    assert router.classify_task("CPU usage is high") == TaskType.PERFORMANCE
    assert router.classify_task("Optimize performance") == TaskType.PERFORMANCE

    # Troubleshooting
    assert router.classify_task("Error in database") == TaskType.TROUBLESHOOTING
    assert router.classify_task("Fix the slow query") == TaskType.TROUBLESHOOTING

    # Security
    assert router.classify_task("Security audit") == TaskType.SECURITY_AUDIT
    assert router.classify_task("Check permissions") == TaskType.SECURITY_AUDIT

    # Documentation
    # Note: "Document this function" matches CODE_ANALYSIS first because "function" is a code keyword
    assert router.classify_task("Document the API endpoints") == TaskType.DOCUMENTATION
    assert router.classify_task("Write a README file") == TaskType.DOCUMENTATION

    # General (default)
    assert router.classify_task("Hello world") == TaskType.GENERAL


def test_routing_rules():
    """Test routing rules configuration."""
    from src.llm.router.router import LLMRouter, TaskType

    router = LLMRouter()

    # Check SQL routes to OCA
    sql_rule = router.get_rule(TaskType.SQL_GENERATION)
    assert sql_rule.provider == "oracle_code_assist"
    assert sql_rule.temperature == 0.2

    # Check troubleshooting routes to Anthropic
    trouble_rule = router.get_rule(TaskType.TROUBLESHOOTING)
    assert trouble_rule.provider == "anthropic"

    # Check general rule
    general_rule = router.get_rule(TaskType.GENERAL)
    assert general_rule.provider == "anthropic"


def test_provider_registry():
    """Test provider registry."""
    from src.llm.providers.registry import ProviderRegistry

    registry = ProviderRegistry()

    # Check registered providers
    assert registry.get("anthropic") is not None
    assert registry.get("openai") is not None
    assert registry.get("oracle_code_assist") is not None
    assert registry.get("nonexistent") is None
