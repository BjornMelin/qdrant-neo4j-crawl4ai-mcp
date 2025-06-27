"""
Comprehensive test configuration for the Unified MCP Intelligence Server.

This module provides advanced pytest fixtures and configuration for testing
modern MCP server applications with async services, dependency injection,
and production-grade testing patterns.

Key Features:
- Async-first testing with proper lifecycle management
- Service mocking and dependency injection
- Test environment configuration
- Performance testing fixtures
- Security testing setup
- Contract testing support
"""

import asyncio
from collections.abc import AsyncGenerator, Generator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
import os
from typing import Any
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4
import warnings

from fastapi import FastAPI
from fastapi.testclient import TestClient
import httpx
import pytest
import structlog

# Import application components
from qdrant_neo4j_crawl4ai_mcp.auth import User, create_demo_token
from qdrant_neo4j_crawl4ai_mcp.config import Settings
from qdrant_neo4j_crawl4ai_mcp.main import create_app
from qdrant_neo4j_crawl4ai_mcp.models.graph_models import (
    GraphNode,
    GraphRelationship,
    Neo4jServiceConfig,
    NodeType,
    RelationshipType,
)
from qdrant_neo4j_crawl4ai_mcp.models.vector_models import (
    VectorSearchRequest,
    VectorServiceConfig,
    VectorStoreRequest,
)
from qdrant_neo4j_crawl4ai_mcp.models.web_models import WebConfig, WebServiceConfig
from qdrant_neo4j_crawl4ai_mcp.services.graph_service import GraphService
from qdrant_neo4j_crawl4ai_mcp.services.vector_service import VectorService
from qdrant_neo4j_crawl4ai_mcp.services.web_service import WebService

# Configure test logging
structlog.configure(
    processors=[
        structlog.stdlib.filter_by_level,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.dev.ConsoleRenderer(colors=False),
    ],
    context_class=dict,
    logger_factory=structlog.stdlib.LoggerFactory(),
    wrapper_class=structlog.stdlib.BoundLogger,
    cache_logger_on_first_use=True,
)

# Suppress warnings from dependencies during testing
warnings.filterwarnings("ignore", category=DeprecationWarning)
warnings.filterwarnings("ignore", category=UserWarning)

# Test configuration constants
TEST_DATABASE_URL = "sqlite:///test.db"
TEST_COLLECTION_NAME = "test_collection"
TEST_EMBEDDING_MODEL = "sentence-transformers/all-MiniLM-L6-v2"


# =============================================================================
# Session-scoped fixtures
# =============================================================================


@pytest.fixture(scope="session")
def event_loop() -> Generator[asyncio.AbstractEventLoop, None, None]:
    """Create an instance of the default event loop for the test session."""
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    yield loop
    loop.close()


@pytest.fixture(scope="session")
def test_settings() -> Settings:
    """Create test settings with overrides for testing environment."""
    return Settings(
        # Environment
        environment="test",
        debug=True,
        log_level="DEBUG",
        # Server configuration
        host="127.0.0.1",
        port=8000,
        workers=1,
        # Security (use test secrets)
        jwt_secret_key="test-secret-key-for-testing-only",
        jwt_algorithm="HS256",
        jwt_expire_minutes=30,
        # Service URLs (use test instances)
        qdrant_url="http://localhost:6333",
        qdrant_api_key=None,
        neo4j_uri="bolt://localhost:7687",
        neo4j_user="neo4j",
        neo4j_password="password",
        neo4j_database="test",
        # Test configurations
        default_collection=TEST_COLLECTION_NAME,
        default_embedding_model=TEST_EMBEDDING_MODEL,
        connection_timeout=10,
        max_retries=2,
        retry_delay=0.1,
        enable_caching=False,  # Disable caching in tests
        # API documentation (enable for test debugging)
        enable_swagger_ui=True,
        enable_redoc=True,
        # Performance settings for testing
        crawl4ai_max_concurrent=2,
        crawl4ai_request_timeout=10,
        crawl4ai_max_retries=1,
        # CORS settings for testing
        allowed_origins=["*"],
        allowed_methods=["*"],
        allowed_headers=["*"],
    )


# =============================================================================
# Service configuration fixtures
# =============================================================================


@pytest.fixture
def vector_service_config(test_settings: Settings) -> VectorServiceConfig:
    """Create vector service configuration for testing."""
    return VectorServiceConfig(
        qdrant_url=test_settings.qdrant_url,
        qdrant_api_key=test_settings.qdrant_api_key,
        default_collection=test_settings.default_collection,
        default_embedding_model=test_settings.default_embedding_model,
        connection_timeout=test_settings.connection_timeout,
        max_retries=test_settings.max_retries,
        retry_delay=test_settings.retry_delay,
        enable_caching=test_settings.enable_caching,
    )


@pytest.fixture
def graph_service_config(test_settings: Settings) -> Neo4jServiceConfig:
    """Create graph service configuration for testing."""
    return Neo4jServiceConfig(
        uri=test_settings.neo4j_uri,
        username=test_settings.neo4j_user,
        password=test_settings.neo4j_password.get_secret_value(),
        database=test_settings.neo4j_database,
        max_connection_pool_size=5,
        connection_acquisition_timeout=10,
        enable_graphrag=True,
        openai_api_key="test-openai-key",
        embedding_model="text-embedding-3-large",
        llm_model="gpt-4o",
    )


@pytest.fixture
def web_service_config(test_settings: Settings) -> WebServiceConfig:
    """Create web service configuration for testing."""
    return WebServiceConfig(
        web_config=WebConfig(
            max_concurrent=test_settings.crawl4ai_max_concurrent,
            request_timeout=test_settings.crawl4ai_request_timeout,
            max_retries=test_settings.crawl4ai_max_retries,
            retry_delay=test_settings.crawl4ai_retry_delay,
            user_agent="MCP-Test-Agent/1.0",
            check_robots_txt=False,  # Disable robots.txt checking in tests
            enable_stealth=False,
            enable_caching=False,
            cache_ttl=0,
        )
    )


# =============================================================================
# Mock service fixtures
# =============================================================================


@pytest.fixture
def mock_qdrant_client() -> AsyncMock:
    """Create a mock Qdrant client for testing."""
    client = AsyncMock()

    # Configure common mock behaviors
    client.get_health_status.return_value = {"status": "green"}
    client.list_collections.return_value = []
    client.create_collection.return_value = True
    client.delete_collection.return_value = True
    client.upsert_points.return_value = True
    client.search_points.return_value = []
    client.get_collection_info.return_value = MagicMock(
        points_count=0, vectors_count=0, status="green"
    )

    return client


@pytest.fixture
def mock_neo4j_driver() -> AsyncMock:
    """Create a mock Neo4j driver for testing."""
    driver = AsyncMock()

    # Mock session context
    session = AsyncMock()
    session.run.return_value = AsyncMock()
    session.close.return_value = None

    driver.session.return_value.__aenter__.return_value = session
    driver.session.return_value.__aexit__.return_value = None
    driver.close.return_value = None
    driver.verify_connectivity.return_value = None

    return driver


@pytest.fixture
def mock_openai_client() -> AsyncMock:
    """Create a mock OpenAI client for testing."""
    client = AsyncMock()

    # Mock chat completion
    mock_completion = AsyncMock()
    mock_completion.choices = [
        MagicMock(message=MagicMock(content='{"entities": [], "relationships": []}'))
    ]
    client.chat.completions.create.return_value = mock_completion

    # Mock embeddings
    mock_embedding = AsyncMock()
    mock_embedding.data = [MagicMock(embedding=[0.1] * 1536)]
    client.embeddings.create.return_value = mock_embedding

    return client


@pytest.fixture
def mock_crawl4ai_client() -> AsyncMock:
    """Create a mock Crawl4AI client for testing."""
    client = AsyncMock()

    # Configure mock behaviors
    client.crawl.return_value = {
        "success": True,
        "data": {
            "markdown": "# Test Content\n\nThis is test content.",
            "cleaned_html": "<h1>Test Content</h1><p>This is test content.</p>",
            "media": {"images": [], "videos": []},
            "links": {"internal": [], "external": []},
            "metadata": {"title": "Test Page", "description": "Test description"},
        },
    }

    return client


# =============================================================================
# Service instance fixtures
# =============================================================================


@pytest.fixture
async def mock_vector_service(
    vector_service_config: VectorServiceConfig, mock_qdrant_client: AsyncMock
) -> AsyncGenerator[VectorService, None]:
    """Create a mocked vector service instance."""
    service = VectorService(vector_service_config)
    service.qdrant_client = mock_qdrant_client

    # Mock embedding service
    service.embedding_service = AsyncMock()
    service.embedding_service.generate_embeddings.return_value = (
        [[0.1, 0.2, 0.3] * 128],  # 384-dimensional vector
        {"dimensions": 384, "processing_time_ms": 50.0},
    )

    await service.initialize()
    yield service
    await service.shutdown()


@pytest.fixture
async def mock_graph_service(
    graph_service_config: Neo4jServiceConfig,
    mock_neo4j_driver: AsyncMock,  # noqa: ARG001
    mock_openai_client: AsyncMock,
) -> AsyncGenerator[GraphService, None]:
    """Create a mocked graph service instance."""
    service = GraphService(graph_service_config)
    service.client = AsyncMock()
    service._openai_client = mock_openai_client  # noqa: SLF001

    await service.initialize()
    yield service
    await service.shutdown()


@pytest.fixture
async def mock_web_service(
    web_service_config: WebServiceConfig, mock_crawl4ai_client: AsyncMock
) -> AsyncGenerator[WebService, None]:
    """Create a mocked web service instance."""
    service = WebService(web_service_config)
    service.client = mock_crawl4ai_client

    await service.initialize()
    yield service
    await service.shutdown()


# =============================================================================
# Application fixtures
# =============================================================================


@pytest.fixture
async def test_app(test_settings: Settings) -> FastAPI:
    """Create a FastAPI test application with mocked services."""
    return create_app(test_settings)


@pytest.fixture
def test_client(test_app: FastAPI) -> TestClient:
    """Create a synchronous test client for the FastAPI application."""
    return TestClient(test_app)


@pytest.fixture
async def async_test_client(
    test_app: FastAPI,
) -> AsyncGenerator[httpx.AsyncClient, None]:
    """Create an async test client for the FastAPI application."""
    async with httpx.AsyncClient(
        app=test_app, base_url="http://test", timeout=30.0
    ) as client:
        yield client


# =============================================================================
# Authentication fixtures
# =============================================================================


@pytest.fixture
def test_user() -> User:
    """Create a test user for authentication testing."""
    return User(
        id=str(uuid4()),
        username="testuser",
        email="test@example.com",
        scopes=["read", "write"],
        is_admin=False,
        is_active=True,
        last_login=datetime.now(UTC),
    )


@pytest.fixture
def admin_user() -> User:
    """Create an admin test user for authorization testing."""
    return User(
        id=str(uuid4()),
        username="admin",
        email="admin@example.com",
        scopes=["read", "write", "admin"],
        is_admin=True,
        is_active=True,
        last_login=datetime.now(UTC),
    )


@pytest.fixture
def test_token(test_settings: Settings, test_user: User) -> str:
    """Create a JWT token for the test user."""
    return create_demo_token(
        username=test_user.username, scopes=test_user.scopes, settings=test_settings
    )


@pytest.fixture
def admin_token(test_settings: Settings, admin_user: User) -> str:
    """Create a JWT token for the admin user."""
    return create_demo_token(
        username=admin_user.username, scopes=admin_user.scopes, settings=test_settings
    )


@pytest.fixture
def auth_headers(test_token: str) -> dict[str, str]:
    """Create authentication headers with test token."""
    return {"Authorization": f"Bearer {test_token}"}


@pytest.fixture
def admin_auth_headers(admin_token: str) -> dict[str, str]:
    """Create authentication headers with admin token."""
    return {"Authorization": f"Bearer {admin_token}"}


# =============================================================================
# Test data fixtures
# =============================================================================


@pytest.fixture
def sample_vector_store_request() -> VectorStoreRequest:
    """Create a sample vector store request for testing."""
    return VectorStoreRequest(
        content="This is a test document for vector storage and search testing.",
        collection_name=TEST_COLLECTION_NAME,
        content_type="text",
        source="test_source",
        tags=["test", "sample", "vector"],
        metadata={"test_id": str(uuid4()), "created_by": "test_suite"},
        embedding_model=TEST_EMBEDDING_MODEL,
    )


@pytest.fixture
def sample_vector_search_request() -> VectorSearchRequest:
    """Create a sample vector search request for testing."""
    return VectorSearchRequest(
        query="test document search query",
        collection_name=TEST_COLLECTION_NAME,
        limit=10,
        score_threshold=0.7,
        include_payload=True,
        include_vectors=False,
    )


@pytest.fixture
def sample_graph_node() -> GraphNode:
    """Create a sample graph node for testing."""
    return GraphNode(
        name="Test Entity",
        node_type=NodeType.ENTITY,
        description="A test entity for graph testing",
        confidence_score=0.9,
        properties={"test_property": "test_value"},
        embedding=[0.1] * 384,
    )


@pytest.fixture
def sample_graph_relationship() -> GraphRelationship:
    """Create a sample graph relationship for testing."""
    return GraphRelationship(
        source_id="node_1",
        target_id="node_2",
        relationship_type=RelationshipType.RELATES_TO,
        weight=0.8,
        confidence=0.9,
        properties={"test_relation": "test_value"},
    )


# =============================================================================
# Performance testing fixtures
# =============================================================================


@pytest.fixture
def performance_monitor():
    """Monitor performance metrics during testing."""
    import time

    import psutil

    process = psutil.Process()
    start_time = time.time()
    start_memory = process.memory_info().rss
    start_cpu = process.cpu_percent()

    class PerformanceMetrics:
        def get_metrics(self) -> dict[str, Any]:
            current_time = time.time()
            current_memory = process.memory_info().rss
            current_cpu = process.cpu_percent()

            return {
                "execution_time": current_time - start_time,
                "memory_usage_mb": current_memory / (1024 * 1024),
                "memory_growth_mb": (current_memory - start_memory) / (1024 * 1024),
                "cpu_usage_percent": current_cpu,
                "avg_cpu_percent": (start_cpu + current_cpu) / 2,
            }

    return PerformanceMetrics()


# =============================================================================
# Integration testing fixtures
# =============================================================================


@pytest.fixture(scope="session")
def integration_services_available() -> bool:
    """Check if integration test services are available."""
    import socket

    services = [
        ("localhost", 6333),  # Qdrant
        ("localhost", 7687),  # Neo4j
    ]

    for host, port in services:
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(1)
            result = sock.connect_ex((host, port))
            sock.close()
            if result != 0:
                return False
        except Exception:
            return False

    return True


@pytest.fixture
def skip_if_no_integration_services(integration_services_available: bool):
    """Skip test if integration services are not available."""
    if not integration_services_available:
        pytest.skip("Integration services (Qdrant, Neo4j) not available")


# =============================================================================
# Async context managers for testing
# =============================================================================


@asynccontextmanager
async def mcp_test_context(
    vector_service: VectorService,
    graph_service: GraphService,
    web_service: WebService,
    test_settings: Settings,
):
    """Async context manager for MCP server testing with real services."""
    try:
        # Initialize services
        await vector_service.initialize()
        await graph_service.initialize()
        await web_service.initialize()

        # Create app with services
        app = create_app(test_settings)

        # Override app state with test services
        from qdrant_neo4j_crawl4ai_mcp.main import app_state

        app_state.update(
            {
                "vector_service": vector_service,
                "graph_service": graph_service,
                "web_service": web_service,
            }
        )

        yield app

    finally:
        # Cleanup services
        if vector_service:
            await vector_service.shutdown()
        if graph_service:
            await graph_service.shutdown()
        if web_service:
            await web_service.shutdown()


# =============================================================================
# Test utility functions
# =============================================================================


def assert_valid_mcp_response(response_data: dict[str, Any]) -> None:
    """Assert that a response follows MCP protocol format."""
    assert "jsonrpc" in response_data
    assert response_data["jsonrpc"] == "2.0"
    assert "id" in response_data

    # Either result or error should be present
    assert "result" in response_data or "error" in response_data


def assert_performance_within_limits(
    metrics: dict[str, Any], max_time: float = 1.0, max_memory_mb: float = 100.0
) -> None:
    """Assert that performance metrics are within acceptable limits."""
    assert metrics["execution_time"] < max_time, (
        f"Execution time {metrics['execution_time']:.2f}s exceeds {max_time}s"
    )
    assert metrics["memory_growth_mb"] < max_memory_mb, (
        f"Memory growth {metrics['memory_growth_mb']:.2f}MB exceeds {max_memory_mb}MB"
    )


async def wait_for_async_condition(
    condition_func, timeout_duration: float = 10.0, interval: float = 0.1
) -> bool:
    """Wait for an async condition to become true."""
    import asyncio
    import time

    start_time = time.time()

    while time.time() - start_time < timeout_duration:
        if await condition_func():
            return True
        await asyncio.sleep(interval)

    return False


# =============================================================================
# Pytest configuration
# =============================================================================


def pytest_configure(config):
    """Configure pytest with custom markers and settings."""
    # Register custom markers
    config.addinivalue_line(
        "markers", "unit: Unit tests that don't require external dependencies"
    )
    config.addinivalue_line(
        "markers", "integration: Integration tests that require external services"
    )
    config.addinivalue_line(
        "markers", "e2e: End-to-end tests that test complete workflows"
    )
    config.addinivalue_line(
        "markers", "slow: Tests that take more than 1 second to run"
    )
    config.addinivalue_line("markers", "network: Tests that require network access")
    config.addinivalue_line("markers", "security: Security-focused tests")
    config.addinivalue_line(
        "markers", "performance: Performance and benchmarking tests"
    )
    config.addinivalue_line(
        "markers", "property: Property-based tests using Hypothesis"
    )
    config.addinivalue_line(
        "markers", "contract: Contract tests for MCP tool interfaces"
    )


def pytest_collection_modifyitems(config, items):  # noqa: ARG001
    """Modify test collection to apply markers automatically."""
    for item in items:
        # Auto-mark slow tests
        if "slow" in item.keywords or any(
            marker in item.nodeid.lower()
            for marker in ["performance", "load", "benchmark"]
        ):
            item.add_marker(pytest.mark.slow)

        # Auto-mark integration tests
        if "integration" in item.nodeid:
            item.add_marker(pytest.mark.integration)

        # Auto-mark unit tests
        if "unit" in item.nodeid:
            item.add_marker(pytest.mark.unit)


@pytest.fixture(autouse=True)
async def cleanup_after_test():
    """Cleanup fixture that runs after each test."""
    yield

    # Clean up any remaining async tasks
    try:
        pending_tasks = [
            task
            for task in asyncio.all_tasks()
            if not task.done() and task != asyncio.current_task()
        ]

        if pending_tasks:
            await asyncio.wait_for(
                asyncio.gather(*pending_tasks, return_exceptions=True), timeout=5.0
            )
    except TimeoutError:
        # Force cancel remaining tasks
        for task in pending_tasks:
            task.cancel()


# =============================================================================
# Environment setup for different test types
# =============================================================================


@pytest.fixture
def test_environment():
    """Set up test environment variables."""
    original_env = os.environ.copy()

    # Set test environment variables
    test_env = {
        "ENVIRONMENT": "test",
        "LOG_LEVEL": "DEBUG",
        "JWT_SECRET_KEY": "test-secret-key",
        "QDRANT_URL": "http://localhost:6333",
        "NEO4J_URI": "bolt://localhost:7687",
        "NEO4J_USER": "neo4j",
        "NEO4J_PASSWORD": "password",
        "NEO4J_DATABASE": "test",
        "OPENAI_API_KEY": "test-openai-key",
    }

    os.environ.update(test_env)

    yield test_env

    # Restore original environment
    os.environ.clear()
    os.environ.update(original_env)
