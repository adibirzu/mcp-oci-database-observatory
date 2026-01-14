"""SQLcl MCP tools for database operations.

Provides SQL execution and schema inspection via Oracle SQLcl.

Supports new SQLcl MCP features (Jan 2026):
- Async query execution with job_id tracking
- Restriction levels (-R flag) for security
- Custom home directory (-home flag) for isolated configs
- Enhanced schema-information tool
"""

import asyncio
import socket
import time
import urllib.request
import uuid
from typing import Any, Dict, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from mcp.server.fastmcp import FastMCP

from ..clients import get_sqlcl_client, disconnect_sqlcl
from ..cache import cached_call

# Async job tracking storage
# Format: {job_id: {"status": str, "result": Any, "created_at": float, "sql": str}}
_async_jobs: Dict[str, Dict[str, Any]] = {}
_async_jobs_lock = asyncio.Lock()
MAX_ASYNC_JOBS = 5  # SQLcl supports up to 5 simultaneous background queries
JOB_TTL_SECONDS = 3600  # Jobs expire after 1 hour

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


async def _cleanup_expired_jobs() -> None:
    """Remove expired jobs from tracking storage."""
    async with _async_jobs_lock:
        now = time.time()
        expired = [
            job_id for job_id, job in _async_jobs.items()
            if now - job["created_at"] > JOB_TTL_SECONDS
        ]
        for job_id in expired:
            del _async_jobs[job_id]


async def _get_active_job_count() -> int:
    """Get count of running async jobs."""
    async with _async_jobs_lock:
        return sum(
            1 for job in _async_jobs.values()
            if job["status"] == "running"
        )


async def _create_async_job(sql: str, connection: str) -> str:
    """Create a new async job entry.

    Args:
        sql: SQL to execute
        connection: Database connection name

    Returns:
        Job ID

    Raises:
        RuntimeError: If max concurrent jobs exceeded
    """
    await _cleanup_expired_jobs()

    active_count = await _get_active_job_count()
    if active_count >= MAX_ASYNC_JOBS:
        raise RuntimeError(
            f"Max async jobs ({MAX_ASYNC_JOBS}) reached. "
            "Wait for running queries to complete or check job status."
        )

    job_id = str(uuid.uuid4())[:8]

    async with _async_jobs_lock:
        _async_jobs[job_id] = {
            "status": "running",
            "result": None,
            "error": None,
            "created_at": time.time(),
            "sql": sql[:200] + "..." if len(sql) > 200 else sql,
            "connection": connection,
        }

    return job_id


async def _update_job_status(
    job_id: str,
    status: str,
    result: Any = None,
    error: str | None = None
) -> None:
    """Update async job status."""
    async with _async_jobs_lock:
        if job_id in _async_jobs:
            _async_jobs[job_id]["status"] = status
            _async_jobs[job_id]["completed_at"] = time.time()
            if result is not None:
                _async_jobs[job_id]["result"] = result
            if error is not None:
                _async_jobs[job_id]["error"] = error


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

    @mcp.tool(
        name="oci_database_execute_sql",
        annotations={
            "title": "Execute SQL",
            "readOnlyHint": False,
            "destructiveHint": False,
            "idempotentHint": False,
            "openWorldHint": True,
        },
    )
    async def execute_sql(
        sql: str,
        connection: str = "default",
        async_mode: bool = False,
        restriction_level: Optional[int] = None,
    ) -> Dict[str, Any]:
        """Execute SQL directly on an Oracle database via SQLcl.

        Args:
            sql: SQL statement to execute
            connection: Database connection name
            async_mode: If True, execute in background and return job_id immediately.
                       Use oci_database_job_status to check progress. Max 5 concurrent.
            restriction_level: SQLcl restriction level (0-2). Higher = more restricted.
                              0: Full access (default)
                              1: No file system access
                              2: No file system or environment access (most secure)

        Returns:
            Query results, or job_id if async_mode=True
        """

        async def _execute_query(job_id: Optional[str] = None):
            """Inner function to execute query, optionally updating job status."""
            try:
                client = await get_sqlcl_client()

                # Connect to specified database if not default
                if connection != "default":
                    connect_result = await safe_call_tool(
                        client, "connect", {"connection_name": connection}, timeout=60.0
                    )
                    if isinstance(connect_result, dict) and "error" in connect_result:
                        error_result = {
                            "success": False,
                            "error": f"Connection failed: {connect_result['error']}",
                            "connection": connection,
                        }
                        if job_id:
                            await _update_job_status(
                                job_id, "failed", error=connect_result["error"]
                            )
                        return error_result

                # Build run-sql args
                run_args: Dict[str, Any] = {"sql": sql}

                # Add async flag for SQLcl MCP server (new feature)
                if async_mode and job_id:
                    run_args["async"] = True

                # Add restriction level if specified
                if restriction_level is not None:
                    run_args["restriction_level"] = restriction_level

                # Execute SQL with longer timeout for async (background execution)
                timeout = 300.0 if async_mode else 120.0
                result = await safe_call_tool(client, "run-sql", run_args, timeout=timeout)

                if isinstance(result, dict) and "error" in result:
                    if job_id:
                        await _update_job_status(job_id, "failed", error=result["error"])
                    return {
                        "success": False,
                        "error": result["error"],
                        "connection": connection,
                    }

                if job_id:
                    await _update_job_status(job_id, "completed", result=result)

                return {
                    "success": True,
                    "result": result,
                    "connection": connection,
                }

            except Exception as e:
                if job_id:
                    await _update_job_status(job_id, "failed", error=str(e))
                return {
                    "success": False,
                    "error": str(e),
                }

        # Async mode: create job, start background task, return immediately
        if async_mode:
            try:
                job_id = await _create_async_job(sql, connection)

                # Fire and forget - schedule execution without waiting
                asyncio.create_task(_execute_query(job_id))

                return {
                    "success": True,
                    "async": True,
                    "job_id": job_id,
                    "message": (
                    f"Query submitted as background job. "
                    f"Use oci_database_job_status(job_id='{job_id}') to check progress."
                ),
                    "connection": connection,
                }
            except RuntimeError as e:
                return {
                    "success": False,
                    "error": str(e),
                    "hint": "Use oci_database_job_status to check running jobs",
                }

        # Synchronous execution (default)
        return await _execute_query()

    @mcp.tool(
        name="oci_database_get_schema",
        annotations={
            "title": "Get Schema Info",
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": True,
        },
    )
    async def get_schema_info(
        schema: str,
        connection: str = "default",
        object_types: Optional[str] = None,
        include_columns: bool = True,
        include_constraints: bool = False,
        include_indexes: bool = False,
        include_comments: bool = True,
        table_filter: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Get schema information including tables, views, and objects.

        Enhanced schema-information tool that provides consolidated database
        metadata in a single call, reducing token usage for NL-to-SQL operations.

        Args:
            schema: Schema name to inspect (e.g., "HR", "USERS")
            connection: Database connection name
            object_types: Comma-separated list of object types to include.
                         Options: TABLES, VIEWS, PROCEDURES, FUNCTIONS, PACKAGES,
                         TRIGGERS, SEQUENCES, SYNONYMS, TYPES.
                         Default: all object types.
            include_columns: Include column details for tables/views (default: True)
            include_constraints: Include constraint definitions (default: False)
            include_indexes: Include index information (default: False)
            include_comments: Include table/column comments (default: True)
            table_filter: Filter tables by name pattern (SQL LIKE syntax, e.g., "EMP%")

        Returns:
            Structured schema metadata with tables, columns, data types, and more
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

            # Build schema-information args with new filtering options
            schema_args: Dict[str, Any] = {"schema": schema}

            if object_types:
                schema_args["object_types"] = object_types
            if not include_columns:
                schema_args["include_columns"] = False
            if include_constraints:
                schema_args["include_constraints"] = True
            if include_indexes:
                schema_args["include_indexes"] = True
            if not include_comments:
                schema_args["include_comments"] = False
            if table_filter:
                schema_args["table_filter"] = table_filter

            result = await safe_call_tool(
                client, "schema-information", schema_args, timeout=90.0
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
                "filters_applied": {
                    "object_types": object_types,
                    "include_columns": include_columns,
                    "include_constraints": include_constraints,
                    "include_indexes": include_indexes,
                    "include_comments": include_comments,
                    "table_filter": table_filter,
                },
            }

        # Use caching for schema info - include all filter params in cache key
        cache_params = {
            "schema": schema,
            "connection": connection,
            "object_types": object_types,
            "include_columns": include_columns,
            "include_constraints": include_constraints,
            "include_indexes": include_indexes,
            "include_comments": include_comments,
            "table_filter": table_filter,
        }
        return await cached_call("get_schema_info", cache_params, _fetch)

    @mcp.tool(
        name="oci_database_list_connections",
        annotations={
            "title": "List Database Connections",
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": True,
        },
    )
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

    @mcp.tool(
        name="oci_database_get_status",
        annotations={
            "title": "Get Database Status",
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": True,
        },
    )
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

    @mcp.tool(
        name="oci_database_disconnect",
        annotations={
            "title": "Disconnect Database",
            "readOnlyHint": False,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": True,
        },
    )
    async def sqlcl_disconnect() -> Dict[str, Any]:
        """Disconnect the shared SQLcl client.

        Returns:
            Disconnection status
        """
        result = await disconnect_sqlcl()
        if result:
            return {"success": True, "message": "SQLcl client disconnected"}
        return {"success": True, "message": "No active SQLcl client"}

    @mcp.tool(
        name="oci_database_job_status",
        annotations={
            "title": "Get Async Job Status",
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": True,
        },
    )
    async def get_job_status(
        job_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Get status of async SQL jobs.

        Use this to check on queries submitted with async_mode=True.

        Args:
            job_id: Specific job ID to check. If not provided, lists all jobs.

        Returns:
            Job status: running, completed, or failed. Includes result when complete.
        """
        await _cleanup_expired_jobs()

        async with _async_jobs_lock:
            if job_id:
                if job_id not in _async_jobs:
                    return {
                        "success": False,
                        "error": (
                            f"Job '{job_id}' not found. "
                            f"Jobs expire after {JOB_TTL_SECONDS // 60} minutes."
                        ),
                    }

                job = _async_jobs[job_id]
                response = {
                    "success": True,
                    "job_id": job_id,
                    "status": job["status"],
                    "sql": job["sql"],
                    "connection": job["connection"],
                    "created_at": job["created_at"],
                }

                if job["status"] == "completed":
                    response["result"] = job["result"]
                    response["completed_at"] = job.get("completed_at")
                elif job["status"] == "failed":
                    response["error"] = job["error"]
                    response["completed_at"] = job.get("completed_at")
                elif job["status"] == "running":
                    elapsed = time.time() - job["created_at"]
                    response["elapsed_seconds"] = round(elapsed, 1)

                return response

            # List all jobs
            jobs_summary = []
            for jid, job in _async_jobs.items():
                jobs_summary.append({
                    "job_id": jid,
                    "status": job["status"],
                    "sql": job["sql"],
                    "connection": job["connection"],
                    "created_at": job["created_at"],
                })

            running_count = sum(1 for j in jobs_summary if j["status"] == "running")

            return {
                "success": True,
                "total_jobs": len(jobs_summary),
                "running_jobs": running_count,
                "max_concurrent": MAX_ASYNC_JOBS,
                "jobs": jobs_summary,
            }

    @mcp.tool(
        name="oci_database_job_result",
        annotations={
            "title": "Get Async Job Result",
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": True,
        },
    )
    async def get_job_result(
        job_id: str,
        wait: bool = False,
        timeout: float = 60.0,
    ) -> Dict[str, Any]:
        """Get result of a completed async SQL job.

        Args:
            job_id: Job ID to retrieve result for
            wait: If True, wait for job to complete (up to timeout)
            timeout: Max seconds to wait if wait=True (default: 60)

        Returns:
            Query result if job completed, or status if still running
        """
        await _cleanup_expired_jobs()

        if wait:
            # Poll until complete or timeout
            start = time.time()
            while time.time() - start < timeout:
                async with _async_jobs_lock:
                    if job_id not in _async_jobs:
                        return {
                            "success": False,
                            "error": f"Job '{job_id}' not found",
                        }
                    job = _async_jobs[job_id]
                    if job["status"] != "running":
                        break
                await asyncio.sleep(0.5)

        async with _async_jobs_lock:
            if job_id not in _async_jobs:
                return {
                    "success": False,
                    "error": (
                        f"Job '{job_id}' not found. "
                        f"Jobs expire after {JOB_TTL_SECONDS // 60} minutes."
                    ),
                }

            job = _async_jobs[job_id]

            if job["status"] == "running":
                elapsed = time.time() - job["created_at"]
                return {
                    "success": True,
                    "status": "running",
                    "job_id": job_id,
                    "message": "Job still running. Use wait=True to block until complete.",
                    "elapsed_seconds": round(elapsed, 1),
                }

            if job["status"] == "failed":
                return {
                    "success": False,
                    "status": "failed",
                    "job_id": job_id,
                    "error": job["error"],
                }

            # Completed
            return {
                "success": True,
                "status": "completed",
                "job_id": job_id,
                "result": job["result"],
                "sql": job["sql"],
                "connection": job["connection"],
            }

    @mcp.tool(
        name="oci_database_job_cancel",
        annotations={
            "title": "Cancel Async Job",
            "readOnlyHint": False,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": True,
        },
    )
    async def cancel_job(job_id: str) -> Dict[str, Any]:
        """Cancel a running async SQL job.

        Note: This removes the job from tracking but may not stop
        the underlying SQL execution if already in progress.

        Args:
            job_id: Job ID to cancel

        Returns:
            Cancellation status
        """
        async with _async_jobs_lock:
            if job_id not in _async_jobs:
                return {
                    "success": False,
                    "error": f"Job '{job_id}' not found",
                }

            job = _async_jobs[job_id]
            status = job["status"]

            if status == "completed":
                return {
                    "success": False,
                    "error": "Job already completed",
                    "job_id": job_id,
                }

            # Mark as cancelled and remove
            del _async_jobs[job_id]

            return {
                "success": True,
                "message": f"Job '{job_id}' cancelled",
                "previous_status": status,
                "note": "SQL may still be executing on database if already started",
            }

    @mcp.tool(
        name="oci_database_check_network",
        annotations={
            "title": "Check Network Access",
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": True,
        },
    )
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

    @mcp.tool(
        name="oci_database_get_ip",
        annotations={
            "title": "Get My IP Address",
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": True,
        },
    )
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
