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

# Load environment from .env.local
from dotenv import load_dotenv
load_dotenv(".env.local")

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
logger.info(f"SQLCL_PATH: {os.getenv('SQLCL_PATH', 'not set')}")
logger.info(f"OCI_CONFIG_FILE: {os.getenv('OCI_CONFIG_FILE', '~/.oci/config')}")
logger.info(f"OCI_CLI_PROFILE: {os.getenv('OCI_CLI_PROFILE', 'DEFAULT')}")


def main():
    """Run the MCP server."""
    mcp.run()


if __name__ == "__main__":
    main()
