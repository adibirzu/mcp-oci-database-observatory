"""Unified database catalog with multi-source discovery and caching.

This module provides a centralized catalog of databases from all sources:
- SQLcl connections (direct database access)
- OCI Database Management API (managed databases)
- OCI Operations Insights (OPSI) (database insights)

The catalog supports:
- Multi-tier caching with configurable TTLs
- Background refresh for proactive cache updates
- Auto-discovery for unknown components
- Unified search across all sources
"""

import asyncio
import json
import time
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any

from src.core import get_logger

logger = get_logger("agents.coordinator.catalog")


class DatabaseSource(str, Enum):
    """Source systems for database discovery."""

    SQLCL = "sqlcl"
    DBMGMT = "dbmgmt"
    OPSI = "opsi"


class DatabaseType(str, Enum):
    """Database types."""

    ORACLE = "oracle"
    AUTONOMOUS = "autonomous"
    MYSQL = "mysql"
    POSTGRESQL = "postgresql"
    UNKNOWN = "unknown"


@dataclass
class DatabaseEntry:
    """Unified database entry from any source."""

    id: str
    name: str
    source: DatabaseSource
    database_type: DatabaseType = DatabaseType.ORACLE
    compartment_id: str | None = None
    compartment_name: str | None = None
    status: str = "unknown"
    connection_name: str | None = None  # SQLcl connection name
    managed_database_id: str | None = None  # DB Management OCID
    opsi_database_id: str | None = None  # OPSI database ID
    deployment_type: str | None = None
    workload_type: str | None = None
    database_version: str | None = None
    last_seen: float = field(default_factory=time.time)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "id": self.id,
            "name": self.name,
            "source": self.source.value,
            "database_type": self.database_type.value,
            "compartment_id": self.compartment_id,
            "compartment_name": self.compartment_name,
            "status": self.status,
            "connection_name": self.connection_name,
            "managed_database_id": self.managed_database_id,
            "opsi_database_id": self.opsi_database_id,
            "deployment_type": self.deployment_type,
            "workload_type": self.workload_type,
            "database_version": self.database_version,
            "last_seen": self.last_seen,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "DatabaseEntry":
        """Create from dictionary."""
        return cls(
            id=data["id"],
            name=data["name"],
            source=DatabaseSource(data.get("source", "sqlcl")),
            database_type=DatabaseType(data.get("database_type", "oracle")),
            compartment_id=data.get("compartment_id"),
            compartment_name=data.get("compartment_name"),
            status=data.get("status", "unknown"),
            connection_name=data.get("connection_name"),
            managed_database_id=data.get("managed_database_id"),
            opsi_database_id=data.get("opsi_database_id"),
            deployment_type=data.get("deployment_type"),
            workload_type=data.get("workload_type"),
            database_version=data.get("database_version"),
            last_seen=data.get("last_seen", time.time()),
            metadata=data.get("metadata", {}),
        )


@dataclass
class CatalogStats:
    """Statistics about the catalog."""

    total_databases: int = 0
    by_source: dict[str, int] = field(default_factory=dict)
    by_type: dict[str, int] = field(default_factory=dict)
    by_status: dict[str, int] = field(default_factory=dict)
    last_refresh: float | None = None
    refresh_duration_ms: float | None = None
    cache_hits: int = 0
    cache_misses: int = 0


class DatabaseCatalog:
    """Unified catalog of databases from all sources.

    Provides:
    - Centralized database discovery from SQLcl, DB Management, OPSI
    - Multi-tier caching with configurable TTLs
    - Background refresh for proactive updates
    - Auto-discovery for unknown components
    """

    # Cache TTLs in seconds
    TTL_SQLCL = 300  # 5 minutes - connections can change
    TTL_DBMGMT = 600  # 10 minutes - managed DBs are stable
    TTL_OPSI = 600  # 10 minutes - OPSI insights are stable

    # Cache file location
    CACHE_DIR = Path.home() / ".mcp-oci" / "cache"
    CACHE_FILE = "database_catalog.json"

    def __init__(
        self,
        tool_executor: Any | None = None,
        cache_ttl: int = 600,
        auto_refresh: bool = True,
    ):
        """Initialize the catalog.

        Args:
            tool_executor: MCP tool executor for calling discovery tools
            cache_ttl: Default cache TTL in seconds
            auto_refresh: Enable background refresh
        """
        self._executor = tool_executor
        self._cache_ttl = cache_ttl
        self._auto_refresh = auto_refresh

        # In-memory cache
        self._databases: dict[str, DatabaseEntry] = {}
        self._last_refresh: dict[DatabaseSource, float] = {}
        self._stats = CatalogStats()

        # Background task
        self._refresh_task: asyncio.Task | None = None
        self._lock = asyncio.Lock()

        # Load from disk cache
        self._load_cache()

    def _load_cache(self) -> None:
        """Load catalog from disk cache."""
        cache_path = self.CACHE_DIR / self.CACHE_FILE
        if cache_path.exists():
            try:
                with open(cache_path) as f:
                    data = json.load(f)

                self._databases = {
                    k: DatabaseEntry.from_dict(v)
                    for k, v in data.get("databases", {}).items()
                }
                self._last_refresh = {
                    DatabaseSource(k): v
                    for k, v in data.get("last_refresh", {}).items()
                }
                self._stats.cache_hits = data.get("stats", {}).get("cache_hits", 0)
                self._stats.cache_misses = data.get("stats", {}).get("cache_misses", 0)

                logger.info(
                    "Loaded catalog from cache",
                    databases=len(self._databases),
                    sources=list(self._last_refresh.keys()),
                )
            except Exception as e:
                logger.warning(f"Failed to load catalog cache: {e}")

    def _save_cache(self) -> None:
        """Save catalog to disk cache."""
        self.CACHE_DIR.mkdir(parents=True, exist_ok=True)
        cache_path = self.CACHE_DIR / self.CACHE_FILE

        try:
            data = {
                "databases": {k: v.to_dict() for k, v in self._databases.items()},
                "last_refresh": {k.value: v for k, v in self._last_refresh.items()},
                "stats": {
                    "cache_hits": self._stats.cache_hits,
                    "cache_misses": self._stats.cache_misses,
                },
                "updated_at": datetime.utcnow().isoformat(),
            }
            with open(cache_path, "w") as f:
                json.dump(data, f, indent=2)

            logger.debug("Saved catalog cache", databases=len(self._databases))
        except Exception as e:
            logger.warning(f"Failed to save catalog cache: {e}")

    def _is_cache_valid(self, source: DatabaseSource) -> bool:
        """Check if cache for a source is still valid."""
        last_refresh = self._last_refresh.get(source)
        if last_refresh is None:
            return False

        ttl = {
            DatabaseSource.SQLCL: self.TTL_SQLCL,
            DatabaseSource.DBMGMT: self.TTL_DBMGMT,
            DatabaseSource.OPSI: self.TTL_OPSI,
        }.get(source, self._cache_ttl)

        return (time.time() - last_refresh) < ttl

    async def _discover_sqlcl(self) -> list[DatabaseEntry]:
        """Discover databases from SQLcl connections."""
        if not self._executor:
            logger.warning("No executor configured for SQLcl discovery")
            return []

        try:
            result = await self._executor.execute(
                server="sqlcl",
                tool="oci_database_list_connections",
                arguments={},
            )

            if not result.success:
                logger.warning(f"SQLcl discovery failed: {result.error}")
                return []

            connections = result.data.get("connections", [])
            entries = []

            for conn in connections:
                conn_name = conn.get("name", "")
                entry = DatabaseEntry(
                    id=f"sqlcl:{conn_name}",
                    name=conn_name,
                    source=DatabaseSource.SQLCL,
                    database_type=DatabaseType.ORACLE,
                    status=conn.get("status", "unknown"),
                    connection_name=conn_name,
                    metadata=conn,
                )
                entries.append(entry)

            logger.info("Discovered SQLcl connections", count=len(entries))
            return entries

        except Exception as e:
            logger.error(f"SQLcl discovery error: {e}")
            return []

    async def _discover_dbmgmt(
        self,
        compartment_id: str | None = None,
        profile: str = "PRODUCTION",
    ) -> list[DatabaseEntry]:
        """Discover databases from OCI Database Management API."""
        if not self._executor:
            logger.warning("No executor configured for DB Management discovery")
            return []

        try:
            result = await self._executor.execute(
                server="oci-dbmgmt",
                tool="oci_dbmgmt_list_databases",
                arguments={
                    "compartment_id": compartment_id,
                    "profile": profile,
                    "limit": 200,
                },
            )

            if not result.success:
                logger.warning(f"DB Management discovery failed: {result.error}")
                return []

            # Parse JSON response
            data = result.data
            if isinstance(data, str):
                data = json.loads(data)

            databases = data.get("databases", [])
            entries = []

            for db in databases:
                db_id = db.get("id", "")
                db_type = DatabaseType.AUTONOMOUS if "autonomous" in db.get("database_type", "").lower() else DatabaseType.ORACLE

                entry = DatabaseEntry(
                    id=f"dbmgmt:{db_id}",
                    name=db.get("name", ""),
                    source=DatabaseSource.DBMGMT,
                    database_type=db_type,
                    compartment_id=db.get("compartment_id"),
                    status=db.get("lifecycle_state", "unknown").lower(),
                    managed_database_id=db_id,
                    deployment_type=db.get("deployment_type"),
                    workload_type=db.get("workload_type"),
                    database_version=db.get("database_version"),
                    metadata=db,
                )
                entries.append(entry)

            logger.info("Discovered DB Management databases", count=len(entries))
            return entries

        except Exception as e:
            logger.error(f"DB Management discovery error: {e}")
            return []

    async def _discover_opsi(
        self,
        compartment_id: str | None = None,
        profile: str = "PRODUCTION",
    ) -> list[DatabaseEntry]:
        """Discover databases from OCI Operations Insights."""
        if not self._executor:
            logger.warning("No executor configured for OPSI discovery")
            return []

        try:
            result = await self._executor.execute(
                server="oci-opsi",
                tool="oci_opsi_search_databases",
                arguments={
                    "compartment_id": compartment_id,
                    "profile": profile,
                },
            )

            if not result.success:
                logger.warning(f"OPSI discovery failed: {result.error}")
                return []

            databases = result.data.get("databases", [])
            entries = []

            for db in databases:
                db_id = db.get("id", "")
                db_type_str = db.get("database_type", "").lower()
                if "autonomous" in db_type_str:
                    db_type = DatabaseType.AUTONOMOUS
                elif "mysql" in db_type_str:
                    db_type = DatabaseType.MYSQL
                else:
                    db_type = DatabaseType.ORACLE

                entry = DatabaseEntry(
                    id=f"opsi:{db_id}",
                    name=db.get("name", db.get("database_name", "")),
                    source=DatabaseSource.OPSI,
                    database_type=db_type,
                    compartment_id=db.get("compartment_id"),
                    compartment_name=db.get("compartment_name"),
                    status=db.get("status", "unknown").lower(),
                    opsi_database_id=db_id,
                    deployment_type=db.get("deployment_type"),
                    metadata=db,
                )
                entries.append(entry)

            logger.info("Discovered OPSI databases", count=len(entries))
            return entries

        except Exception as e:
            logger.error(f"OPSI discovery error: {e}")
            return []

    async def refresh(
        self,
        sources: list[DatabaseSource] | None = None,
        force: bool = False,
    ) -> CatalogStats:
        """Refresh the catalog from specified sources.

        Args:
            sources: Sources to refresh (all if None)
            force: Force refresh even if cache is valid

        Returns:
            Catalog statistics after refresh
        """
        async with self._lock:
            start_time = time.time()
            sources = sources or list(DatabaseSource)

            for source in sources:
                if not force and self._is_cache_valid(source):
                    logger.debug(f"Cache valid for {source.value}, skipping refresh")
                    self._stats.cache_hits += 1
                    continue

                self._stats.cache_misses += 1
                entries: list[DatabaseEntry] = []

                if source == DatabaseSource.SQLCL:
                    entries = await self._discover_sqlcl()
                elif source == DatabaseSource.DBMGMT:
                    entries = await self._discover_dbmgmt()
                elif source == DatabaseSource.OPSI:
                    entries = await self._discover_opsi()

                # Update catalog
                for entry in entries:
                    self._databases[entry.id] = entry

                self._last_refresh[source] = time.time()

            # Update stats
            self._update_stats()
            self._stats.last_refresh = time.time()
            self._stats.refresh_duration_ms = (time.time() - start_time) * 1000

            # Persist to disk
            self._save_cache()

            logger.info(
                "Catalog refreshed",
                databases=self._stats.total_databases,
                duration_ms=self._stats.refresh_duration_ms,
            )

            return self._stats

    def _update_stats(self) -> None:
        """Update catalog statistics."""
        self._stats.total_databases = len(self._databases)
        self._stats.by_source = {}
        self._stats.by_type = {}
        self._stats.by_status = {}

        for db in self._databases.values():
            # By source
            source_key = db.source.value
            self._stats.by_source[source_key] = self._stats.by_source.get(source_key, 0) + 1

            # By type
            type_key = db.database_type.value
            self._stats.by_type[type_key] = self._stats.by_type.get(type_key, 0) + 1

            # By status
            status_key = db.status
            self._stats.by_status[status_key] = self._stats.by_status.get(status_key, 0) + 1

    async def search(
        self,
        name: str | None = None,
        database_type: DatabaseType | None = None,
        source: DatabaseSource | None = None,
        status: str | None = None,
        compartment_id: str | None = None,
        refresh_if_empty: bool = True,
    ) -> list[DatabaseEntry]:
        """Search the catalog.

        Args:
            name: Database name (partial match, case-insensitive)
            database_type: Filter by database type
            source: Filter by source
            status: Filter by status
            compartment_id: Filter by compartment
            refresh_if_empty: Refresh catalog if no results found

        Returns:
            List of matching database entries
        """
        results = []
        name_lower = name.lower() if name else None

        for db in self._databases.values():
            # Name filter
            if name_lower and name_lower not in db.name.lower():
                continue

            # Type filter
            if database_type and db.database_type != database_type:
                continue

            # Source filter
            if source and db.source != source:
                continue

            # Status filter
            if status and db.status != status.lower():
                continue

            # Compartment filter
            if compartment_id and db.compartment_id != compartment_id:
                continue

            results.append(db)

        # If no results and refresh enabled, try discovering
        if not results and refresh_if_empty and name:
            logger.info(f"No results for '{name}', attempting auto-discovery")
            await self.discover_database(name)
            return await self.search(
                name=name,
                database_type=database_type,
                source=source,
                status=status,
                compartment_id=compartment_id,
                refresh_if_empty=False,  # Don't recurse
            )

        return results

    async def discover_database(self, name: str) -> DatabaseEntry | None:
        """Discover a specific database by name.

        This is used for auto-discovery when a user asks about
        a database that isn't in the catalog.

        Args:
            name: Database name to search for

        Returns:
            DatabaseEntry if found, None otherwise
        """
        logger.info(f"Auto-discovering database: {name}")

        # Try DB Management search first (most complete data)
        if self._executor:
            try:
                result = await self._executor.execute(
                    server="oci-dbmgmt",
                    tool="oci_dbmgmt_search_databases",
                    arguments={"name": name, "limit": 10},
                )

                if result.success:
                    data = result.data
                    if isinstance(data, str):
                        data = json.loads(data)

                    databases = data.get("databases", [])
                    for db in databases:
                        if name.lower() in db.get("name", "").lower():
                            entry = DatabaseEntry(
                                id=f"dbmgmt:{db.get('id', '')}",
                                name=db.get("name", ""),
                                source=DatabaseSource.DBMGMT,
                                database_type=DatabaseType.ORACLE,
                                compartment_id=db.get("compartment_id"),
                                status=db.get("lifecycle_state", "unknown").lower(),
                                managed_database_id=db.get("id"),
                                metadata=db,
                            )
                            self._databases[entry.id] = entry
                            self._save_cache()
                            logger.info(f"Discovered database via DB Management: {entry.name}")
                            return entry

            except Exception as e:
                logger.warning(f"DB Management search failed: {e}")

        # Try OPSI search
        if self._executor:
            try:
                result = await self._executor.execute(
                    server="oci-opsi",
                    tool="oci_opsi_search_databases",
                    arguments={"name": name},
                )

                if result.success:
                    databases = result.data.get("databases", [])
                    for db in databases:
                        db_name = db.get("name", db.get("database_name", ""))
                        if name.lower() in db_name.lower():
                            entry = DatabaseEntry(
                                id=f"opsi:{db.get('id', '')}",
                                name=db_name,
                                source=DatabaseSource.OPSI,
                                database_type=DatabaseType.ORACLE,
                                compartment_id=db.get("compartment_id"),
                                status=db.get("status", "unknown").lower(),
                                opsi_database_id=db.get("id"),
                                metadata=db,
                            )
                            self._databases[entry.id] = entry
                            self._save_cache()
                            logger.info(f"Discovered database via OPSI: {entry.name}")
                            return entry

            except Exception as e:
                logger.warning(f"OPSI search failed: {e}")

        logger.warning(f"Could not discover database: {name}")
        return None

    def get_by_name(self, name: str) -> DatabaseEntry | None:
        """Get database by exact name match.

        Args:
            name: Exact database name

        Returns:
            DatabaseEntry if found
        """
        for db in self._databases.values():
            if db.name.lower() == name.lower():
                return db
        return None

    def get_by_id(self, db_id: str) -> DatabaseEntry | None:
        """Get database by ID.

        Args:
            db_id: Database ID (with source prefix)

        Returns:
            DatabaseEntry if found
        """
        return self._databases.get(db_id)

    def get_connection_name(self, db_name: str) -> str | None:
        """Get SQLcl connection name for a database.

        First looks for a direct SQLcl connection, then tries to match
        by database name across all sources.

        Args:
            db_name: Database name

        Returns:
            Connection name if found
        """
        # Direct SQLcl connection
        for db in self._databases.values():
            if db.source == DatabaseSource.SQLCL:
                if db.name.lower() == db_name.lower():
                    return db.connection_name

        # Try to find matching database and return connection name
        for db in self._databases.values():
            if db.name.lower() == db_name.lower():
                # If this DB has a connection name, use it
                if db.connection_name:
                    return db.connection_name
                # Otherwise, the database name might be the connection name
                return db.name

        return None

    def get_managed_database_id(self, db_name: str) -> str | None:
        """Get managed database ID for a database name.

        Args:
            db_name: Database name

        Returns:
            Managed database OCID if found
        """
        for db in self._databases.values():
            if db.name.lower() == db_name.lower():
                if db.managed_database_id:
                    return db.managed_database_id
        return None

    def get_opsi_database_id(self, db_name: str) -> str | None:
        """Get OPSI database ID for a database name.

        Args:
            db_name: Database name

        Returns:
            OPSI database ID if found
        """
        for db in self._databases.values():
            if db.name.lower() == db_name.lower():
                if db.opsi_database_id:
                    return db.opsi_database_id
        return None

    def list_all(self) -> list[DatabaseEntry]:
        """List all databases in the catalog."""
        return list(self._databases.values())

    def get_stats(self) -> CatalogStats:
        """Get catalog statistics."""
        self._update_stats()
        return self._stats

    async def start_background_refresh(
        self,
        interval_seconds: int = 300,
    ) -> None:
        """Start background refresh task.

        Args:
            interval_seconds: Refresh interval in seconds
        """
        if self._refresh_task and not self._refresh_task.done():
            logger.warning("Background refresh already running")
            return

        async def _refresh_loop():
            while True:
                try:
                    await asyncio.sleep(interval_seconds)
                    await self.refresh()
                except asyncio.CancelledError:
                    break
                except Exception as e:
                    logger.error(f"Background refresh error: {e}")

        self._refresh_task = asyncio.create_task(_refresh_loop())
        logger.info(
            "Started background refresh",
            interval=interval_seconds,
        )

    async def stop_background_refresh(self) -> None:
        """Stop background refresh task."""
        if self._refresh_task:
            self._refresh_task.cancel()
            try:
                await self._refresh_task
            except asyncio.CancelledError:
                pass
            self._refresh_task = None
            logger.info("Stopped background refresh")


# Singleton instance
_catalog: DatabaseCatalog | None = None


def get_catalog(
    tool_executor: Any | None = None,
    force_new: bool = False,
) -> DatabaseCatalog:
    """Get or create the database catalog singleton.

    Args:
        tool_executor: MCP tool executor
        force_new: Force creation of new instance

    Returns:
        DatabaseCatalog instance
    """
    global _catalog
    if _catalog is None or force_new:
        _catalog = DatabaseCatalog(tool_executor=tool_executor)
    elif tool_executor and not _catalog._executor:
        _catalog._executor = tool_executor
    return _catalog
