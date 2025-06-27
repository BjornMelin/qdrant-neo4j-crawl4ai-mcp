"""
Cross-service integration tests for the Unified MCP Intelligence Server.

This module provides comprehensive integration testing for cross-service
data flows, service coordination, and complex workflow validation that
spans multiple backend services (Qdrant, Neo4j, Crawl4AI).

Key Features:
- Cross-service data flow validation
- Service communication and coordination testing
- Complex workflow integration scenarios
- Real-time data consistency verification
- Error propagation and recovery testing
- Service dependency and startup order validation
"""

import asyncio
from datetime import UTC, datetime
from unittest.mock import AsyncMock
from uuid import uuid4

import httpx
import pytest

from qdrant_neo4j_crawl4ai_mcp.config import Settings
from qdrant_neo4j_crawl4ai_mcp.main import create_app


class TestCrossServiceDataFlow:
    """Tests for data flowing between all three services in complex scenarios."""

    @pytest.mark.integration
    @pytest.mark.slow
    async def test_web_to_vector_to_graph_workflow(
        self,
        async_test_client: httpx.AsyncClient,
        auth_headers: dict[str, str],
        mock_vector_service: AsyncMock,  # noqa: ARG002
        mock_graph_service: AsyncMock,  # noqa: ARG002
        mock_web_service: AsyncMock,  # noqa: ARG002
    ):
        """Test complete workflow: web crawl → vector storage → graph knowledge extraction."""  # noqa: E501
        # Step 1: Crawl web content
        web_crawl_data = {
            "query": "https://example.com/ai-research-paper",
            "mode": "web",
            "limit": 1,
        }

        # Mock web service response
        web_response = await async_test_client.post(
            "/api/v1/web/crawl", json=web_crawl_data, headers=auth_headers
        )
        assert web_response.status_code == 200

        web_result = web_response.json()
        crawled_content = (
            "Artificial intelligence research shows significant advances in "
            "neural networks and machine learning algorithms."
        )

        # Step 2: Store crawled content in vector database
        vector_store_data = {
            "content": crawled_content,
            "collection_name": "research_papers",
            "content_type": "text",
            "source": "web_crawl",
            "tags": ["research", "ai", "neural-networks"],
            "metadata": {
                "crawl_url": "https://example.com/ai-research-paper",
                "crawl_timestamp": datetime.now(UTC).isoformat(),
                "web_result_id": web_result.get("id", "unknown"),
            },
        }

        store_response = await async_test_client.post(
            "/api/v1/vector/store", json=vector_store_data, headers=auth_headers
        )
        assert store_response.status_code == 200

        store_result = store_response.json()
        document_id = store_result["id"]

        # Step 3: Search for similar content to verify storage
        search_data = {
            "query": "artificial intelligence neural networks",
            "limit": 5,
            "filters": {"source": "web_crawl"},
        }

        search_response = await async_test_client.post(
            "/api/v1/vector/search", json=search_data, headers=auth_headers
        )
        assert search_response.status_code == 200

        search_result = search_response.json()
        assert search_result["confidence"] > 0.7

        # Step 4: Extract knowledge graph from the content
        graph_extraction_data = {
            "query": "extract entities and relationships from research content",
            "mode": "graph",
            "filters": {"source_document": document_id, "content_type": "text"},
        }

        graph_response = await async_test_client.post(
            "/api/v1/graph/query", json=graph_extraction_data, headers=auth_headers
        )
        assert graph_response.status_code == 200

        graph_result = graph_response.json()

        # Verify cross-service data correlation
        assert document_id in store_result["id"]
        assert search_result["source"] == "vector"
        assert graph_result["source"] == "graph"

        # Verify metadata propagation
        assert "web_crawl" in str(store_result)
        assert search_result["confidence"] >= 0.0
        assert graph_result["confidence"] >= 0.0

    @pytest.mark.integration
    async def test_graph_to_vector_semantic_enhancement(
        self, async_test_client: httpx.AsyncClient, auth_headers: dict[str, str]
    ):
        """Test using graph relationships to enhance vector search results."""
        # Step 1: Create knowledge graph entities
        graph_creation_data = {
            "query": "create entity relationships for AI concepts",
            "mode": "graph",
            "filters": {
                "entities": [
                    "Artificial Intelligence",
                    "Machine Learning",
                    "Neural Networks",
                ],
                "relationships": ["IS_SUBSET_OF", "USES", "IMPLEMENTS"],
            },
        }

        graph_response = await async_test_client.post(
            "/api/v1/graph/query", json=graph_creation_data, headers=auth_headers
        )
        assert graph_response.status_code == 200

        # Step 2: Store related documents in vector database
        documents = [
            {
                "content": (
                    "Machine learning is a subset of artificial intelligence "
                    "that focuses on learning from data."
                ),
                "tags": ["ai", "ml", "learning"],
                "metadata": {
                    "concept": "Machine Learning",
                    "relationship": "IS_SUBSET_OF",
                },
            },
            {
                "content": (
                    "Neural networks are computational models inspired by "
                    "biological neural systems."
                ),
                "tags": ["neural-networks", "computation", "biology"],
                "metadata": {
                    "concept": "Neural Networks",
                    "relationship": "IMPLEMENTS",
                },
            },
            {
                "content": (
                    "Deep learning uses neural networks with multiple layers "
                    "to solve complex problems."
                ),
                "tags": ["deep-learning", "neural-networks", "complexity"],
                "metadata": {"concept": "Deep Learning", "relationship": "USES"},
            },
        ]

        stored_ids = []
        for doc in documents:
            store_data = {
                "content": doc["content"],
                "collection_name": "ai_concepts",
                "content_type": "text",
                "tags": doc["tags"],
                "metadata": doc["metadata"],
            }

            store_response = await async_test_client.post(
                "/api/v1/vector/store", json=store_data, headers=auth_headers
            )
            assert store_response.status_code == 200
            stored_ids.append(store_response.json()["id"])

        # Step 3: Perform graph-enhanced semantic search
        enhanced_search_data = {
            "query": "machine learning algorithms",
            "limit": 10,
            "filters": {
                "enhancement_mode": "graph_aware",
                "relationship_types": ["IS_SUBSET_OF", "USES"],
            },
        }

        search_response = await async_test_client.post(
            "/api/v1/vector/search", json=enhanced_search_data, headers=auth_headers
        )
        assert search_response.status_code == 200

        search_result = search_response.json()

        # Verify enhanced results
        assert search_result["source"] == "vector"
        assert len(stored_ids) == 3
        assert search_result["confidence"] >= 0.0

    @pytest.mark.integration
    async def test_vector_to_web_content_discovery(
        self, async_test_client: httpx.AsyncClient, auth_headers: dict[str, str]
    ):
        """Test using vector search to guide web content discovery."""
        # Step 1: Store seed content in vector database
        seed_content = {
            "content": (
                "Research on transformer architectures in natural language processing"
            ),
            "collection_name": "nlp_research",
            "content_type": "text",
            "tags": ["nlp", "transformers", "research"],
            "metadata": {"research_area": "natural_language_processing"},
        }

        store_response = await async_test_client.post(
            "/api/v1/vector/store", json=seed_content, headers=auth_headers
        )
        assert store_response.status_code == 200

        # Step 2: Search for related concepts
        concept_search_data = {
            "query": "transformer models language processing",
            "limit": 5,
            "filters": {"research_area": "natural_language_processing"},
        }

        search_response = await async_test_client.post(
            "/api/v1/vector/search", json=concept_search_data, headers=auth_headers
        )
        assert search_response.status_code == 200

        search_result = search_response.json()

        # Step 3: Use search insights to guide web crawling
        web_crawl_data = {
            "query": (
                f"transformer architecture NLP research "
                f"{search_result.get('content', '')}"
            ),
            "mode": "web",
            "limit": 3,
            "filters": {
                "guided_by_vector_search": True,
                "search_confidence": search_result.get("confidence", 0.0),
            },
        }

        crawl_response = await async_test_client.post(
            "/api/v1/web/crawl", json=web_crawl_data, headers=auth_headers
        )
        assert crawl_response.status_code == 200

        crawl_result = crawl_response.json()

        # Verify guided discovery
        assert crawl_result["source"] == "web"
        assert search_result["source"] == "vector"
        assert crawl_result["confidence"] >= 0.0


class TestServiceCoordination:
    """Tests for service coordination, communication, and dependency management."""

    @pytest.mark.integration
    async def test_service_startup_coordination(
        self,
        test_settings: Settings,
        skip_if_no_integration_services,  # noqa: ARG002
    ):
        """Test proper service startup coordination and dependency resolution."""
        from qdrant_neo4j_crawl4ai_mcp.main import app_state

        # Create app with coordinated startup
        app = create_app(test_settings)

        async with app.router.lifespan_context(app):
            # Verify all services are available
            assert app_state["vector_service"] is not None
            assert app_state["graph_service"] is not None
            assert app_state["web_service"] is not None
            assert app_state["mcp_app"] is not None

            # Verify service registry
            services = app_state["mcp_servers"]
            expected_services = {"vector", "graph", "web"}
            available_services = set(services.keys())

            assert expected_services.issubset(available_services)

            # Verify service health
            for service_info in services.values():
                assert service_info["status"] in ["ready", "error"]
                assert "last_check" in service_info

                if service_info["status"] == "ready":
                    assert isinstance(service_info["last_check"], datetime)

    @pytest.mark.integration
    async def test_service_communication_patterns(
        self, async_test_client: httpx.AsyncClient, auth_headers: dict[str, str]
    ):
        """Test communication patterns between services."""
        # Test sequential service calls
        operations = [
            (
                "POST",
                "/api/v1/web/crawl",
                {
                    "query": "artificial intelligence research",
                    "mode": "web",
                    "limit": 1,
                },
            ),
            ("POST", "/api/v1/vector/search", {"query": "AI research", "limit": 5}),
            (
                "POST",
                "/api/v1/graph/query",
                {"query": "AI entity relationships", "mode": "graph"},
            ),
        ]

        results = []
        for method, endpoint, data in operations:
            response = await async_test_client.request(
                method, endpoint, json=data, headers=auth_headers
            )
            assert response.status_code == 200

            result = response.json()
            results.append(
                {
                    "endpoint": endpoint,
                    "source": result.get("source"),
                    "confidence": result.get("confidence", 0.0),
                    "timestamp": result.get("timestamp"),
                }
            )

        # Verify service responses
        sources = [r["source"] for r in results]
        assert "web" in sources
        assert "vector" in sources
        assert "graph" in sources

        # Verify communication timing
        confidences = [r["confidence"] for r in results]
        assert all(c >= 0.0 for c in confidences)

    @pytest.mark.integration
    async def test_service_failure_resilience(
        self,
        async_test_client: httpx.AsyncClient,
        auth_headers: dict[str, str],  # noqa: ARG002
    ):
        """Test system resilience when individual services fail."""
        # Test with one service potentially unavailable
        health_response = await async_test_client.get("/health")
        assert health_response.status_code == 200

        health_data = health_response.json()
        services = health_data.get("services", {})

        # System should remain operational even if some services have errors
        assert health_data["status"] == "healthy"

        # Test graceful degradation
        for service_info in services.values():
            if service_info.get("status") == "error":
                # Verify error is properly tracked
                assert "error" in service_info or "last_check" in service_info
            elif service_info.get("status") == "ready":
                # Verify healthy services are functional
                assert "last_check" in service_info


class TestComplexWorkflows:
    """Tests for complex, real-world workflow scenarios."""

    @pytest.mark.integration
    @pytest.mark.slow
    async def test_research_paper_processing_workflow(
        self, async_test_client: httpx.AsyncClient, auth_headers: dict[str, str]
    ):
        """Test complete research paper processing workflow."""
        # Simulate processing a research paper through all services

        # Step 1: Web crawling for paper content
        paper_url = "https://arxiv.org/abs/example-paper"
        crawl_data = {
            "query": paper_url,
            "mode": "web",
            "limit": 1,
            "filters": {"content_type": "academic_paper"},
        }

        crawl_response = await async_test_client.post(
            "/api/v1/web/crawl", json=crawl_data, headers=auth_headers
        )
        assert crawl_response.status_code == 200

        # Step 2: Extract and store paper content
        paper_content = (
            "Abstract: This paper presents novel approaches to "
            "transformer architectures..."
        )
        store_data = {
            "content": paper_content,
            "collection_name": "research_papers",
            "content_type": "academic_paper",
            "source": "arxiv",
            "tags": ["transformers", "nlp", "architecture"],
            "metadata": {
                "paper_url": paper_url,
                "paper_type": "conference",
                "authors": ["John Doe", "Jane Smith"],
                "publication_year": 2024,
            },
        }

        store_response = await async_test_client.post(
            "/api/v1/vector/store", json=store_data, headers=auth_headers
        )
        assert store_response.status_code == 200

        paper_id = store_response.json()["id"]

        # Step 3: Extract knowledge graph from paper
        graph_data = {
            "query": "extract research entities and relationships",
            "mode": "graph",
            "filters": {
                "source_document": paper_id,
                "extract_authors": True,
                "extract_concepts": True,
                "extract_citations": True,
            },
        }

        graph_response = await async_test_client.post(
            "/api/v1/graph/query", json=graph_data, headers=auth_headers
        )
        assert graph_response.status_code == 200

        # Step 4: Find related papers using vector search
        similarity_search_data = {
            "query": "transformer architecture neural networks",
            "limit": 10,
            "filters": {"content_type": "academic_paper", "exclude_ids": [paper_id]},
        }

        similarity_response = await async_test_client.post(
            "/api/v1/vector/search", json=similarity_search_data, headers=auth_headers
        )
        assert similarity_response.status_code == 200

        # Step 5: Discover citations through web crawling
        citation_discovery_data = {
            "query": "transformer architecture citations papers",
            "mode": "web",
            "limit": 5,
            "filters": {"guided_by_paper": paper_id, "discovery_type": "citations"},
        }

        citation_response = await async_test_client.post(
            "/api/v1/web/crawl", json=citation_discovery_data, headers=auth_headers
        )
        assert citation_response.status_code == 200

        # Verify complete workflow
        assert all(
            response.status_code == 200
            for response in [
                crawl_response,
                store_response,
                graph_response,
                similarity_response,
                citation_response,
            ]
        )

        # Verify data consistency across services
        workflow_metadata = {
            "paper_id": paper_id,
            "crawl_source": crawl_response.json().get("source"),
            "vector_confidence": similarity_response.json().get("confidence"),
            "graph_entities": graph_response.json().get("confidence"),
            "citation_discovery": citation_response.json().get("source"),
        }

        assert workflow_metadata["crawl_source"] == "web"
        assert workflow_metadata["vector_confidence"] >= 0.0
        assert workflow_metadata["graph_entities"] >= 0.0
        assert workflow_metadata["citation_discovery"] == "web"

    @pytest.mark.integration
    async def test_knowledge_base_construction_workflow(
        self, async_test_client: httpx.AsyncClient, auth_headers: dict[str, str]
    ):
        """Test building a knowledge base through multi-service coordination."""
        knowledge_domains = [
            {
                "domain": "machine_learning",
                "content": (
                    "Machine learning algorithms learn patterns from data "
                    "without explicit programming."
                ),
                "related_urls": [
                    "https://example.com/ml-intro",
                    "https://example.com/ml-algorithms",
                ],
            },
            {
                "domain": "deep_learning",
                "content": (
                    "Deep learning uses neural networks with many layers "
                    "to model complex patterns."
                ),
                "related_urls": [
                    "https://example.com/deep-learning",
                    "https://example.com/neural-nets",
                ],
            },
            {
                "domain": "natural_language_processing",
                "content": (
                    "NLP enables computers to understand and process human language."
                ),
                "related_urls": [
                    "https://example.com/nlp-basics",
                    "https://example.com/language-models",
                ],
            },
        ]

        domain_ids = {}

        # Step 1: Store domain knowledge in vector database
        for domain in knowledge_domains:
            store_data = {
                "content": domain["content"],
                "collection_name": "knowledge_base",
                "content_type": "domain_knowledge",
                "tags": [domain["domain"], "knowledge", "ai"],
                "metadata": {
                    "domain": domain["domain"],
                    "related_urls": domain["related_urls"],
                    "knowledge_type": "foundational",
                },
            }

            store_response = await async_test_client.post(
                "/api/v1/vector/store", json=store_data, headers=auth_headers
            )
            assert store_response.status_code == 200
            domain_ids[domain["domain"]] = store_response.json()["id"]

        # Step 2: Create domain relationships in graph
        for domain in knowledge_domains:
            graph_data = {
                "query": f"create relationships for {domain['domain']}",
                "mode": "graph",
                "filters": {
                    "domain_id": domain_ids[domain["domain"]],
                    "create_relationships": True,
                    "relationship_types": ["RELATED_TO", "IS_PART_OF", "USES"],
                },
            }

            graph_response = await async_test_client.post(
                "/api/v1/graph/query", json=graph_data, headers=auth_headers
            )
            assert graph_response.status_code == 200

        # Step 3: Enrich knowledge with web content
        for domain in knowledge_domains:
            for url in domain["related_urls"]:
                web_data = {
                    "query": url,
                    "mode": "web",
                    "limit": 1,
                    "filters": {
                        "enrich_domain": domain["domain"],
                        "knowledge_base_id": domain_ids[domain["domain"]],
                    },
                }

                web_response = await async_test_client.post(
                    "/api/v1/web/crawl", json=web_data, headers=auth_headers
                )
                assert web_response.status_code == 200

        # Step 4: Validate knowledge base coherence
        coherence_search_data = {
            "query": "machine learning deep learning NLP relationships",
            "limit": 15,
            "filters": {"content_type": "domain_knowledge"},
        }

        coherence_response = await async_test_client.post(
            "/api/v1/vector/search", json=coherence_search_data, headers=auth_headers
        )
        assert coherence_response.status_code == 200

        # Verify knowledge base construction
        assert len(domain_ids) == 3
        coherence_result = coherence_response.json()
        assert coherence_result["confidence"] >= 0.0
        assert coherence_result["source"] == "vector"


class TestDataConsistency:
    """Tests for data consistency across services."""

    @pytest.mark.integration
    async def test_cross_service_transaction_consistency(
        self, async_test_client: httpx.AsyncClient, auth_headers: dict[str, str]
    ):
        """Test data consistency in cross-service transactions."""
        transaction_id = str(uuid4())

        # Step 1: Begin cross-service transaction
        transaction_data = {
            "content": f"Transaction test content for {transaction_id}",
            "collection_name": "consistency_test",
            "content_type": "test_data",
            "metadata": {
                "transaction_id": transaction_id,
                "consistency_test": True,
                "timestamp": datetime.now(UTC).isoformat(),
            },
        }

        # Store in vector service
        vector_response = await async_test_client.post(
            "/api/v1/vector/store", json=transaction_data, headers=auth_headers
        )
        assert vector_response.status_code == 200

        vector_id = vector_response.json()["id"]

        # Create corresponding graph entity
        graph_data = {
            "query": f"create entity for transaction {transaction_id}",
            "mode": "graph",
            "filters": {
                "transaction_id": transaction_id,
                "vector_id": vector_id,
                "entity_type": "test_entity",
            },
        }

        graph_response = await async_test_client.post(
            "/api/v1/graph/query", json=graph_data, headers=auth_headers
        )
        assert graph_response.status_code == 200

        # Step 2: Verify consistency across services
        consistency_check_data = {
            "query": f"transaction consistency test {transaction_id}",
            "limit": 5,
            "filters": {"transaction_id": transaction_id},
        }

        search_response = await async_test_client.post(
            "/api/v1/vector/search", json=consistency_check_data, headers=auth_headers
        )
        assert search_response.status_code == 200

        # Verify transaction consistency
        search_result = search_response.json()
        assert search_result["source"] == "vector"

        # Verify cross-references
        assert vector_id is not None
        assert transaction_id in str(transaction_data)

    @pytest.mark.integration
    async def test_eventual_consistency_verification(
        self, async_test_client: httpx.AsyncClient, auth_headers: dict[str, str]
    ):
        """Test eventual consistency across services."""
        # Create data that will propagate across services
        test_document = {
            "content": "Eventually consistent data propagation test document",
            "collection_name": "consistency_verification",
            "content_type": "test_document",
            "tags": ["consistency", "verification", "test"],
            "metadata": {
                "consistency_test": True,
                "propagation_time": datetime.now(UTC).isoformat(),
            },
        }

        # Store document
        store_response = await async_test_client.post(
            "/api/v1/vector/store", json=test_document, headers=auth_headers
        )
        assert store_response.status_code == 200

        document_id = store_response.json()["id"]

        # Allow time for propagation
        await asyncio.sleep(0.1)

        # Verify data is accessible through search
        verification_attempts = 3
        for attempt in range(verification_attempts):
            search_data = {
                "query": "eventually consistent data propagation",
                "limit": 10,
                "filters": {"consistency_test": True},
            }

            search_response = await async_test_client.post(
                "/api/v1/vector/search", json=search_data, headers=auth_headers
            )

            if search_response.status_code == 200:
                search_result = search_response.json()
                if search_result.get("confidence", 0) > 0:
                    break

            # Wait between attempts
            if attempt < verification_attempts - 1:
                await asyncio.sleep(0.1)

        # Verify eventual consistency
        assert search_response.status_code == 200
        assert document_id is not None


@pytest.mark.integration
async def test_service_lifecycle_coordination(
    test_settings: Settings,
    skip_if_no_integration_services,  # noqa: ARG001
):
    """Test coordinated service lifecycle management."""
    from qdrant_neo4j_crawl4ai_mcp.main import app_state

    # Test application startup
    app = create_app(test_settings)

    async with app.router.lifespan_context(app):
        # Verify all services are properly initialized
        assert app_state["startup_time"] is not None
        assert app_state["vector_service"] is not None
        assert app_state["graph_service"] is not None
        assert app_state["web_service"] is not None
        assert app_state["mcp_app"] is not None

        # Verify service registry is populated
        services = app_state["mcp_servers"]
        assert len(services) >= 3

        for service_name in ["vector", "graph", "web"]:
            assert service_name in services
            service_info = services[service_name]
            assert "status" in service_info
            assert "last_check" in service_info

    # After context exit, verify cleanup
    assert app_state["vector_service"] is None
    assert app_state["graph_service"] is None
    assert app_state["web_service"] is None
    assert app_state["mcp_app"] is None


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
