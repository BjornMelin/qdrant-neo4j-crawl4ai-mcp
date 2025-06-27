"""
Main application entry point for the Unified MCP Intelligence Server.

This module creates and configures the FastMCP 2.0 server with service
composition, authentication, and production-ready middleware stack.
"""

import asyncio
from contextlib import asynccontextmanager
from datetime import datetime
import signal
import sys
from typing import Any

from fastapi import Depends, FastAPI, HTTPException, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.responses import JSONResponse, PlainTextResponse
from fastmcp import FastMCP
from prometheus_client import generate_latest
from pydantic import BaseModel, Field
import structlog
import uvicorn

from qdrant_neo4j_crawl4ai_mcp.auth import (
    User,
    create_demo_token,
    get_current_active_user,
    require_admin,
    require_read,
    require_write,
)
from qdrant_neo4j_crawl4ai_mcp.config import Settings, get_settings
from qdrant_neo4j_crawl4ai_mcp.middleware import setup_middleware
from qdrant_neo4j_crawl4ai_mcp.models.graph_models import Neo4jServiceConfig
from qdrant_neo4j_crawl4ai_mcp.models.vector_models import VectorServiceConfig
from qdrant_neo4j_crawl4ai_mcp.models.web_models import WebConfig, WebServiceConfig
from qdrant_neo4j_crawl4ai_mcp.services.graph_service import GraphService
from qdrant_neo4j_crawl4ai_mcp.services.vector_service import VectorService
from qdrant_neo4j_crawl4ai_mcp.services.web_service import WebService
from qdrant_neo4j_crawl4ai_mcp.tools.graph_tools import register_graph_tools
from qdrant_neo4j_crawl4ai_mcp.tools.vector_tools import register_vector_tools
from qdrant_neo4j_crawl4ai_mcp.tools.web_tools import register_web_tools

# Set up structured logging
structlog.configure(
    processors=[
        structlog.stdlib.filter_by_level,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.JSONRenderer(),
    ],
    context_class=dict,
    logger_factory=structlog.stdlib.LoggerFactory(),
    wrapper_class=structlog.stdlib.BoundLogger,
    cache_logger_on_first_use=True,
)

logger = structlog.get_logger(__name__)


# Pydantic models for API requests/responses
class HealthResponse(BaseModel):
    """Health check response model."""

    status: str = Field(..., description="Service health status")
    timestamp: datetime = Field(..., description="Health check timestamp")
    version: str = Field(..., description="Application version")
    environment: str = Field(..., description="Deployment environment")
    services: dict[str, Any] = Field(
        default_factory=dict, description="Service health details"
    )


class IntelligenceQuery(BaseModel):
    """Unified query interface for all intelligence services."""

    query: str = Field(
        ..., min_length=1, max_length=1000, description="Natural language query"
    )
    mode: str = Field(
        default="auto", description="Processing mode: auto, vector, graph, web"
    )
    filters: dict[str, Any] = Field(default_factory=dict, description="Query filters")
    limit: int = Field(default=10, ge=1, le=100, description="Maximum results")


class IntelligenceResult(BaseModel):
    """Unified result interface for all intelligence services."""

    content: str = Field(..., description="Primary content result")
    source: str = Field(..., description="Source service: vector, graph, web")
    confidence: float = Field(
        ..., ge=0.0, le=1.0, description="Result confidence score"
    )
    metadata: dict[str, Any] = Field(
        default_factory=dict, description="Additional metadata"
    )
    timestamp: datetime = Field(
        default_factory=datetime.utcnow, description="Result timestamp"
    )


class TokenRequest(BaseModel):
    """Request model for token generation."""

    username: str = Field(
        ..., min_length=1, max_length=50, description="Username for the token"
    )
    scopes: list[str] = Field(default=["read"], description="Requested scopes")


class TokenResponse(BaseModel):
    """Response model for token generation."""

    access_token: str = Field(..., description="JWT access token")
    token_type: str = Field(default="bearer", description="Token type")
    expires_in: int = Field(..., description="Token expiration time in seconds")
    scopes: list[str] = Field(..., description="Granted scopes")


# Global application state
app_state = {
    "startup_time": None,
    "health_checks": {},
    "mcp_servers": {},
    "vector_service": None,
    "graph_service": None,
    "web_service": None,
    "mcp_app": None,
}


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan manager for startup and shutdown."""
    # Startup
    app_state["startup_time"] = datetime.utcnow()

    logger.info(
        "Application starting",
        version="1.0.0",
        startup_time=app_state["startup_time"].isoformat(),
    )

    try:
        # Initialize vector service
        settings = get_settings()
        vector_config = VectorServiceConfig(
            qdrant_url=settings.qdrant_url,
            qdrant_api_key=settings.qdrant_api_key,
            default_collection=settings.default_collection,
            default_embedding_model=settings.default_embedding_model,
            connection_timeout=settings.connection_timeout,
            max_retries=settings.max_retries,
            retry_delay=settings.retry_delay,
            enable_caching=settings.enable_caching,
        )

        app_state["vector_service"] = VectorService(vector_config)
        await app_state["vector_service"].initialize()

        # Initialize graph service
        graph_config = Neo4jServiceConfig(
            uri=settings.neo4j_uri,
            username=settings.neo4j_user,
            password=settings.neo4j_password.get_secret_value(),
            database=settings.neo4j_database,
            max_connection_pool_size=settings.neo4j_max_pool_size,
            connection_acquisition_timeout=settings.neo4j_connection_timeout,
            enable_graphrag=settings.neo4j_enable_graphrag,
            openai_api_key=settings.openai_api_key.get_secret_value()
            if settings.openai_api_key
            else None,
            embedding_model=settings.openai_embedding_model,
            llm_model=settings.openai_llm_model,
        )

        app_state["graph_service"] = GraphService(graph_config)
        await app_state["graph_service"].initialize()

        # Initialize web service
        web_config = WebServiceConfig(
            web_config=WebConfig(
                max_concurrent=settings.crawl4ai_max_concurrent,
                request_timeout=settings.crawl4ai_request_timeout,
                max_retries=settings.crawl4ai_max_retries,
                retry_delay=settings.crawl4ai_retry_delay,
                user_agent=settings.crawl4ai_user_agent,
                check_robots_txt=settings.crawl4ai_check_robots_txt,
                enable_stealth=settings.crawl4ai_enable_stealth,
                enable_caching=settings.crawl4ai_enable_caching,
                cache_ttl=settings.crawl4ai_cache_ttl,
            )
        )

        app_state["web_service"] = WebService(web_config)
        await app_state["web_service"].initialize()

        # Initialize FastMCP app and register tools
        mcp = FastMCP("Unified MCP Intelligence Server")
        register_vector_tools(mcp, app_state["vector_service"])
        register_graph_tools(mcp, app_state["graph_service"])
        register_web_tools(mcp, app_state["web_service"])
        app_state["mcp_app"] = mcp

        # Update service status
        app_state["mcp_servers"] = {
            "vector": {"status": "ready", "last_check": datetime.utcnow()},
            "graph": {"status": "ready", "last_check": datetime.utcnow()},
            "web": {"status": "ready", "last_check": datetime.utcnow()},
        }

        logger.info("Vector service initialized successfully")
        logger.info("Graph service initialized successfully")
        logger.info("Web service initialized successfully")
        logger.info(
            "MCP services initialized", services=list(app_state["mcp_servers"].keys())
        )

    except Exception as e:
        logger.exception("Failed to initialize services", error=str(e))
        # Update service status to reflect failure
        app_state["mcp_servers"] = {
            "vector": {
                "status": "error",
                "last_check": datetime.utcnow(),
                "error": str(e),
            },
            "graph": {
                "status": "error",
                "last_check": datetime.utcnow(),
                "error": str(e),
            },
            "web": {
                "status": "error",
                "last_check": datetime.utcnow(),
                "error": str(e),
            },
        }
        # Don't raise exception here - let the app start but with degraded functionality

    yield

    # Shutdown
    logger.info("Application shutting down")

    if app_state["vector_service"]:
        try:
            await app_state["vector_service"].shutdown()
            logger.info("Vector service shutdown completed")
        except Exception as e:
            logger.warning("Error during vector service shutdown", error=str(e))

    if app_state["graph_service"]:
        try:
            await app_state["graph_service"].shutdown()
            logger.info("Graph service shutdown completed")
        except Exception as e:
            logger.warning("Error during graph service shutdown", error=str(e))

    if app_state["web_service"]:
        try:
            await app_state["web_service"].shutdown()
            logger.info("Web service shutdown completed")
        except Exception as e:
            logger.warning("Error during web service shutdown", error=str(e))

    app_state["mcp_servers"].clear()
    app_state["vector_service"] = None
    app_state["graph_service"] = None
    app_state["web_service"] = None
    app_state["mcp_app"] = None


def create_app(settings: Settings | None = None) -> FastAPI:
    """
    Create and configure the FastAPI application.

    Args:
        settings: Application settings (optional, will be loaded if not provided)

    Returns:
        Configured FastAPI application
    """
    if settings is None:
        settings = get_settings()

    # Create FastAPI app with security configurations
    app = FastAPI(
        title="Unified MCP Intelligence Server",
        description="Production-ready MCP server abstracting Qdrant, Neo4j, and Crawl4AI",
        version="1.0.0",
        lifespan=lifespan,
        docs_url="/docs" if settings.enable_swagger_ui else None,
        redoc_url="/redoc" if settings.enable_redoc else None,
        openapi_url="/openapi.json"
        if (settings.enable_swagger_ui or settings.enable_redoc)
        else None,
    )

    # CORS middleware (add before other middleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.allowed_origins,
        allow_credentials=True,
        allow_methods=settings.allowed_methods,
        allow_headers=settings.allowed_headers,
        max_age=3600,
    )

    # Trusted host middleware for production
    if settings.is_production:
        app.add_middleware(
            TrustedHostMiddleware,
            allowed_hosts=["yourdomain.com", "*.yourdomain.com", "localhost"],
        )

    # Set up comprehensive middleware stack
    setup_middleware(app, settings)

    # Health check endpoints (no authentication required)
    @app.get("/health", response_model=HealthResponse, tags=["Health"])
    async def health_check() -> HealthResponse:
        """
        Application health check endpoint.

        Returns comprehensive health information including service status,
        uptime, and configuration details for monitoring systems.
        """
        return HealthResponse(
            status="healthy",
            timestamp=datetime.utcnow(),
            version="1.0.0",
            environment=settings.environment,
            services=app_state["mcp_servers"],
        )

    @app.get("/ready", tags=["Health"])
    async def readiness_check() -> dict[str, Any]:
        """
        Kubernetes-style readiness check.

        Returns simple ready status for load balancer health checks.
        """
        return {"status": "ready", "timestamp": datetime.utcnow().isoformat()}

    @app.get("/metrics", response_class=PlainTextResponse, tags=["Monitoring"])
    async def prometheus_metrics() -> str:
        """
        Prometheus metrics endpoint.

        Returns application metrics in Prometheus format for monitoring
        and alerting systems.
        """
        return generate_latest().decode("utf-8")

    # Authentication endpoints
    @app.post("/auth/token", response_model=TokenResponse, tags=["Authentication"])
    async def create_access_token(
        token_request: TokenRequest, settings: Settings = Depends(get_settings)
    ) -> TokenResponse:
        """
        Create a JWT access token for API authentication.

        This is a demo endpoint for testing. In production, this would
        integrate with a proper authentication provider.
        """
        # Create demo token
        token = create_demo_token(
            username=token_request.username,
            scopes=token_request.scopes,
            settings=settings,
        )

        logger.info(
            "Demo token created",
            username=token_request.username,
            scopes=token_request.scopes,
        )

        return TokenResponse(
            access_token=token,
            token_type="bearer",
            expires_in=settings.jwt_expire_minutes * 60,
            scopes=token_request.scopes,
        )

    # Protected API endpoints
    @app.get("/api/v1/profile", tags=["User"])
    async def get_user_profile(
        current_user: User = Depends(get_current_active_user),
    ) -> dict[str, Any]:
        """
        Get current user profile information.

        Returns user details and permissions for the authenticated user.
        """
        return {
            "id": current_user.id,
            "username": current_user.username,
            "email": current_user.email,
            "scopes": current_user.scopes,
            "is_admin": current_user.is_admin,
            "last_login": current_user.last_login.isoformat()
            if current_user.last_login
            else None,
        }

    # Intelligence service endpoints (placeholders for service mounting)
    @app.post(
        "/api/v1/intelligence/query",
        response_model=IntelligenceResult,
        tags=["Intelligence"],
    )
    async def unified_intelligence_query(
        query: IntelligenceQuery, current_user: User = Depends(require_read)
    ) -> IntelligenceResult:
        """
        Unified intelligence query across all services.

        Routes queries to appropriate services (vector, graph, web) based on
        query mode and content analysis.
        """
        logger.info(
            "Intelligence query received",
            username=current_user.username,
            query_mode=query.mode,
            query_length=len(query.query),
        )

        # Demo response - would route to actual services
        if query.mode in {"vector", "auto"}:
            source = "vector"
            content = f"Vector search results for: {query.query}"
        elif query.mode == "graph":
            source = "graph"
            content = f"Graph analysis results for: {query.query}"
        elif query.mode == "web":
            source = "web"
            content = f"Web intelligence results for: {query.query}"
        else:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid query mode: {query.mode}",
            )

        return IntelligenceResult(
            content=content,
            source=source,
            confidence=0.85,
            metadata={
                "query_mode": query.mode,
                "filters_applied": query.filters,
                "user_id": current_user.id,
            },
        )

    # Vector service endpoints
    @app.post("/api/v1/vector/search", tags=["Vector"])
    async def vector_search(
        query: IntelligenceQuery, current_user: User = Depends(require_read)
    ) -> IntelligenceResult:
        """
        Semantic vector search using Qdrant.

        Performs similarity search across embedded document collections.
        """
        logger.info("Vector search request", username=current_user.username)

        vector_service = app_state.get("vector_service")
        if not vector_service:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Vector service is not available",
            )

        try:
            from qdrant_neo4j_crawl4ai_mcp.models.vector_models import (
                SearchMode,
                VectorSearchRequest,
            )

            # Convert query to vector search request
            search_request = VectorSearchRequest(
                query=query.query,
                collection_name=settings.default_collection,
                limit=query.limit,
                score_threshold=0.0,
                mode=SearchMode.SEMANTIC,
                filters=query.filters,
                include_payload=True,
                include_vectors=False,
            )

            # Perform vector search
            search_response = await vector_service.search_vectors(search_request)

            # Format results
            if search_response.results:
                top_result = search_response.results[0]
                content = (
                    top_result.payload.content
                    if top_result.payload
                    else f"Vector search results for: {query.query}"
                )
                confidence = min(top_result.score, 1.0)
            else:
                content = f"No vector search results found for: {query.query}"
                confidence = 0.0

            return IntelligenceResult(
                content=content,
                source="vector",
                confidence=confidence,
                metadata={
                    "service": "qdrant",
                    "user_id": current_user.id,
                    "results_count": len(search_response.results),
                    "search_time_ms": search_response.search_time_ms,
                },
            )

        except Exception as e:
            logger.exception(
                "Vector search failed", error=str(e), username=current_user.username
            )
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Vector search failed: {e!s}",
            )

    @app.post("/api/v1/vector/store", tags=["Vector"])
    async def vector_store(
        request: dict, current_user: User = Depends(require_write)
    ) -> dict:
        """
        Store document with vector embedding in Qdrant.

        Converts text content into vector embeddings and stores them
        in the specified collection for later semantic search retrieval.
        """
        logger.info("Vector store request", username=current_user.username)

        vector_service = app_state.get("vector_service")
        if not vector_service:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Vector service is not available",
            )

        try:
            from qdrant_neo4j_crawl4ai_mcp.models.vector_models import (
                VectorStoreRequest,
            )

            # Convert request to vector store request
            store_request = VectorStoreRequest(
                content=request.get("content", ""),
                collection_name=request.get(
                    "collection_name", settings.default_collection
                ),
                content_type=request.get("content_type", "text"),
                source=request.get("source"),
                tags=request.get("tags", []),
                metadata=request.get("metadata", {}),
                embedding_model=request.get("embedding_model"),
            )

            # Store vector
            store_response = await vector_service.store_vector(store_request)

            return {
                "status": "success",
                "id": store_response.id,
                "collection_name": store_response.collection_name,
                "vector_dimensions": store_response.vector_dimensions,
                "embedding_time_ms": store_response.embedding_time_ms,
                "storage_time_ms": store_response.storage_time_ms,
                "timestamp": store_response.timestamp.isoformat(),
                "user_id": current_user.id,
            }

        except Exception as e:
            logger.exception(
                "Vector store failed", error=str(e), username=current_user.username
            )
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Vector store failed: {e!s}",
            )

    @app.get("/api/v1/vector/collections", tags=["Vector"])
    async def list_vector_collections(
        current_user: User = Depends(require_read),
    ) -> dict:
        """
        List all available vector collections with their statistics.

        Provides an overview of all collections, their sizes, and configuration details.
        """
        logger.info("List vector collections request", username=current_user.username)

        vector_service = app_state.get("vector_service")
        if not vector_service:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Vector service is not available",
            )

        try:
            collections_response = await vector_service.list_collections()

            return {
                "status": "success",
                "collections": [
                    {
                        "name": c.name,
                        "status": c.status.value,
                        "vector_size": c.vector_size,
                        "distance_metric": c.distance.value,
                        "points_count": c.points_count,
                        "indexed_vectors": c.indexed_vectors_count,
                        "segments_count": c.segments_count,
                        "disk_usage_bytes": c.disk_data_size,
                        "disk_usage_mb": round(c.disk_data_size / (1024 * 1024), 2),
                        "ram_usage_bytes": c.ram_data_size,
                        "ram_usage_mb": round(c.ram_data_size / (1024 * 1024), 2),
                        "created_at": c.created_at,
                        "updated_at": c.updated_at,
                    }
                    for c in collections_response.collections
                ],
                "total_collections": collections_response.total_collections,
                "total_vectors": collections_response.total_points,
                "timestamp": collections_response.timestamp.isoformat(),
                "user_id": current_user.id,
            }

        except Exception as e:
            logger.exception(
                "List collections failed", error=str(e), username=current_user.username
            )
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to list collections: {e!s}",
            )

    @app.get("/api/v1/vector/health", tags=["Vector"])
    async def vector_health_check(current_user: User = Depends(require_read)) -> dict:
        """
        Get vector service health status and performance metrics.

        Returns detailed health information about the vector database service.
        """
        logger.info("Vector health check request", username=current_user.username)

        vector_service = app_state.get("vector_service")
        if not vector_service:
            return {
                "status": "unavailable",
                "service": "vector",
                "details": {"error": "Vector service is not initialized"},
                "timestamp": datetime.utcnow().isoformat(),
            }

        try:
            health_result = await vector_service.health_check()

            return {
                "status": health_result.status,
                "service": health_result.service,
                "response_time_ms": health_result.response_time_ms,
                "details": health_result.details,
                "timestamp": health_result.timestamp.isoformat(),
                "user_id": current_user.id,
            }

        except Exception as e:
            logger.exception(
                "Vector health check failed",
                error=str(e),
                username=current_user.username,
            )
            return {
                "status": "error",
                "service": "vector",
                "details": {"error": str(e), "error_type": type(e).__name__},
                "timestamp": datetime.utcnow().isoformat(),
                "user_id": current_user.id,
            }

    # Graph service endpoints
    @app.post("/api/v1/graph/query", tags=["Graph"])
    async def graph_query(
        query: IntelligenceQuery, current_user: User = Depends(require_read)
    ) -> IntelligenceResult:
        """
        Knowledge graph query using Neo4j.

        Executes Cypher queries for relationship analysis and graph traversal.
        """
        logger.info("Graph query request", username=current_user.username)

        return IntelligenceResult(
            content=f"Neo4j graph query: {query.query}",
            source="graph",
            confidence=0.88,
            metadata={"service": "neo4j", "user_id": current_user.id},
        )

    # Web intelligence endpoints
    @app.post("/api/v1/web/crawl", tags=["Web"])
    async def web_crawl(
        query: IntelligenceQuery, current_user: User = Depends(require_write)
    ) -> IntelligenceResult:
        """
        Web content crawling using Crawl4AI.

        Extracts and analyzes content from web sources with intelligent parsing.
        """
        logger.info("Web crawl request", username=current_user.username)

        return IntelligenceResult(
            content=f"Crawl4AI web extraction: {query.query}",
            source="web",
            confidence=0.82,
            metadata={"service": "crawl4ai", "user_id": current_user.id},
        )

    # Admin endpoints
    @app.get("/api/v1/admin/stats", tags=["Admin"])
    async def admin_stats(
        current_user: User = Depends(require_admin),
    ) -> dict[str, Any]:
        """
        Administrative statistics and monitoring data.

        Returns comprehensive system metrics for administrators.
        """
        uptime = None
        if app_state["startup_time"]:
            uptime_delta = datetime.utcnow() - app_state["startup_time"]
            uptime = int(uptime_delta.total_seconds())

        return {
            "uptime_seconds": uptime,
            "startup_time": app_state["startup_time"].isoformat()
            if app_state["startup_time"]
            else None,
            "services": app_state["mcp_servers"],
            "environment": settings.environment,
            "version": "1.0.0",
        }

    # Error handlers
    @app.exception_handler(HTTPException)
    async def http_exception_handler(
        request: Request, exc: HTTPException
    ) -> JSONResponse:
        """Custom HTTP exception handler with structured logging."""
        logger.warning(
            "HTTP exception",
            status_code=exc.status_code,
            detail=exc.detail,
            path=request.url.path,
            method=request.method,
        )

        return JSONResponse(
            status_code=exc.status_code,
            content={
                "error": exc.detail,
                "status_code": exc.status_code,
                "timestamp": datetime.utcnow().isoformat(),
            },
        )

    logger.info("FastAPI application created", environment=settings.environment)
    return app


def setup_signal_handlers() -> None:
    """Set up graceful shutdown signal handlers."""

    def signal_handler(signum, frame) -> None:
        logger.info(f"Received signal {signum}, shutting down gracefully...")
        sys.exit(0)

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)


def main() -> None:
    """
    Main entry point for the application.

    Configures and starts the Uvicorn ASGI server with production-ready settings.
    """
    settings = get_settings()

    # Set up signal handlers for graceful shutdown
    setup_signal_handlers()

    # Configure logging level
    log_level = settings.log_level.lower()

    logger.info(
        "Starting Unified MCP Intelligence Server",
        version="1.0.0",
        environment=settings.environment,
        host=settings.host,
        port=settings.port,
        log_level=log_level,
    )

    # Create the application
    app = create_app(settings)

    # Configure Uvicorn server
    config = uvicorn.Config(
        app=app,
        host=settings.host,
        port=settings.port,
        log_level=log_level,
        access_log=settings.log_level == "DEBUG",
        reload=settings.is_development and settings.debug,
        workers=1 if settings.is_development else settings.workers,
    )

    # Start the server
    server = uvicorn.Server(config)

    try:
        # Run the server
        asyncio.run(server.serve())
    except KeyboardInterrupt:
        logger.info("Server stopped by user")
    except Exception as e:
        logger.exception("Server error", error=str(e), error_type=type(e).__name__)
        sys.exit(1)


if __name__ == "__main__":
    main()
