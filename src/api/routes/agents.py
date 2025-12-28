"""Agent routes."""

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from src.agents.base.context import AgentContext
from src.agents.coordinator import CoordinatorAgent
from src.agents.database import MySQLAgent, OracleAgent, PostgresAgent
from src.api.dependencies import (
    get_agent_context,
    get_coordinator,
    get_mysql_agent,
    get_oracle_agent,
    get_postgres_agent,
)
from src.observability import create_span

router = APIRouter(prefix="/agents", tags=["agents"])


class QueryRequest(BaseModel):
    """Agent query request."""

    query: str
    database_type: str | None = None
    connection_name: str | None = None
    parameters: dict[str, Any] | None = None


class QueryResponse(BaseModel):
    """Agent query response."""

    success: bool
    agent: str
    database_type: str | None = None
    response: Any
    error: str | None = None


@router.post("/query")
async def query_agent(
    request: QueryRequest,
    coordinator: Annotated[CoordinatorAgent, Depends(get_coordinator)],
    context: Annotated[AgentContext, Depends(get_agent_context)],
) -> QueryResponse:
    """Query the coordinator agent."""
    with create_span(
        "api.agents.query",
        component="api",
        attributes={"query": request.query[:100]},
    ):
        try:
            result = await coordinator.process_query(
                query=request.query,
                context=context,
                parameters=request.parameters,
            )

            return QueryResponse(
                success=result.get("success", False),
                agent=result.get("agent", "coordinator"),
                database_type=result.get("database_type"),
                response=result.get("response") or result.get("results"),
                error=result.get("error"),
            )
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))


@router.post("/oracle/query")
async def query_oracle(
    request: QueryRequest,
    agent: Annotated[OracleAgent, Depends(get_oracle_agent)],
    context: Annotated[AgentContext, Depends(get_agent_context)],
) -> QueryResponse:
    """Query the Oracle agent directly."""
    with create_span(
        "api.agents.oracle.query",
        component="api",
    ):
        try:
            # Connect if connection provided
            if request.connection_name:
                await agent.connect(request.connection_name, context)

            result = await agent.process(
                query=request.query,
                context=context,
                parameters=request.parameters,
            )

            return QueryResponse(
                success=result.get("success", False),
                agent="oracle_agent",
                database_type="oracle",
                response=result,
                error=result.get("error"),
            )
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))


@router.post("/mysql/query")
async def query_mysql(
    request: QueryRequest,
    agent: Annotated[MySQLAgent, Depends(get_mysql_agent)],
    context: Annotated[AgentContext, Depends(get_agent_context)],
) -> QueryResponse:
    """Query the MySQL agent directly."""
    with create_span(
        "api.agents.mysql.query",
        component="api",
    ):
        try:
            if request.connection_name:
                await agent.connect(request.connection_name, context)

            result = await agent.process(
                query=request.query,
                context=context,
                parameters=request.parameters,
            )

            return QueryResponse(
                success=result.get("success", False),
                agent="mysql_agent",
                database_type="mysql",
                response=result,
                error=result.get("error"),
            )
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))


@router.post("/postgres/query")
async def query_postgres(
    request: QueryRequest,
    agent: Annotated[PostgresAgent, Depends(get_postgres_agent)],
    context: Annotated[AgentContext, Depends(get_agent_context)],
) -> QueryResponse:
    """Query the PostgreSQL agent directly."""
    with create_span(
        "api.agents.postgres.query",
        component="api",
    ):
        try:
            if request.connection_name:
                await agent.connect(request.connection_name, context)

            result = await agent.process(
                query=request.query,
                context=context,
                parameters=request.parameters,
            )

            return QueryResponse(
                success=result.get("success", False),
                agent="postgres_agent",
                database_type="postgres",
                response=result,
                error=result.get("error"),
            )
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))


@router.get("/status")
async def agents_status(
    oracle: Annotated[OracleAgent, Depends(get_oracle_agent)],
    mysql: Annotated[MySQLAgent, Depends(get_mysql_agent)],
    postgres: Annotated[PostgresAgent, Depends(get_postgres_agent)],
) -> dict[str, Any]:
    """Get status of all agents."""
    return {
        "agents": [
            {
                "name": oracle.name,
                "type": oracle.database_type,
                "capabilities": [c.value for c in oracle.capabilities],
            },
            {
                "name": mysql.name,
                "type": mysql.database_type,
                "capabilities": [c.value for c in mysql.capabilities],
            },
            {
                "name": postgres.name,
                "type": postgres.database_type,
                "capabilities": [c.value for c in postgres.capabilities],
            },
        ],
    }
