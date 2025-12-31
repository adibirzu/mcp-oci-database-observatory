"""SQLcl MCP tools for database operations.

Provides SQL execution and schema inspection via Oracle SQLcl.
"""

import asyncio
import os
import socket
import urllib.request
from typing import Any, Dict, TYPE_CHECKING

if TYPE_CHECKING:
    from mcp.server.fastmcp import FastMCP

from ..clients import get_sqlcl_client, disconnect_sqlcl
from ..cache import cached_call, get_cache

# ACL-related Oracle error patterns
ACL_ERROR_PATTERNS = [
    "ORA-12526",  # TNS:listener: all appropriate instances are in restricted mode
    "ORA-12547",  # TNS:lost contact
    "ORA-12170",  # TNS:Connect timeout
    "ORA-12541",  # TNS:no listener
    "ORA-12543",  # TNS:destination host unreachable
    "ORA-12514",  # TNS:listener does not currently know of service
    "ORA-12505",  # TNS:listener does not currently know of SID
    "ORA-28000",  # the account is locked
    "ORA-28001",  # the password has expired
    "ORA-01017",  # invalid username/password
    "ORA-12154",  # TNS:could not resolve the connect identifier
    "connection refused",
    "network is unreachable",
    "host is unreachable",
    "connection timed out",
    "access denied",
    "not authorized",
    "ACL",
    "whitelist",
    "blocked",
]


def get_public_ip() -> str | None:
    """Get the public IP address of this machine."""
    services = [
        "https://api.ipify.org",
        "https://checkip.amazonaws.com",
        "https://ifconfig.me/ip",
        "https://icanhazip.com",
    ]

    for service in services:
        try:
            with urllib.request.urlopen(service, timeout=5) as response:
                return response.read().decode("utf-8").strip()
        except Exception:
            continue

    return None


def check_acl_error(error_message: str) -> Dict[str, Any] | None:
    """Check if an error message indicates an ACL/network access issue."""
    error_lower = error_message.lower()

    for pattern in ACL_ERROR_PATTERNS:
        if pattern.lower() in error_lower:
            public_ip = get_public_ip()

            return {
                "acl_error": True,
                "error_type": "network_access_denied",
                "detected_pattern": pattern,
                "your_public_ip": public_ip,
                "message": f"Connection blocked - your IP ({public_ip or 'unknown'}) may not be in the database ACL",
                "resolution": [
                    "1. Go to OCI Console > Autonomous Database > Network",
                    "2. Add your IP to the Access Control List (ACL)",
                    f"3. Add IP: {public_ip}" if public_ip else "3. Determine your public IP and add it",
                    "4. Wait 1-2 minutes for ACL changes to propagate",
                    "5. Retry the connection",
                ],
                "original_error": error_message,
            }

    return None


async def safe_call_tool(client, tool_name: str, args: dict, timeout: float = 90.0) -> Any:
    """Safely call a tool with timeout and error handling."""
    try:
        result = await asyncio.wait_for(
            client.call_tool(tool_name, args),
            timeout=timeout,
        )

        # Check result for ACL errors
        result_str = str(result) if result else ""
        acl_error = check_acl_error(result_str)
        if acl_error:
            return acl_error

        return result
    except asyncio.TimeoutError:
        acl_check = check_acl_error("connection timed out")
        if acl_check:
            acl_check["timeout"] = timeout
            return acl_check
        return {"error": f"Tool '{tool_name}' timeout after {timeout}s"}
    except Exception as e:
        error_str = str(e)
        acl_error = check_acl_error(error_str)
        if acl_error:
            return acl_error
        return {"error": error_str}


def register_tools(mcp: "FastMCP") -> None:
    """Register SQLcl tools with the MCP server."""

    @mcp.tool()
    async def execute_sql(
        sql: str,
        connection: str = "default",
    ) -> Dict[str, Any]:
        """Execute SQL directly on an Oracle database via SQLcl.

        Args:
            sql: SQL statement to execute
            connection: Database connection name

        Returns:
            Query results or execution status
        """
        try:
            client = await get_sqlcl_client()

            # Connect to specified database if not default
            if connection != "default":
                connect_result = await safe_call_tool(
                    client, "connect", {"connection_name": connection}, timeout=60.0
                )
                if isinstance(connect_result, dict) and "error" in connect_result:
                    return {
                        "success": False,
                        "error": f"Connection failed: {connect_result['error']}",
                        "connection": connection,
                    }

            # Execute SQL
            result = await safe_call_tool(client, "run-sql", {"sql": sql}, timeout=120.0)

            if isinstance(result, dict) and "error" in result:
                return {
                    "success": False,
                    "error": result["error"],
                    "connection": connection,
                }

            return {
                "success": True,
                "result": result,
                "connection": connection,
            }

        except Exception as e:
            return {
                "success": False,
                "error": str(e),
            }

    @mcp.tool()
    async def get_schema_info(
        schema: str,
        connection: str = "default",
    ) -> Dict[str, Any]:
        """Get schema information including tables, views, and objects.

        Args:
            schema: Schema name to inspect (e.g., "HR", "USERS")
            connection: Database connection name

        Returns:
            Schema metadata including tables, views, procedures
        """

        async def _fetch():
            client = await get_sqlcl_client()

            if connection != "default":
                connect_result = await safe_call_tool(
                    client, "connect", {"connection_name": connection}, timeout=60.0
                )
                if isinstance(connect_result, dict) and "error" in connect_result:
                    return {
                        "success": False,
                        "error": f"Connection failed: {connect_result['error']}",
                    }

            result = await safe_call_tool(
                client, "schema-information", {"schema": schema}, timeout=90.0
            )

            if isinstance(result, dict) and "error" in result:
                return {
                    "success": False,
                    "error": result["error"],
                    "schema": schema,
                }

            return {
                "success": True,
                "schema": schema,
                "result": result,
            }

        # Use caching for schema info
        return await cached_call(
            "get_schema_info",
            {"schema": schema, "connection": connection},
            _fetch,
        )

    @mcp.tool()
    async def list_connections() -> Dict[str, Any]:
        """List available database connections configured in SQLcl.

        Returns:
            List of connection names and their status
        """

        async def _fetch():
            client = await get_sqlcl_client()
            result = await safe_call_tool(client, "list-connections", {}, timeout=30.0)

            if isinstance(result, dict) and "error" in result:
                return {
                    "success": False,
                    "error": result["error"],
                }

            return {
                "success": True,
                "connections": result,
            }

        return await cached_call("list_connections", {}, _fetch)

    @mcp.tool()
    async def database_status(
        connection: str = "default",
    ) -> Dict[str, Any]:
        """Get the status of a database connection.

        Args:
            connection: Database connection name

        Returns:
            Connection status and database information
        """
        try:
            client = await get_sqlcl_client()

            # Get list of connections first
            connections = await safe_call_tool(client, "list-connections", {}, timeout=30.0)

            # Try to connect to specified database
            connect_result = None
            if connection != "default":
                connect_result = await safe_call_tool(
                    client, "connect", {"connection_name": connection}, timeout=60.0
                )

            # Get basic status query
            status_result = await safe_call_tool(
                client,
                "run-sql",
                {"sql": "SELECT INSTANCE_NAME, STATUS, DATABASE_STATUS FROM V$INSTANCE"},
                timeout=60.0,
            )

            return {
                "success": True,
                "connection": connection,
                "available_connections": connections,
                "connect_result": connect_result,
                "instance_status": status_result,
            }

        except Exception as e:
            return {
                "success": False,
                "error": str(e),
                "connection": connection,
            }

    @mcp.tool()
    async def sqlcl_disconnect() -> Dict[str, Any]:
        """Disconnect the shared SQLcl client.

        Returns:
            Disconnection status
        """
        result = await disconnect_sqlcl()
        if result:
            return {"success": True, "message": "SQLcl client disconnected"}
        return {"success": True, "message": "No active SQLcl client"}

    @mcp.tool()
    async def check_network_access(
        host: str = "",
        port: int = 1522,
    ) -> Dict[str, Any]:
        """Check network access and ACL status for database connections.

        Args:
            host: Database host to test (optional)
            port: Port to test (default: 1522 for Oracle ATP)

        Returns:
            Network access status including your public IP
        """
        result = {
            "success": True,
            "your_public_ip": None,
            "hostname": socket.gethostname(),
            "network_tests": {},
        }

        # Get public IP
        public_ip = get_public_ip()
        result["your_public_ip"] = public_ip

        if not public_ip:
            result["warning"] = "Could not determine public IP - check internet connection"

        # Get local IPs
        try:
            local_ips = []
            for info in socket.getaddrinfo(socket.gethostname(), None):
                ip = info[4][0]
                if ip not in local_ips and not ip.startswith("127."):
                    local_ips.append(ip)
            result["local_ips"] = local_ips[:5]
        except Exception:
            result["local_ips"] = []

        # Test connectivity if host provided
        if host:
            result["network_tests"]["target"] = f"{host}:{port}"

            # DNS resolution
            try:
                resolved_ips = socket.gethostbyname_ex(host)[2]
                result["network_tests"]["dns_resolved"] = True
                result["network_tests"]["resolved_ips"] = resolved_ips[:3]
            except socket.gaierror as e:
                result["network_tests"]["dns_resolved"] = False
                result["network_tests"]["dns_error"] = str(e)
                result["success"] = False

            # TCP connectivity test
            if result["network_tests"].get("dns_resolved"):
                try:
                    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                    sock.settimeout(10)
                    sock_result = sock.connect_ex((host, port))
                    sock.close()

                    if sock_result == 0:
                        result["network_tests"]["tcp_connect"] = True
                        result["network_tests"]["port_open"] = True
                    else:
                        result["network_tests"]["tcp_connect"] = False
                        result["network_tests"]["port_open"] = False
                        result["network_tests"]["connect_error_code"] = sock_result
                        result["acl_warning"] = {
                            "message": f"Cannot connect to {host}:{port}",
                            "possible_cause": "Your IP may not be in the database ACL",
                            "your_ip": public_ip,
                            "action": "Add your IP to the database's Access Control List in OCI Console",
                        }
                except socket.timeout:
                    result["network_tests"]["tcp_connect"] = False
                    result["network_tests"]["error"] = "Connection timeout"
                    result["acl_warning"] = {
                        "message": "Connection timed out - likely ACL blocked",
                        "your_ip": public_ip,
                        "action": "Add your IP to the database's Access Control List",
                    }
                except Exception as e:
                    result["network_tests"]["tcp_connect"] = False
                    result["network_tests"]["error"] = str(e)

        # Provide ACL guidance
        result["acl_guidance"] = {
            "your_ip_to_whitelist": public_ip,
            "steps": [
                "1. Log into OCI Console",
                "2. Navigate to Autonomous Database > Your Database",
                "3. Click 'Network' in the left menu",
                "4. Under 'Access Control List', click 'Edit'",
                f"5. Add IP address: {public_ip}" if public_ip else "5. Add your public IP address",
                "6. Save changes and wait 1-2 minutes",
            ],
        }

        return result

    @mcp.tool()
    async def get_my_ip() -> Dict[str, Any]:
        """Get your current public IP address.

        Returns:
            Your public IP address and network info
        """
        public_ip = get_public_ip()

        return {
            "success": True,
            "public_ip": public_ip,
            "hostname": socket.gethostname(),
            "message": f"Add this IP to your database ACL: {public_ip}" if public_ip else "Could not determine public IP",
        }
