"""OCI client management for MCP server.

Provides lazy-loaded, thread-safe OCI SDK clients for:
- Operations Insights (OPSI)
- Logging Analytics (Logan)
- SQLcl (via MCP stdio transport)

All blocking OCI calls are offloaded to threads for async compatibility.
"""

import asyncio
import os
from dataclasses import dataclass
from typing import Any, Dict, Optional

# OCI SDK - lazy import to handle missing dependency gracefully
_oci = None


def _get_oci():
    """Lazy load OCI SDK."""
    global _oci
    if _oci is None:
        try:
            import oci

            _oci = oci
        except ImportError:
            raise ImportError(
                "OCI SDK not installed. Install with: pip install oci"
            )
    return _oci


@dataclass
class OCIConfig:
    """OCI configuration from profile."""

    config: Dict[str, Any]
    profile: str
    region: str
    tenancy_id: str
    compartment_id: Optional[str] = None
    dbmgmt_compartment_id: Optional[str] = None
    opsi_compartment_id: Optional[str] = None


class OCIClientManager:
    """Manages OCI SDK clients with multi-tenancy support.

    Clients are created lazily and cached per profile/region.
    Thread-safe via asyncio locks.
    """

    def __init__(self):
        self._configs: Dict[str, OCIConfig] = {}
        self._opsi_clients: Dict[str, Any] = {}
        self._logan_clients: Dict[str, Any] = {}
        self._dbm_clients: Dict[str, Any] = {}
        self._lock = asyncio.Lock()

    def _load_config(self, profile: str = "DEFAULT") -> OCIConfig:
        """Load OCI config for a profile.

        Args:
            profile: OCI profile name

        Returns:
            OCIConfig instance with profile-specific compartments
        """
        oci = _get_oci()

        config_file = os.getenv("OCI_CONFIG_FILE", "~/.oci/config")
        config = oci.config.from_file(config_file, profile)

        # Get region from env or config
        region = os.getenv("OCI_REGION") or config.get("region")

        # Profile-specific environment variable lookup
        # Converts profile name to uppercase for env var lookup
        # e.g., "PRODUCTION" -> OCI_PRODUCTION_DBMGMT_COMPARTMENT_ID
        profile_upper = profile.upper().replace("-", "_")

        # Get profile-specific DB Management compartment
        dbmgmt_compartment_id = (
            os.getenv(f"OCI_{profile_upper}_DBMGMT_COMPARTMENT_ID") or
            os.getenv("OCI_DBMGMT_COMPARTMENT_ID")
        )

        # Get profile-specific OPSI compartment
        opsi_compartment_id = (
            os.getenv(f"OCI_{profile_upper}_OPSI_COMPARTMENT_ID") or
            os.getenv("OCI_OPSI_COMPARTMENT_ID")
        )

        # Get general compartment: profile-specific -> generic -> tenancy
        compartment_id = (
            os.getenv(f"OCI_{profile_upper}_COMPARTMENT_ID") or
            os.getenv("OCI_COMPARTMENT_ID") or
            config.get("tenancy")
        )

        return OCIConfig(
            config=config,
            profile=profile,
            region=region,
            tenancy_id=config.get("tenancy"),
            compartment_id=compartment_id,
            dbmgmt_compartment_id=dbmgmt_compartment_id or compartment_id,
            opsi_compartment_id=opsi_compartment_id or compartment_id,
        )

    async def get_config(self, profile: str = "DEFAULT") -> OCIConfig:
        """Get OCI config for profile.

        Args:
            profile: OCI profile name

        Returns:
            OCIConfig instance
        """
        async with self._lock:
            if profile not in self._configs:
                self._configs[profile] = await asyncio.to_thread(
                    self._load_config, profile
                )
            return self._configs[profile]

    def _create_opsi_client(self, config: OCIConfig) -> Any:
        """Create OPSI client (blocking, run in thread).

        Args:
            config: OCI configuration

        Returns:
            OperationsInsightsClient
        """
        oci = _get_oci()

        # Set timeout from env
        timeout = int(os.getenv("OPSI_CLIENT_TIMEOUT", "30"))

        client = oci.opsi.OperationsInsightsClient(
            config.config,
            retry_strategy=oci.retry.DEFAULT_RETRY_STRATEGY,
            timeout=timeout,
        )

        # Override region if needed
        if config.region:
            client.base_client.set_region(config.region)

        return client

    async def get_opsi_client(
        self, profile: str = "DEFAULT", region: Optional[str] = None
    ) -> Any:
        """Get OPSI client for profile/region.

        Args:
            profile: OCI profile name
            region: Optional region override

        Returns:
            OperationsInsightsClient
        """
        key = f"{profile}:{region or 'default'}"

        async with self._lock:
            if key not in self._opsi_clients:
                config = await self.get_config(profile)
                if region:
                    # Override region
                    config = OCIConfig(
                        config=config.config,
                        profile=config.profile,
                        region=region,
                        tenancy_id=config.tenancy_id,
                        compartment_id=config.compartment_id,
                    )
                self._opsi_clients[key] = await asyncio.to_thread(
                    self._create_opsi_client, config
                )
            return self._opsi_clients[key]

    def _create_logan_client(self, config: OCIConfig) -> Any:
        """Create Logan client (blocking, run in thread).

        Args:
            config: OCI configuration

        Returns:
            LogAnalyticsClient
        """
        oci = _get_oci()

        # Set timeout from env
        timeout = int(os.getenv("LOGAN_CLIENT_TIMEOUT", "30"))

        client = oci.log_analytics.LogAnalyticsClient(
            config.config,
            retry_strategy=oci.retry.DEFAULT_RETRY_STRATEGY,
            timeout=timeout,
        )

        # Override region if needed
        if config.region:
            client.base_client.set_region(config.region)

        return client

    async def get_logan_client(
        self, profile: str = "DEFAULT", region: Optional[str] = None
    ) -> Any:
        """Get Logan client for profile/region.

        Args:
            profile: OCI profile name
            region: Optional region override

        Returns:
            LogAnalyticsClient
        """
        key = f"{profile}:{region or 'default'}"

        async with self._lock:
            if key not in self._logan_clients:
                config = await self.get_config(profile)
                if region:
                    config = OCIConfig(
                        config=config.config,
                        profile=config.profile,
                        region=region,
                        tenancy_id=config.tenancy_id,
                        compartment_id=config.compartment_id,
                    )
                self._logan_clients[key] = await asyncio.to_thread(
                    self._create_logan_client, config
                )
            return self._logan_clients[key]

    def _create_dbm_client(self, config: OCIConfig) -> Any:
        """Create Database Management client (blocking, run in thread).

        Args:
            config: OCI configuration

        Returns:
            DbManagementClient
        """
        oci = _get_oci()

        timeout = int(os.getenv("DBM_CLIENT_TIMEOUT", "30"))

        client = oci.database_management.DbManagementClient(
            config.config,
            retry_strategy=oci.retry.DEFAULT_RETRY_STRATEGY,
            timeout=timeout,
        )

        if config.region:
            client.base_client.set_region(config.region)

        return client

    async def get_dbm_client(
        self, profile: str = "DEFAULT", region: Optional[str] = None
    ) -> Any:
        """Get Database Management client.

        Args:
            profile: OCI profile name
            region: Optional region override

        Returns:
            DbManagementClient
        """
        key = f"{profile}:{region or 'default'}"

        async with self._lock:
            if key not in self._dbm_clients:
                config = await self.get_config(profile)
                if region:
                    config = OCIConfig(
                        config=config.config,
                        profile=config.profile,
                        region=region,
                        tenancy_id=config.tenancy_id,
                        compartment_id=config.compartment_id,
                    )
                self._dbm_clients[key] = await asyncio.to_thread(
                    self._create_dbm_client, config
                )
            return self._dbm_clients[key]

    async def get_namespace(self, profile: str = "DEFAULT") -> str:
        """Get tenancy namespace (required for Logan queries).

        Args:
            profile: OCI profile name

        Returns:
            Namespace string
        """
        oci = _get_oci()
        config = await self.get_config(profile)

        def _get_ns():
            client = oci.object_storage.ObjectStorageClient(config.config)
            return client.get_namespace().data

        return await asyncio.to_thread(_get_ns)


# SQLcl client management (separate from OCI SDK)
_sqlcl_client = None
_sqlcl_lock = asyncio.Lock()
_sqlcl_config: Dict[str, Any] = {}


async def get_sqlcl_client(
    timeout: float = 120.0,
    home_dir: Optional[str] = None,
    restriction_level: Optional[int] = None,
) -> Any:
    """Get or create shared SQLcl MCP client.

    Reuses connection to avoid Java startup overhead.

    Args:
        timeout: Connection timeout in seconds
        home_dir: Custom SQLcl home directory for isolated configs.
                 Use this to limit which database connections are available.
                 Defaults to SQLCL_HOME env var or standard location.
        restriction_level: SQLcl restriction level (0-2) passed via -R flag.
                          0: Full access (default)
                          1: No file system access (spool, @script disabled)
                          2: No file system or environment access (most secure)

    Returns:
        Connected MCPClient for SQLcl
    """
    global _sqlcl_client, _sqlcl_config

    # Check if config changed - need new client
    new_config = {
        "home_dir": home_dir or os.getenv("SQLCL_HOME"),
        "restriction_level": restriction_level,
    }

    async with _sqlcl_lock:
        # Check if existing client matches config and is connected
        if _sqlcl_client is not None:
            if _sqlcl_config == new_config:
                try:
                    if hasattr(_sqlcl_client, "is_connected") and _sqlcl_client.is_connected:
                        return _sqlcl_client
                except Exception:
                    pass
            else:
                # Config changed, disconnect old client
                try:
                    await _sqlcl_client.disconnect()
                except Exception:
                    pass
                _sqlcl_client = None

        # Import MCP client
        try:
            from src.mcp.client.stdio import StdioTransport
            from src.mcp.client.client import MCPClient
        except ImportError:
            raise ImportError(
                "MCP client not available. Ensure src.mcp is installed."
            )

        sqlcl_path = os.getenv("SQLCL_PATH", "/Applications/sqlcl/bin/sql")

        if not os.path.exists(sqlcl_path):
            raise RuntimeError(f"SQLcl not found at {sqlcl_path}")

        # Build command args
        args = ["-mcp"]

        # Add restriction level flag (new SQLcl MCP feature)
        if restriction_level is not None:
            if restriction_level not in (0, 1, 2):
                raise ValueError("restriction_level must be 0, 1, or 2")
            args.extend(["-R", str(restriction_level)])

        # Add custom home directory (new SQLcl MCP feature)
        effective_home = home_dir or os.getenv("SQLCL_HOME")
        if effective_home:
            if not os.path.isdir(effective_home):
                raise RuntimeError(f"SQLcl home directory not found: {effective_home}")
            args.extend(["-home", effective_home])

        # Java options for better startup
        env = {
            "_JAVA_OPTIONS": "--enable-native-access=ALL-UNNAMED",
            "SQLCL_MCP_MODE": "true",
        }

        java_home = os.getenv("JAVA_HOME")
        if java_home:
            env["JAVA_HOME"] = java_home

        transport = StdioTransport(
            command=sqlcl_path,
            args=args,
            env=env,
        )
        client = MCPClient("sqlcl", transport)

        try:
            await asyncio.wait_for(client.connect(), timeout=timeout)
            _sqlcl_client = client
            _sqlcl_config = new_config
            return client
        except asyncio.TimeoutError:
            raise RuntimeError(
                f"SQLcl startup timeout ({timeout}s) - Java may be slow to initialize"
            )
        except Exception as e:
            raise RuntimeError(f"Failed to connect to SQLcl: {e}")


async def disconnect_sqlcl() -> bool:
    """Disconnect the shared SQLcl client.

    Returns:
        True if disconnected, False if no client
    """
    global _sqlcl_client

    async with _sqlcl_lock:
        if _sqlcl_client:
            try:
                await _sqlcl_client.disconnect()
            except Exception:
                pass
            _sqlcl_client = None
            return True
        return False


# Global OCI client manager instance
_oci_manager: Optional[OCIClientManager] = None


def get_oci_manager() -> OCIClientManager:
    """Get the global OCI client manager."""
    global _oci_manager
    if _oci_manager is None:
        _oci_manager = OCIClientManager()
    return _oci_manager
