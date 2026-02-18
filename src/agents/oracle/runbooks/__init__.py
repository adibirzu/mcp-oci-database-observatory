"""Oracle diagnostic runbooks module.

This module provides SQL-based diagnostic runbooks for Oracle database
troubleshooting. Each runbook contains multiple queries targeting specific
diagnostic areas.

Runbooks:
    - blocking_sessions: Detect lock contention and blocking chains
    - long_operations: Monitor V$SESSION_LONGOPS for extended operations
    - parallelism_stats: Analyze parallel execution and downgrades
    - full_table_scans: Identify expensive full table scans
    - sql_monitor: Real-time SQL execution monitoring (V$SQL_MONITOR)
"""

from pathlib import Path
from typing import NamedTuple

# Runbook directory path
RUNBOOKS_DIR = Path(__file__).parent

# Available runbooks
RUNBOOK_FILES = {
    "blocking_sessions": "blocking_sessions.sql",
    "long_operations": "long_operations.sql",
    "parallelism_stats": "parallelism_stats.sql",
    "full_table_scans": "full_table_scans.sql",
    "sql_monitor": "sql_monitor.sql",
}


class RunbookQuery(NamedTuple):
    """A single query from a runbook."""

    name: str
    description: str
    sql: str


class Runbook(NamedTuple):
    """A diagnostic runbook with multiple queries."""

    name: str
    description: str
    queries: list[RunbookQuery]


def parse_runbook(content: str) -> list[RunbookQuery]:
    """Parse SQL file into individual queries.

    Queries are separated by comments starting with '-- Query N:'
    """
    queries = []
    current_query = None
    current_sql_lines: list[str] = []
    current_description = ""

    for line in content.split("\n"):
        # Check for query marker
        if line.strip().startswith("-- Query"):
            # Save previous query if exists
            if current_query is not None:
                sql = "\n".join(current_sql_lines).strip()
                if sql:
                    queries.append(RunbookQuery(
                        name=current_query,
                        description=current_description,
                        sql=sql,
                    ))

            # Extract query name from marker
            parts = line.split(":", 1)
            current_query = parts[0].replace("--", "").strip()
            current_description = parts[1].strip() if len(parts) > 1 else ""
            current_sql_lines = []

        elif current_query is not None:
            # Skip leading description comments
            if line.startswith("--") and not current_sql_lines:
                # Append to description
                comment = line.replace("--", "").strip()
                if comment and current_description:
                    current_description += " " + comment
                elif comment:
                    current_description = comment
            else:
                current_sql_lines.append(line)

    # Don't forget the last query
    if current_query is not None:
        sql = "\n".join(current_sql_lines).strip()
        if sql:
            queries.append(RunbookQuery(
                name=current_query,
                description=current_description,
                sql=sql,
            ))

    return queries


def load_runbook(name: str) -> Runbook:
    """Load a runbook by name.

    Args:
        name: Runbook name (e.g., 'blocking_sessions')

    Returns:
        Parsed runbook with queries

    Raises:
        ValueError: If runbook name is not found
        FileNotFoundError: If runbook file is missing
    """
    if name not in RUNBOOK_FILES:
        available = ", ".join(RUNBOOK_FILES.keys())
        raise ValueError(f"Unknown runbook: {name}. Available: {available}")

    filepath = RUNBOOKS_DIR / RUNBOOK_FILES[name]
    if not filepath.exists():
        raise FileNotFoundError(f"Runbook file not found: {filepath}")

    content = filepath.read_text()

    # Extract description from file header
    lines = content.split("\n")
    description = ""
    for line in lines[:5]:  # Check first 5 lines for description
        if line.startswith("-- Purpose:"):
            description = line.replace("-- Purpose:", "").strip()
            break

    queries = parse_runbook(content)

    return Runbook(
        name=name,
        description=description,
        queries=queries,
    )


def list_runbooks() -> dict[str, str]:
    """List all available runbooks with descriptions.

    Returns:
        Dict mapping runbook name to description
    """
    runbooks = {}
    for name in RUNBOOK_FILES:
        try:
            runbook = load_runbook(name)
            runbooks[name] = runbook.description
        except (FileNotFoundError, ValueError):
            runbooks[name] = "Description not available"
    return runbooks


def get_query(runbook_name: str, query_name: str) -> RunbookQuery | None:
    """Get a specific query from a runbook.

    Args:
        runbook_name: Name of the runbook
        query_name: Name of the query (e.g., 'Query 1')

    Returns:
        RunbookQuery if found, None otherwise
    """
    try:
        runbook = load_runbook(runbook_name)
        for query in runbook.queries:
            if query.name.lower() == query_name.lower():
                return query
        return None
    except (FileNotFoundError, ValueError):
        return None


__all__ = [
    "RUNBOOK_FILES",
    "Runbook",
    "RunbookQuery",
    "load_runbook",
    "list_runbooks",
    "get_query",
    "parse_runbook",
]
