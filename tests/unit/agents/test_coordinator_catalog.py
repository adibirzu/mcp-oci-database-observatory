"""Tests for coordinator database catalog integration.

Tests the end-to-end flow of:
1. Intent classification -> skill detection
2. Database name resolution via catalog
3. Skill execution with resolved parameters
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from src.agents.coordinator.coordinator import (
    CoordinatorAgent,
    DBMGMT_SKILL_MAP,
    INTENT_SKILL_MAP,
)
from src.agents.coordinator.catalog import (
    DatabaseCatalog,
    DatabaseEntry,
    DatabaseSource,
    DatabaseType,
)
from src.agents.coordinator.skills import SkillType
from src.agents.base.context import AgentContext
from src.core.types import IntentType


@pytest.fixture
def coordinator():
    """Create a coordinator agent for testing."""
    return CoordinatorAgent()


@pytest.fixture
def mock_context():
    """Create a mock agent context."""
    ctx = MagicMock(spec=AgentContext)
    ctx.tool_executor = MagicMock()
    ctx.request_id = "test-request-123"
    return ctx


@pytest.fixture
def sample_db_entry():
    """Sample database entry from catalog."""
    return DatabaseEntry(
        id="production-catalog-id",
        name="PRODUCTION",
        source=DatabaseSource.SQLCL,
        database_type=DatabaseType.AUTONOMOUS,
        status="AVAILABLE",
        connection_name="PRODUCTION",
        managed_database_id="ocid1.manageddatabase.oc1..aaa",
        opsi_database_id="ocid1.opsidb.oc1..bbb",
        compartment_id="ocid1.compartment.oc1..ccc",
    )


class TestSkillDetection:
    """Test skill detection from intent and entities."""

    @pytest.mark.parametrize("analysis_type,expected_skill", [
        ("blocking_sessions", SkillType.BLOCKING_SESSIONS),
        ("long_operations", SkillType.LONG_OPERATIONS),
        ("parallelism_analysis", SkillType.PARALLELISM_ANALYSIS),
        ("full_table_scans", SkillType.FULL_TABLE_SCANS),
        ("sql_monitor", SkillType.SQL_MONITOR),
        ("awr_analysis", SkillType.AWR_ANALYSIS),
        ("sql_tuning", SkillType.SQL_TUNING),
        ("alert_analysis", SkillType.ALERT_ANALYSIS),
    ])
    def test_dbmgmt_skill_mapping(self, analysis_type, expected_skill):
        """Verify DB Management analysis types map to correct skills."""
        assert DBMGMT_SKILL_MAP.get(analysis_type) == expected_skill

    @pytest.mark.parametrize("intent,expected_skill", [
        (IntentType.MONITOR, SkillType.FLEET_HEALTH),
        (IntentType.DIAGNOSE, SkillType.PERFORMANCE_TROUBLESHOOT),
        (IntentType.OPTIMIZE, SkillType.COST_OPTIMIZATION),
        (IntentType.ANALYZE, SkillType.DATABASE_HEALTH),
    ])
    def test_intent_skill_mapping(self, intent, expected_skill):
        """Verify intent types map to correct OPSI skills."""
        assert INTENT_SKILL_MAP.get(intent) == expected_skill

    def test_dbmgmt_analysis_takes_priority(self, coordinator):
        """DB Management analysis should take priority over intent-based skills."""
        mock_intent = MagicMock()
        mock_intent.primary_intent = IntentType.DIAGNOSE

        # When dbmgmt_analysis is present, it should be used
        entities = {"dbmgmt_analysis": ["blocking_sessions"]}
        skill = coordinator._should_use_opsi_skill(mock_intent, entities)
        assert skill == SkillType.BLOCKING_SESSIONS

    def test_opsi_entities_trigger_skill(self, coordinator):
        """OPSI-specific entities should trigger OPSI skill usage."""
        mock_intent = MagicMock()
        mock_intent.primary_intent = IntentType.MONITOR

        entities = {"opsi_analysis": ["fleet_summary"]}
        skill = coordinator._should_use_opsi_skill(mock_intent, entities)
        assert skill == SkillType.FLEET_HEALTH


class TestDatabaseResolution:
    """Test database name resolution via catalog."""

    @pytest.mark.asyncio
    async def test_resolve_database_params_found(
        self, coordinator, mock_context, sample_db_entry
    ):
        """When database is found in catalog, params should be populated."""
        # Setup mock catalog
        mock_catalog = MagicMock(spec=DatabaseCatalog)
        mock_catalog.search = AsyncMock(return_value=[sample_db_entry])
        mock_catalog._executor = None

        with patch.object(
            coordinator, '_ensure_catalog_initialized',
            return_value=mock_catalog
        ):
            entities = {"databases": ["PRODUCTION"]}
            params = await coordinator._resolve_database_params(
                entities, mock_context
            )

            assert params["connection_name"] == "PRODUCTION"
            assert params["managed_database_id"] == "ocid1.manageddatabase.oc1..aaa"
            assert params["database_id"] == "ocid1.opsidb.oc1..bbb"
            assert params["compartment_id"] == "ocid1.compartment.oc1..ccc"
            assert "_database_entry" in params

    @pytest.mark.asyncio
    async def test_resolve_database_params_not_found(
        self, coordinator, mock_context
    ):
        """When database is not found, connection_name should be set as fallback."""
        mock_catalog = MagicMock(spec=DatabaseCatalog)
        mock_catalog.search = AsyncMock(return_value=[])
        mock_catalog._executor = None

        with patch.object(
            coordinator, '_ensure_catalog_initialized',
            return_value=mock_catalog
        ):
            entities = {"databases": ["UNKNOWN_DB"]}
            params = await coordinator._resolve_database_params(
                entities, mock_context
            )

            # Should use database name as fallback connection_name
            assert params["connection_name"] == "UNKNOWN_DB"
            assert "managed_database_id" not in params

    @pytest.mark.asyncio
    async def test_resolve_database_params_no_databases(
        self, coordinator, mock_context
    ):
        """When no databases in entities, should return entities unchanged."""
        mock_catalog = MagicMock(spec=DatabaseCatalog)
        mock_catalog._executor = None

        with patch.object(
            coordinator, '_ensure_catalog_initialized',
            return_value=mock_catalog
        ):
            entities = {"metrics": ["cpu", "memory"]}
            params = await coordinator._resolve_database_params(
                entities, mock_context
            )

            # Should return original entities without modification
            assert params == {"metrics": ["cpu", "memory"]}
            mock_catalog.search.assert_not_called()


class TestCatalogInitialization:
    """Test catalog initialization flow."""

    @pytest.mark.asyncio
    async def test_catalog_lazy_initialization(self, coordinator, mock_context):
        """Catalog should be lazily initialized on first use."""
        assert coordinator._catalog is None
        assert coordinator._catalog_initialized is False

        # Mock get_catalog to return a mock catalog
        mock_catalog = MagicMock(spec=DatabaseCatalog)
        mock_catalog.refresh = AsyncMock()
        mock_catalog.get_stats.return_value = MagicMock(total_databases=5)
        mock_catalog._executor = None

        with patch(
            'src.agents.coordinator.coordinator.get_catalog',
            return_value=mock_catalog
        ):
            catalog = await coordinator._ensure_catalog_initialized(mock_context)

            assert catalog is mock_catalog
            assert coordinator._catalog is mock_catalog
            assert coordinator._catalog_initialized is True
            mock_catalog.refresh.assert_called_once()

    @pytest.mark.asyncio
    async def test_catalog_not_reinitialized(self, coordinator, mock_context):
        """Catalog should not be reinitialized on subsequent calls."""
        mock_catalog = MagicMock(spec=DatabaseCatalog)
        mock_catalog._executor = mock_context.tool_executor

        coordinator._catalog = mock_catalog
        coordinator._catalog_initialized = True

        catalog = await coordinator._ensure_catalog_initialized(mock_context)

        assert catalog is mock_catalog
        mock_catalog.refresh.assert_not_called()


class TestIntentToSkillFlow:
    """Test the full intent -> skill flow."""

    @pytest.mark.asyncio
    async def test_blocking_sessions_query(self, coordinator):
        """Verify blocking session query routes to BLOCKING_SESSIONS skill."""
        query = "show me blocking sessions for PRODUCTION"
        intent = await coordinator.classifier.classify(query)

        assert "blocking_sessions" in intent.entities.get("dbmgmt_analysis", [])

        skill = coordinator._should_use_opsi_skill(intent, intent.entities)
        assert skill == SkillType.BLOCKING_SESSIONS

    @pytest.mark.asyncio
    async def test_long_operations_query(self, coordinator):
        """Verify long operations query routes to LONG_OPERATIONS skill."""
        query = "check long operations in PRODUCTION database"
        intent = await coordinator.classifier.classify(query)

        assert "long_operations" in intent.entities.get("dbmgmt_analysis", [])

        skill = coordinator._should_use_opsi_skill(intent, intent.entities)
        assert skill == SkillType.LONG_OPERATIONS

    @pytest.mark.asyncio
    async def test_parallelism_analysis_query(self, coordinator):
        """Verify parallel execution query routes to PARALLELISM_ANALYSIS skill."""
        query = "analyze parallel query performance for FINANCE database"
        intent = await coordinator.classifier.classify(query)

        assert "parallelism_analysis" in intent.entities.get("dbmgmt_analysis", [])

        skill = coordinator._should_use_opsi_skill(intent, intent.entities)
        assert skill == SkillType.PARALLELISM_ANALYSIS

    @pytest.mark.asyncio
    async def test_full_table_scan_query(self, coordinator):
        """Verify FTS detection query routes to FULL_TABLE_SCANS skill."""
        query = "identify full table scans on ORDERS database"
        intent = await coordinator.classifier.classify(query)

        assert "full_table_scans" in intent.entities.get("dbmgmt_analysis", [])

        skill = coordinator._should_use_opsi_skill(intent, intent.entities)
        assert skill == SkillType.FULL_TABLE_SCANS

    @pytest.mark.asyncio
    async def test_sql_monitor_query(self, coordinator):
        """Verify SQL monitor query routes to SQL_MONITOR skill."""
        query = "show sql monitor report for active sql on PRODUCTION"
        intent = await coordinator.classifier.classify(query)

        assert "sql_monitor" in intent.entities.get("dbmgmt_analysis", [])

        skill = coordinator._should_use_opsi_skill(intent, intent.entities)
        assert skill == SkillType.SQL_MONITOR

    @pytest.mark.asyncio
    async def test_awr_report_query(self, coordinator):
        """Verify AWR report query routes to AWR_ANALYSIS skill."""
        query = "generate awr report for FINANCE database"
        intent = await coordinator.classifier.classify(query)

        assert "awr_analysis" in intent.entities.get("dbmgmt_analysis", [])

        skill = coordinator._should_use_opsi_skill(intent, intent.entities)
        assert skill == SkillType.AWR_ANALYSIS


class TestCatalogManagement:
    """Test catalog management methods."""

    @pytest.mark.asyncio
    async def test_refresh_catalog(self, coordinator, mock_context):
        """Test catalog refresh method."""
        mock_catalog = MagicMock(spec=DatabaseCatalog)
        mock_stats = MagicMock(
            total_databases=10,
            by_source={"sqlcl": 5, "dbmgmt": 3, "opsi": 2},
            by_type={"ADB_S": 10},
            by_status={"AVAILABLE": 10},
            last_refresh="2025-01-08T10:00:00",
            cache_hits=100,
            cache_misses=5,
        )
        mock_catalog.refresh = AsyncMock(return_value=mock_stats)
        mock_catalog._executor = None

        with patch.object(
            coordinator, '_ensure_catalog_initialized',
            return_value=mock_catalog
        ):
            result = await coordinator.refresh_catalog(mock_context)

            assert result["total_databases"] == 10
            assert result["by_source"]["sqlcl"] == 5

    @pytest.mark.asyncio
    async def test_list_databases(self, coordinator, mock_context, sample_db_entry):
        """Test listing databases from catalog."""
        mock_catalog = MagicMock(spec=DatabaseCatalog)
        mock_catalog.search = AsyncMock(return_value=[sample_db_entry])
        mock_catalog._executor = None

        with patch.object(
            coordinator, '_ensure_catalog_initialized',
            return_value=mock_catalog
        ):
            result = await coordinator.list_databases(mock_context)

            assert len(result) == 1
            assert result[0]["name"] == "PRODUCTION"
            assert result[0]["source"] == "sqlcl"

    @pytest.mark.asyncio
    async def test_get_catalog_stats(self, coordinator, mock_context):
        """Test getting catalog statistics."""
        mock_catalog = MagicMock(spec=DatabaseCatalog)
        mock_catalog.get_stats.return_value = MagicMock(
            total_databases=15,
            by_source={"sqlcl": 10, "dbmgmt": 5},
            by_type={"ADB_S": 15},
            by_status={"AVAILABLE": 15},
            last_refresh="2025-01-08T10:00:00",
            cache_hits=50,
            cache_misses=2,
        )
        mock_catalog._executor = None

        with patch.object(
            coordinator, '_ensure_catalog_initialized',
            return_value=mock_catalog
        ):
            result = await coordinator.get_catalog_stats(mock_context)

            assert result["total_databases"] == 15
            assert result["cache_hits"] == 50
