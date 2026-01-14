"""OCI Database Observatory MCP Server entry point.

Run with: python -m src.mcp_server

A modular, multi-tenancy MCP server for:
- Oracle Database operations via SQLcl
- OCI Operations Insights (OPSI) analytics
- OCI Logging Analytics (Logan) queries
- Multi-tenancy profile management

Observability:
- OCI APM tracing via OpenTelemetry
- OCI Logging with APM trace correlation
"""

import atexit
import logging
import os
import sys
from pathlib import Path

# Load environment from .env.local with cascading search
from dotenv import load_dotenv


def _find_and_load_env() -> str | None:
    """Find and load .env.local from multiple candidate locations.

    Returns:
        Path to loaded .env.local or None if not found
    """
    # 1. Explicit override via environment variable
    explicit_path = os.getenv("OCI_ENV_FILE")
    if explicit_path:
        expanded = Path(explicit_path).expanduser()
        if expanded.exists():
            load_dotenv(expanded)
            return str(expanded)

    # 2. Current working directory
    cwd_env = Path.cwd() / ".env.local"
    if cwd_env.exists():
        load_dotenv(cwd_env)
        return str(cwd_env)

    # 3. Project root (this file is at src/mcp_server/__main__.py)
    project_root = Path(__file__).parent.parent.parent / ".env.local"
    if project_root.exists():
        load_dotenv(project_root)
        return str(project_root)

    # 4. Search parent directories (up to 3 levels from cwd)
    current = Path.cwd()
    for _ in range(3):
        parent_env = current.parent / ".env.local"
        if parent_env.exists():
            load_dotenv(parent_env)
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
            load_dotenv(path)
            return str(path)

    return None


_env_file_loaded = _find_and_load_env()

# Configure logging to stderr (MCP stdio-safe)
logging.basicConfig(
    level=getattr(logging, os.getenv("MCP_LOG_LEVEL", "INFO").upper(), logging.INFO),
    stream=sys.stderr,
    format="%(asctime)s [%(levelname)s] %(name)s - %(message)s",
)
logger = logging.getLogger("oci-database-observatory")

# Initialize observability (APM + Logging)
from src.observability import init_tracing, shutdown_tracing
from src.observability.oci_logging import init_oci_logging, shutdown_oci_logging

# Initialize OCI APM tracing
logger.info("Initializing OCI APM tracing...")
init_tracing(component="mcp_executor")

# Initialize OCI Logging
logger.info("Initializing OCI Logging...")
init_oci_logging(profile=os.getenv("OCI_CLI_PROFILE", "DEFAULT"))

# Register shutdown handlers
def shutdown_observability():
    """Shutdown observability on exit."""
    logger.info("Shutting down observability...")
    shutdown_oci_logging()
    shutdown_tracing()

atexit.register(shutdown_observability)

# Import FastMCP
from mcp.server.fastmcp import FastMCP

# Initialize FastMCP server
mcp = FastMCP(name="oci-database-observatory")

# Import and register all tool modules
from .tools import register_all_tools

register_all_tools(mcp)

# Log startup
logger.info("OCI Database Observatory MCP Server starting...")
logger.info(f"ENV_FILE_LOADED: {_env_file_loaded or 'none found'}")
logger.info(f"SQLCL_PATH: {os.getenv('SQLCL_PATH', 'not set')}")
logger.info(f"OCI_CONFIG_FILE: {os.getenv('OCI_CONFIG_FILE', '~/.oci/config')}")
logger.info(f"OCI_CLI_PROFILE: {os.getenv('OCI_CLI_PROFILE', 'DEFAULT')}")
logger.info(f"OCI_COMPARTMENT_ID: {os.getenv('OCI_COMPARTMENT_ID', 'not set')[:50] + '...' if os.getenv('OCI_COMPARTMENT_ID') else 'not set'}")
logger.info(f"OCI_DEFAULT_DBMGMT_COMPARTMENT_ID: {'set' if os.getenv('OCI_DEFAULT_DBMGMT_COMPARTMENT_ID') else 'not set'}")
logger.info(f"OCI_PRODUCTION_DBMGMT_COMPARTMENT_ID: {'set' if os.getenv('OCI_PRODUCTION_DBMGMT_COMPARTMENT_ID') else 'not set'}")


def main():
    """Run the MCP server."""
    mcp.run()


if __name__ == "__main__":
    main()
