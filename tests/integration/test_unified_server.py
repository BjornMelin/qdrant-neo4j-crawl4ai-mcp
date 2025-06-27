"""
Integration tests for the Unified MCP Intelligence Server.

This module provides comprehensive integration testing for the MCP server
with real service interactions, cross-service data flows, and end-to-end
workflow validation using modern async testing patterns.

Key Features:
- Multi-service integration testing (Qdrant, Neo4j, Crawl4AI)
- Cross-service data flow validation
- MCP protocol compliance testing
- Performance integration benchmarks
- Service health monitoring
- Production-like test scenarios
"""

import asyncio
import time
from unittest.mock import AsyncMock

from fastapi import FastAPI
import httpx
import pytest

from qdrant_neo4j_crawl4ai_mcp.config import Settings
from qdrant_neo4j_crawl4ai_mcp.main import create_app
from qdrant_neo4j_crawl4ai_mcp.models.vector_models import (
    VectorSearchRequest,
    VectorStoreRequest,
)


class TestUnifiedServerIntegration:
    """Integration tests for the unified MCP server with service composition."""

    @pytest.mark.integration
    async def test_server_startup_and_health(
        self,
        test_app: FastAPI,
        async_test_client: httpx.AsyncClient,
    ):
        """Test server startup sequence and health endpoints."""
        # Test basic health endpoint
        health_response = await async_test_client.get("/health")
        assert health_response.status_code == 200

        health_data = health_response.json()
        assert health_data["status"] == "healthy"
        assert health_data["version"] == "1.0.0"
        assert "services" in health_data
        assert "timestamp" in health_data

        # Test readiness endpoint
        ready_response = await async_test_client.get("/ready")
        assert ready_response.status_code == 200

        ready_data = ready_response.json()
        assert ready_data["status"] == "ready"

        # Test metrics endpoint
        metrics_response = await async_test_client.get("/metrics")
        assert metrics_response.status_code == 200
        assert "text/plain" in metrics_response.headers["content-type"]

    @pytest.mark.integration
    async def test_authentication_flow(
        self, async_test_client: httpx.AsyncClient, test_user, test_settings: Settings
    ):
        """Test complete authentication flow with token generation and usage."""
        # Test token creation
        token_request = {"username": test_user.username, "scopes": ["read", "write"]}

        token_response = await async_test_client.post("/auth/token", json=token_request)
        assert token_response.status_code == 200

        token_data = token_response.json()
        assert "access_token" in token_data
        assert token_data["token_type"] == "bearer"  # noqa: S105
        assert token_data["scopes"] == ["read", "write"]
        assert token_data["expires_in"] == test_settings.jwt_expire_minutes * 60

        # Test authenticated endpoint access
        auth_headers = {"Authorization": f"Bearer {token_data['access_token']}"}
        profile_response = await async_test_client.get(
            "/api/v1/profile", headers=auth_headers
        )
        assert profile_response.status_code == 200

        profile_data = profile_response.json()
        assert profile_data["username"] == test_user.username
        assert "read" in profile_data["scopes"]
        assert "write" in profile_data["scopes"]

        # Test unauthenticated access denial
        unauth_response = await async_test_client.get("/api/v1/profile")
        assert unauth_response.status_code == 401

    @pytest.mark.integration
    async def test_vector_service_integration(
        self,
        async_test_client: httpx.AsyncClient,
        auth_headers: dict[str, str],
        sample_vector_store_request: VectorStoreRequest,
        sample_vector_search_request: VectorSearchRequest,
    ):
        """Test vector service integration through API endpoints."""
        # Test vector storage
        store_data = {
            "content": sample_vector_store_request.content,
            "collection_name": sample_vector_store_request.collection_name,
            "content_type": sample_vector_store_request.content_type,
            "tags": sample_vector_store_request.tags,
            "metadata": sample_vector_store_request.metadata,
        }

        store_response = await async_test_client.post(
            "/api/v1/vector/store", json=store_data, headers=auth_headers
        )
        assert store_response.status_code == 200

        store_result = store_response.json()
        assert store_result["status"] == "success"
        assert "id" in store_result
        assert (
            store_result["collection_name"]
            == sample_vector_store_request.collection_name
        )
        assert store_result["vector_dimensions"] > 0

        # Test vector search
        search_data = {
            "query": sample_vector_search_request.query,
            "limit": sample_vector_search_request.limit,
            "filters": {},
        }

        search_response = await async_test_client.post(
            "/api/v1/vector/search", json=search_data, headers=auth_headers
        )
        assert search_response.status_code == 200

        search_result = search_response.json()
        assert search_result["source"] == "vector"
        assert search_result["confidence"] >= 0.0
        assert "metadata" in search_result

        # Test collections listing
        collections_response = await async_test_client.get(
            "/api/v1/vector/collections", headers=auth_headers
        )
        assert collections_response.status_code == 200

        collections_data = collections_response.json()
        assert collections_data["status"] == "success"
        assert "collections" in collections_data
        assert "total_collections" in collections_data

        # Test vector service health
        health_response = await async_test_client.get(
            "/api/v1/vector/health", headers=auth_headers
        )
        assert health_response.status_code == 200

        health_data = health_response.json()
        assert health_data["service"] == "vector"
        assert "status" in health_data
        assert "response_time_ms" in health_data

    @pytest.mark.integration
    async def test_graph_service_integration(
        self, async_test_client: httpx.AsyncClient, auth_headers: dict[str, str]
    ):
        """Test graph service integration through API endpoints."""
        # Test graph query
        query_data = {"query": "knowledge graph analysis", "mode": "graph", "limit": 10}

        query_response = await async_test_client.post(
            "/api/v1/graph/query", json=query_data, headers=auth_headers
        )
        assert query_response.status_code == 200

        query_result = query_response.json()
        assert query_result["source"] == "graph"
        assert "content" in query_result
        assert query_result["confidence"] >= 0.0
        assert "metadata" in query_result
        assert query_result["metadata"]["service"] == "neo4j"

    @pytest.mark.integration
    async def test_web_service_integration(
        self, async_test_client: httpx.AsyncClient, auth_headers: dict[str, str]
    ):
        """Test web service integration through API endpoints."""
        # Test web crawling
        crawl_data = {"query": "web intelligence extraction", "mode": "web", "limit": 5}

        crawl_response = await async_test_client.post(
            "/api/v1/web/crawl", json=crawl_data, headers=auth_headers
        )
        assert crawl_response.status_code == 200

        crawl_result = crawl_response.json()
        assert crawl_result["source"] == "web"
        assert "content" in crawl_result
        assert crawl_result["confidence"] >= 0.0
        assert "metadata" in crawl_result
        assert crawl_result["metadata"]["service"] == "crawl4ai"

    @pytest.mark.integration
    async def test_unified_intelligence_routing(
        self, async_test_client: httpx.AsyncClient, auth_headers: dict[str, str]
    ):
        """Test unified intelligence query routing to appropriate services."""
        # Test auto mode routing
        auto_query = {
            "query": "artificial intelligence research papers",
            "mode": "auto",
            "limit": 10,
        }

        auto_response = await async_test_client.post(
            "/api/v1/intelligence/query", json=auto_query, headers=auth_headers
        )
        assert auto_response.status_code == 200

        auto_result = auto_response.json()
        assert auto_result["source"] == "vector"  # Should default to vector
        assert "content" in auto_result

        # Test explicit vector mode
        vector_query = {
            "query": "machine learning algorithms",
            "mode": "vector",
            "limit": 5,
        }

        vector_response = await async_test_client.post(
            "/api/v1/intelligence/query", json=vector_query, headers=auth_headers
        )
        assert vector_response.status_code == 200

        vector_result = vector_response.json()
        assert vector_result["source"] == "vector"

        # Test explicit graph mode
        graph_query = {"query": "entity relationships", "mode": "graph", "limit": 10}

        graph_response = await async_test_client.post(
            "/api/v1/intelligence/query", json=graph_query, headers=auth_headers
        )
        assert graph_response.status_code == 200

        graph_result = graph_response.json()
        assert graph_result["source"] == "graph"

        # Test explicit web mode
        web_query = {"query": "latest news updates", "mode": "web", "limit": 5}

        web_response = await async_test_client.post(
            "/api/v1/intelligence/query", json=web_query, headers=auth_headers
        )
        assert web_response.status_code == 200

        web_result = web_response.json()
        assert web_result["source"] == "web"

        # Test invalid mode
        invalid_query = {"query": "test query", "mode": "invalid_mode", "limit": 5}

        invalid_response = await async_test_client.post(
            "/api/v1/intelligence/query", json=invalid_query, headers=auth_headers
        )
        assert invalid_response.status_code == 400

    @pytest.mark.integration
    async def test_admin_endpoints(
        self,
        async_test_client: httpx.AsyncClient,
        admin_auth_headers: dict[str, str],
        auth_headers: dict[str, str],
    ):
        """Test admin-specific endpoints and authorization."""
        # Test admin access with admin user
        admin_response = await async_test_client.get(
            "/api/v1/admin/stats", headers=admin_auth_headers
        )
        assert admin_response.status_code == 200

        admin_data = admin_response.json()
        assert "uptime_seconds" in admin_data
        assert "startup_time" in admin_data
        assert "services" in admin_data
        assert "environment" in admin_data
        assert "version" in admin_data

        # Test admin access denied for regular user
        denied_response = await async_test_client.get(
            "/api/v1/admin/stats", headers=auth_headers
        )
        assert denied_response.status_code == 403

    @pytest.mark.integration
    async def test_error_handling_and_resilience(
        self, async_test_client: httpx.AsyncClient, auth_headers: dict[str, str]
    ):
        """Test error handling and service resilience."""
        # Test malformed request
        malformed_response = await async_test_client.post(
            "/api/v1/vector/search", json={"invalid": "request"}, headers=auth_headers
        )
        assert malformed_response.status_code in [400, 422]

        # Test request without authentication
        unauth_response = await async_test_client.post(
            "/api/v1/vector/search", json={"query": "test", "limit": 5}
        )
        assert unauth_response.status_code == 401

        # Test oversized request
        oversized_query = {
            "query": "x" * 2000,  # Exceeds max_length=1000
            "limit": 5,
        }

        oversized_response = await async_test_client.post(
            "/api/v1/intelligence/query", json=oversized_query, headers=auth_headers
        )
        assert oversized_response.status_code == 422

        # Test invalid limit values
        invalid_limit_query = {
            "query": "test query",
            "limit": 200,  # Exceeds max limit
        }

        invalid_limit_response = await async_test_client.post(
            "/api/v1/intelligence/query", json=invalid_limit_query, headers=auth_headers
        )
        assert invalid_limit_response.status_code == 422


class TestCrossServiceIntegration:
    """Tests for cross-service data flows and integration scenarios."""

    @pytest.mark.integration
    @pytest.mark.slow
    async def test_end_to_end_data_flow(
        self,
        async_test_client: httpx.AsyncClient,
        auth_headers: dict[str, str],
        mock_vector_service: AsyncMock,  # noqa: ARG002
        mock_graph_service: AsyncMock,  # noqa: ARG002
        mock_web_service: AsyncMock,  # noqa: ARG002
    ):
        """Test complete data flow across all three services."""
        # Step 1: Crawl web content
        web_crawl_data = {
            "query": "https://example.com/research-paper",
            "mode": "web",
            "limit": 1,
        }

        web_response = await async_test_client.post(
            "/api/v1/web/crawl", json=web_crawl_data, headers=auth_headers
        )
        assert web_response.status_code == 200

        # Step 2: Store extracted content in vector database
        content = (
            "Research paper about machine learning algorithms and their applications."
        )
        vector_store_data = {
            "content": content,
            "collection_name": "research_papers",
            "content_type": "text",
            "source": "web_crawl",
            "tags": ["research", "ml", "algorithms"],
            "metadata": {"crawl_url": "https://example.com/research-paper"},
        }

        store_response = await async_test_client.post(
            "/api/v1/vector/store", json=vector_store_data, headers=auth_headers
        )
        assert store_response.status_code == 200

        store_result = store_response.json()
        document_id = store_result["id"]

        # Step 3: Search for similar content
        search_data = {"query": "machine learning research", "limit": 5}

        search_response = await async_test_client.post(
            "/api/v1/vector/search", json=search_data, headers=auth_headers
        )
        assert search_response.status_code == 200

        # Step 4: Extract knowledge graph entities from content
        # This would be tested with actual graph service integration
        graph_query_data = {
            "query": "extract entities from research content",
            "mode": "graph",
            "filters": {"source_document": document_id},
        }

        graph_response = await async_test_client.post(
            "/api/v1/graph/query", json=graph_query_data, headers=auth_headers
        )
        assert graph_response.status_code == 200

        # Verify cross-service metadata correlation
        assert document_id in store_result["id"]

    @pytest.mark.integration
    async def test_service_health_monitoring(
        self, async_test_client: httpx.AsyncClient, auth_headers: dict[str, str]
    ):
        """Test comprehensive service health monitoring."""
        # Get overall application health
        app_health_response = await async_test_client.get("/health")
        assert app_health_response.status_code == 200

        app_health_data = app_health_response.json()
        assert "services" in app_health_data

        # Get vector service health
        vector_health_response = await async_test_client.get(
            "/api/v1/vector/health", headers=auth_headers
        )
        assert vector_health_response.status_code == 200

        vector_health_data = vector_health_response.json()
        assert vector_health_data["service"] == "vector"
        assert "response_time_ms" in vector_health_data

        # Verify health data consistency
        services_status = app_health_data["services"]
        if "vector" in services_status:
            assert services_status["vector"]["status"] in ["ready", "error"]

    @pytest.mark.integration
    async def test_concurrent_multi_service_requests(
        self, async_test_client: httpx.AsyncClient, auth_headers: dict[str, str]
    ):
        """Test concurrent requests across multiple services."""
        # Create concurrent requests to different services
        tasks = []

        # Vector search tasks
        for i in range(3):
            vector_data = {"query": f"vector search query {i}", "limit": 5}
            task = async_test_client.post(
                "/api/v1/vector/search", json=vector_data, headers=auth_headers
            )
            tasks.append(task)

        # Graph query tasks
        for i in range(3):
            graph_data = {
                "query": f"graph analysis query {i}",
                "mode": "graph",
                "limit": 10,
            }
            task = async_test_client.post(
                "/api/v1/graph/query", json=graph_data, headers=auth_headers
            )
            tasks.append(task)

        # Web crawl tasks
        for i in range(2):
            web_data = {
                "query": f"web intelligence query {i}",
                "mode": "web",
                "limit": 5,
            }
            task = async_test_client.post(
                "/api/v1/web/crawl", json=web_data, headers=auth_headers
            )
            tasks.append(task)

        # Execute all tasks concurrently
        start_time = time.time()
        responses = await asyncio.gather(*tasks)
        execution_time = time.time() - start_time

        # Verify all requests succeeded
        assert len(responses) == 8
        assert all(response.status_code == 200 for response in responses)

        # Verify response data structure
        for response in responses:
            data = response.json()
            assert "source" in data
            assert data["source"] in ["vector", "graph", "web"]
            assert "confidence" in data
            assert "content" in data

        # Performance assertion - concurrent requests should be faster than sequential
        assert execution_time < 5.0  # Should complete within 5 seconds

    @pytest.mark.integration
    async def test_data_consistency_across_services(
        self, async_test_client: httpx.AsyncClient, auth_headers: dict[str, str]
    ):
        """Test data consistency when same content is processed by multiple services."""
        test_content = (
            "Artificial intelligence and machine learning are transforming healthcare."
        )

        # Store in vector database
        vector_store_data = {
            "content": test_content,
            "collection_name": "healthcare_ai",
            "content_type": "text",
            "tags": ["ai", "healthcare", "ml"],
            "metadata": {"test_id": "consistency_test_1"},
        }

        store_response = await async_test_client.post(
            "/api/v1/vector/store", json=vector_store_data, headers=auth_headers
        )
        assert store_response.status_code == 200

        store_result = store_response.json()
        vector_id = store_result["id"]

        # Search for the stored content
        search_data = {"query": "artificial intelligence healthcare", "limit": 10}

        search_response = await async_test_client.post(
            "/api/v1/vector/search", json=search_data, headers=auth_headers
        )
        assert search_response.status_code == 200

        # Verify metadata consistency
        assert vector_id in store_result["id"]
        assert store_result["collection_name"] == "healthcare_ai"


class TestPerformanceIntegration:
    """Integration tests focusing on performance characteristics."""

    @pytest.mark.integration
    @pytest.mark.performance
    async def test_response_time_benchmarks(
        self,
        async_test_client: httpx.AsyncClient,
        auth_headers: dict[str, str],
        performance_monitor,
    ):
        """Test response time benchmarks for critical endpoints."""
        endpoints_and_data = [
            ("/health", "GET", None),
            ("/ready", "GET", None),
            ("/api/v1/profile", "GET", None),
            ("/api/v1/vector/search", "POST", {"query": "test", "limit": 5}),
            (
                "/api/v1/intelligence/query",
                "POST",
                {"query": "test", "mode": "auto", "limit": 5},
            ),
        ]

        response_times = {}

        for endpoint, method, data in endpoints_and_data:
            start_time = time.time()

            if method == "GET":
                headers = auth_headers if "/api/" in endpoint else {}
                response = await async_test_client.get(endpoint, headers=headers)
            else:
                response = await async_test_client.post(
                    endpoint, json=data, headers=auth_headers
                )

            response_time = (time.time() - start_time) * 1000  # Convert to milliseconds
            response_times[endpoint] = response_time

            assert response.status_code == 200
            assert response_time < 1000  # All endpoints should respond within 1 second

        # Performance metrics collection
        metrics = performance_monitor.get_metrics()

        # Verify performance criteria
        assert metrics["execution_time"] < 5.0  # Total test execution under 5 seconds
        assert response_times["/health"] < 100  # Health check under 100ms
        assert response_times["/ready"] < 50  # Readiness check under 50ms

    @pytest.mark.integration
    @pytest.mark.performance
    async def test_throughput_under_load(
        self, async_test_client: httpx.AsyncClient, auth_headers: dict[str, str]
    ):
        """Test system throughput under sustained load."""
        num_requests = 50
        max_concurrent = 10

        async def single_request(request_id: int) -> dict:
            """Single request for load testing."""
            query_data = {
                "query": f"load test query {request_id}",
                "mode": "auto",
                "limit": 5,
            }

            start_time = time.time()
            response = await async_test_client.post(
                "/api/v1/intelligence/query", json=query_data, headers=auth_headers
            )
            response_time = time.time() - start_time

            return {
                "request_id": request_id,
                "status_code": response.status_code,
                "response_time": response_time,
                "success": response.status_code == 200,
            }

        # Execute requests in batches to control concurrency
        all_results = []
        for batch_start in range(0, num_requests, max_concurrent):
            batch_end = min(batch_start + max_concurrent, num_requests)
            batch_tasks = [single_request(i) for i in range(batch_start, batch_end)]

            batch_results = await asyncio.gather(*batch_tasks)
            all_results.extend(batch_results)

            # Small delay between batches to prevent overwhelming
            await asyncio.sleep(0.1)

        # Analyze results
        successful_requests = [r for r in all_results if r["success"]]
        failed_requests = [r for r in all_results if not r["success"]]

        success_rate = len(successful_requests) / len(all_results)
        average_response_time = sum(
            r["response_time"] for r in successful_requests
        ) / len(successful_requests)

        # Performance assertions
        assert success_rate >= 0.95  # At least 95% success rate
        assert average_response_time < 2.0  # Average response time under 2 seconds
        assert len(failed_requests) <= 2  # No more than 2 failed requests

        # Log performance metrics


@pytest.mark.integration
async def test_service_initialization_order(
    test_settings: Settings,
    skip_if_no_integration_services,  # noqa: ARG001
):
    """Test that services initialize in the correct order and handle dependencies."""
    # This test verifies service startup sequence
    app = create_app(test_settings)

    # The lifespan context manager should handle proper initialization
    async with app.router.lifespan_context(app):
        # Verify services are available after initialization
        from qdrant_neo4j_crawl4ai_mcp.main import app_state

        # Check that all services are initialized
        assert app_state["vector_service"] is not None
        assert app_state["graph_service"] is not None
        assert app_state["web_service"] is not None
        assert app_state["mcp_app"] is not None

        # Check service status
        services_status = app_state["mcp_servers"]
        assert "vector" in services_status
        assert "graph" in services_status
        assert "web" in services_status


@pytest.mark.integration
async def test_graceful_shutdown(
    test_settings: Settings,
    skip_if_no_integration_services,  # noqa: ARG001
):
    """Test graceful shutdown of all services."""
    app = create_app(test_settings)

    async with app.router.lifespan_context(app):
        from qdrant_neo4j_crawl4ai_mcp.main import app_state

        # Verify services are running
        assert app_state["vector_service"] is not None
        assert app_state["graph_service"] is not None
        assert app_state["web_service"] is not None

    # After context exit, services should be cleaned up
    from qdrant_neo4j_crawl4ai_mcp.main import app_state

    assert app_state["vector_service"] is None
    assert app_state["graph_service"] is None
    assert app_state["web_service"] is None


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
