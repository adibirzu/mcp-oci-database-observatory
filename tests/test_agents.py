"""Tests for agent system."""

import pytest
from unittest.mock import MagicMock, AsyncMock


def test_coordinator_agent():
    """Test coordinator agent."""
    from src.agents.coordinator import CoordinatorAgent

    coordinator = CoordinatorAgent()

    assert coordinator.name == "coordinator"
    assert coordinator.otel_service_name == "oci-obs-coordinator"


@pytest.mark.asyncio
async def test_intent_classifier():
    """Test intent classification."""
    from src.agents.coordinator.intent import IntentClassifier
    from src.core.types import DatabaseType

    classifier = IntentClassifier()

    # Oracle intents
    intent = await classifier.classify("check Oracle database health")
    assert intent.database_type == DatabaseType.ORACLE

    # MySQL intents
    intent = await classifier.classify("analyze MySQL performance")
    assert intent.database_type == DatabaseType.MYSQL

    # PostgreSQL intents
    intent = await classifier.classify("PostgreSQL slow queries")
    assert intent.database_type == DatabaseType.POSTGRES

    # Multi-database
    intent = await classifier.classify("compare Oracle and MySQL databases")
    assert intent.database_type == "multi"


def test_database_agent_base_properties():
    """Test DatabaseAgent base class properties."""
    from src.agents.database.base import DatabaseAgent
    from abc import abstractmethod
    import inspect

    # Verify DatabaseAgent is abstract
    assert hasattr(DatabaseAgent, '__abstractmethods__')

    # Check that key abstract methods exist
    assert hasattr(DatabaseAgent, 'database_type')
    assert hasattr(DatabaseAgent, '_check_health')
    assert hasattr(DatabaseAgent, '_analyze_performance')


def test_agent_capabilities_enum():
    """Test capability enum values."""
    from src.agents.base.capabilities import (
        Capability,
        CapabilityCategory,
        ORACLE_CAPABILITIES,
        MYSQL_CAPABILITIES,
        POSTGRES_CAPABILITIES,
    )

    # Test capability enum
    assert Capability.PERFORMANCE_ANALYSIS.value == "performance_analysis"
    assert Capability.SQL_EXECUTION.value == "sql_execution"
    assert Capability.TROUBLESHOOTING.value == "troubleshooting"

    # Test category enum
    assert CapabilityCategory.DIAGNOSTIC.value == "diagnostic"
    assert CapabilityCategory.ANALYTICAL.value == "analytical"

    # Test Oracle capabilities exist
    assert len(ORACLE_CAPABILITIES) > 0
    assert any(c.id == "awr_analysis" for c in ORACLE_CAPABILITIES)

    # Test MySQL capabilities exist
    assert len(MYSQL_CAPABILITIES) > 0
    assert any(c.id == "perf_schema" for c in MYSQL_CAPABILITIES)

    # Test Postgres capabilities exist
    assert len(POSTGRES_CAPABILITIES) > 0
    assert any(c.id == "pg_stat_analysis" for c in POSTGRES_CAPABILITIES)


def test_get_capabilities_for_database():
    """Test getting capabilities for specific database types."""
    from src.agents.base.capabilities import get_capabilities_for_database
    from src.core.types import DatabaseType

    oracle_caps = get_capabilities_for_database(DatabaseType.ORACLE)
    assert len(oracle_caps) > 0
    assert oracle_caps[0].id == "awr_analysis"

    mysql_caps = get_capabilities_for_database(DatabaseType.MYSQL)
    assert len(mysql_caps) > 0

    postgres_caps = get_capabilities_for_database(DatabaseType.POSTGRES)
    assert len(postgres_caps) > 0


def test_agent_router():
    """Test agent router."""
    from src.agents.coordinator.router import AgentRouter

    router = AgentRouter()

    # Initially empty
    assert router.list_agents() == []


@pytest.mark.asyncio
async def test_response_aggregator():
    """Test response aggregator."""
    from src.agents.coordinator.aggregator import ResponseAggregator
    from src.core.types import AgentResult, DatabaseType

    aggregator = ResponseAggregator()

    # Test with empty results - aggregate succeeds but with 0 agents
    result = await aggregator.aggregate([])
    # With 0 results, success_count == len(results) is True (0 == 0)
    assert result["success"] is True
    assert result["metrics"]["agents_invoked"] == 0
    assert result["summary"] == "No issues detected"
