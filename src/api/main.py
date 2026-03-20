"""FastAPI application factory."""

from contextlib import asynccontextmanager
from typing import Any, AsyncIterator

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from src.api.dependencies import get_server_registry, get_tool_catalog
from src.api.routes import agents_router, compliance_router, health_router, llm_router, mcp_router
from src.core import get_logger, settings
from src.logging import LogManager, OCILoggingHandler
from src.observability import init_tracing

logger = get_logger("api.main")


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Application lifespan handler."""
    logger.info("Starting OCI Database Observatory...")

    # Initialize OpenTelemetry
    if settings.otel_tracing_enabled:
        init_tracing(settings.otel_service_name)
        logger.info("OpenTelemetry tracing initialized")

    # Initialize OCI Logging
    if settings.oci_logging_enabled and settings.oci_compartment_id:
        try:
            log_manager = LogManager()
            await log_manager.initialize(
                log_group_name=settings.oci_log_group_name,
                log_name=settings.oci_log_name,
            )
            if log_manager.log_id:
                # Add OCI logging handler
                import logging
                root_logger = logging.getLogger()
                oci_handler = OCILoggingHandler(
                    log_id=log_manager.log_id,
                    service_name=settings.otel_service_name,
                )
                root_logger.addHandler(oci_handler)
                logger.info("OCI Logging initialized with APM correlation")
        except Exception as e:
            logger.warning("Failed to initialize OCI Logging", error=str(e))

    # Initialize MCP servers
    try:
        registry = get_server_registry()
        await registry.initialize()
        await registry.connect_all()
        logger.info("MCP servers initialized")

        # Refresh tool catalog
        catalog = get_tool_catalog(registry)
        await catalog.refresh()
        logger.info("Tool catalog refreshed", tool_count=len(catalog.list_tools()))
    except Exception as e:
        logger.error("Failed to initialize MCP servers", error=str(e))

    logger.info(
        "OCI Database Observatory started",
        port=settings.port,
        environment=settings.environment,
    )

    yield

    # Shutdown
    logger.info("Shutting down OCI Database Observatory...")
    try:
        registry = get_server_registry()
        await registry.disconnect_all()
    except Exception as e:
        logger.warning("Error during shutdown", error=str(e))


def create_app() -> FastAPI:
    """Create and configure FastAPI application."""
    app = FastAPI(
        title="OCI Database Observatory",
        description="Multi-agent framework for Oracle, MySQL, and PostgreSQL observability",
        version="0.1.0",
        lifespan=lifespan,
    )

    # CORS middleware
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],  # Configure appropriately for production
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Include routers
    app.include_router(health_router)
    app.include_router(agents_router)
    app.include_router(mcp_router)
    app.include_router(llm_router)
    app.include_router(compliance_router)

    @app.get("/")
    async def root() -> dict[str, Any]:
        """Root endpoint."""
        return {
            "service": "OCI Database Observatory",
            "version": "0.2.0",
            "docs": "/docs",
            "health": "/health",
            "endpoints": {
                "agents": "/agents/query",
                "mcp_tools": "/mcp/tools",
                "llm_providers": "/llm/providers",
                "compliance": "/compliance",
                "compliance_scan": "/compliance/scan",
                "compliance_report": "/compliance/report",
            },
        }

    return app


# Create app instance
app = create_app()
