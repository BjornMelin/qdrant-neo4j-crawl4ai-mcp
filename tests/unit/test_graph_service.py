"""
Unit tests for Neo4j graph service.

Comprehensive test suite covering graph operations, memory management,
GraphRAG integration, and error handling scenarios.
"""

import asyncio
from datetime import UTC, datetime
from unittest.mock import AsyncMock, Mock, patch

from neo4j.exceptions import AuthError, ServiceUnavailable
import pytest

from qdrant_neo4j_crawl4ai_mcp.models.graph_models import (
    CypherQuery,
    CypherResult,
    GraphAnalysisRequest,
    GraphHealthCheck,
    GraphNode,
    GraphRelationship,
    GraphSearchRequest,
    KnowledgeExtractionRequest,
    MemoryNode,
    Neo4jServiceConfig,
    NodeType,
    RelationshipType,
)
from qdrant_neo4j_crawl4ai_mcp.services.graph_service import GraphService
from qdrant_neo4j_crawl4ai_mcp.services.neo4j_client import Neo4jClient


@pytest.fixture
def mock_config():
    """Create a mock Neo4j service configuration."""
    return Neo4jServiceConfig(
        uri="bolt://localhost:7687",
        username="neo4j",
        password="password",
        database="test_db",
        enable_graphrag=True,
        openai_api_key="test-api-key",
        embedding_model="text-embedding-3-large",
        llm_model="gpt-4o",
    )


@pytest.fixture
def mock_neo4j_client():
    """Create a mock Neo4j client."""
    client = AsyncMock(spec=Neo4jClient)
    client.initialize = AsyncMock()
    client.shutdown = AsyncMock()
    client.execute_query = AsyncMock()
    client.execute_batch_queries = AsyncMock()
    client.health_check = AsyncMock()
    return client


@pytest.fixture
def mock_openai_client():
    """Create a mock OpenAI client."""
    client = AsyncMock()

    # Mock chat completion
    mock_completion = AsyncMock()
    mock_completion.choices = [
        Mock(message=Mock(content='{"entities": [], "relationships": []}'))
    ]
    client.chat.completions.create = AsyncMock(return_value=mock_completion)

    # Mock embeddings
    mock_embedding = AsyncMock()
    mock_embedding.data = [Mock(embedding=[0.1] * 1536)]
    client.embeddings.create = AsyncMock(return_value=mock_embedding)

    return client


@pytest.fixture
async def graph_service(mock_config, mock_neo4j_client, mock_openai_client):
    """Create a graph service instance with mocked dependencies."""
    with (
        patch(
            "qdrant_neo4j_crawl4ai_mcp.services.graph_service.Neo4jClient",
            return_value=mock_neo4j_client,
        ),
        patch(
            "qdrant_neo4j_crawl4ai_mcp.services.graph_service.AsyncOpenAI",
            return_value=mock_openai_client,
        ),
    ):
        service = GraphService(mock_config)
        # Replace the client with our mock
        service.client = mock_neo4j_client
        service._openai_client = mock_openai_client  # noqa: SLF001
        await service.initialize()
        yield service
        await service.shutdown()


class TestGraphService:
    """Test cases for GraphService."""

    async def test_initialization(self, mock_config, mock_neo4j_client):
        """Test service initialization."""
        with patch(
            "qdrant_neo4j_crawl4ai_mcp.services.graph_service.Neo4jClient",
            return_value=mock_neo4j_client,
        ):
            service = GraphService(mock_config)
            await service.initialize()

            mock_neo4j_client.initialize.assert_called_once()
            assert service.config == mock_config
            assert service.client == mock_neo4j_client
            assert service._openai_client is not None  # noqa: SLF001

    async def test_shutdown(self, graph_service, mock_neo4j_client):
        """Test service shutdown."""
        await graph_service.shutdown()

        mock_neo4j_client.shutdown.assert_called_once()
        assert len(graph_service._memory_cache) == 0  # noqa: SLF001

    async def test_health_check(self, graph_service, mock_neo4j_client):
        """Test health check delegation."""
        expected_health = GraphHealthCheck(
            status="healthy",
            database_connected=True,
            response_time_ms=10.5,
            total_nodes=100,
            total_relationships=50,
        )

        mock_neo4j_client.health_check.return_value = expected_health

        result = await graph_service.health_check()

        assert result == expected_health
        mock_neo4j_client.health_check.assert_called_once()

    async def test_create_memory_node(self, graph_service, mock_neo4j_client):
        """Test memory node creation."""
        # Mock successful Cypher execution
        mock_result = CypherResult(
            success=True,
            records=[{"id": "memory_123", "created_at": datetime.now(UTC).isoformat()}],
            execution_time_ms=15.5,
            records_available=1,
        )
        mock_neo4j_client.execute_query.return_value = mock_result

        result = await graph_service.create_memory_node(
            name="Test Subject",
            memory_type="person",
            observations=["friendly", "knowledgeable"],
            context="met at conference",
        )

        assert isinstance(result, MemoryNode)
        assert result.name == "Test Subject"
        assert result.memory_type == "person"
        assert result.observations == ["friendly", "knowledgeable"]
        assert result.context == "met at conference"

        # Verify Cypher query was executed
        mock_neo4j_client.execute_query.assert_called()
        query_call = mock_neo4j_client.execute_query.call_args[0][0]
        assert isinstance(query_call, CypherQuery)
        assert "CREATE" in query_call.query
        assert "Memory" in query_call.query

    async def test_extract_knowledge_from_text(
        self, graph_service, mock_openai_client, mock_neo4j_client
    ):
        """Test AI-powered knowledge extraction."""
        # Mock OpenAI response
        mock_openai_client.chat.completions.create.return_value.choices[
            0
        ].message.content = """
        {
            "entities": [
                {
                    "name": "John Doe",
                    "type": "Person",
                    "description": "Software engineer",
                    "confidence": 0.9
                },
                {
                    "name": "Python",
                    "type": "Concept",
                    "description": "Programming language",
                    "confidence": 0.8
                }
            ],
            "relationships": [
                {
                    "source": "John Doe",
                    "target": "Python",
                    "type": "KNOWS",
                    "confidence": 0.85
                }
            ]
        }
        """

        # Mock Neo4j operations
        mock_neo4j_client.execute_batch_queries.return_value = [
            CypherResult(
                success=True, records=[], execution_time_ms=10, records_available=0
            ),
            CypherResult(
                success=True, records=[], execution_time_ms=5, records_available=0
            ),
        ]

        request = KnowledgeExtractionRequest(
            text="John Doe is a software engineer who knows Python.",
            extract_entities=True,
            extract_relationships=True,
            source_type="text",
        )

        result = await graph_service.extract_knowledge_from_text(request)

        assert result.total_entities == 2
        assert result.total_relationships == 1
        assert result.average_confidence > 0.8
        assert len(result.extracted_nodes) == 2
        assert len(result.extracted_relationships) == 1

        # Verify OpenAI was called
        mock_openai_client.chat.completions.create.assert_called()

        # Verify nodes were created
        assert any(node.name == "John Doe" for node in result.extracted_nodes)
        assert any(node.name == "Python" for node in result.extracted_nodes)

    async def test_extract_knowledge_without_openai(
        self, mock_config, mock_neo4j_client
    ):
        """Test knowledge extraction when OpenAI is disabled."""
        # Disable GraphRAG
        mock_config.enable_graphrag = False
        mock_config.openai_api_key = None

        with patch(
            "qdrant_neo4j_crawl4ai_mcp.services.graph_service.Neo4jClient",
            return_value=mock_neo4j_client,
        ):
            service = GraphService(mock_config)
            service.client = mock_neo4j_client
            await service.initialize()

            request = KnowledgeExtractionRequest(
                text="Some text to extract knowledge from"
            )

            with pytest.raises(RuntimeError, match="GraphRAG is not enabled"):
                await service.extract_knowledge_from_text(request)

    async def test_search_graph(self, graph_service, mock_neo4j_client):
        """Test graph search functionality."""
        # Mock search results
        mock_result = CypherResult(
            success=True,
            records=[
                {
                    "node": {
                        "id": "node_1",
                        "name": "Test Node",
                        "node_type": "Entity",
                        "confidence_score": 0.9,
                    },
                    "score": 0.85,
                }
            ],
            execution_time_ms=25.0,
            records_available=1,
        )
        mock_neo4j_client.execute_query.return_value = mock_result

        request = GraphSearchRequest(
            query="test search", node_types=[NodeType.ENTITY], max_depth=2, limit=10
        )

        result = await graph_service.search_graph(request)

        assert result.total_results >= 0
        assert result.search_time_ms > 0
        assert result.query_type in ["text_search", "semantic_search"]

        # Verify search query was executed
        mock_neo4j_client.execute_query.assert_called()

    async def test_analyze_graph_structure(self, graph_service, mock_neo4j_client):
        """Test graph structure analysis."""
        # Mock analysis queries
        mock_results = [
            CypherResult(
                success=True,
                records=[{"count": 100}],
                execution_time_ms=10,
                records_available=1,
            ),
            CypherResult(
                success=True,
                records=[{"count": 50}],
                execution_time_ms=8,
                records_available=1,
            ),
            CypherResult(
                success=True,
                records=[{"density": 0.25}],
                execution_time_ms=15,
                records_available=1,
            ),
        ]
        mock_neo4j_client.execute_batch_queries.return_value = mock_results

        request = GraphAnalysisRequest(
            analysis_type="centrality", depth=3, include_metrics=True
        )

        result = await graph_service.analyze_graph_structure(request)

        assert result.analysis_type == "centrality"
        assert result.node_count >= 0
        assert result.relationship_count >= 0
        assert result.density >= 0.0
        assert result.analysis_time_ms > 0

        # Verify analysis queries were executed
        mock_neo4j_client.execute_batch_queries.assert_called()

    async def test_execute_cypher_query(self, graph_service, mock_neo4j_client):
        """Test direct Cypher query execution."""
        expected_result = CypherResult(
            success=True,
            records=[{"name": "Test", "count": 5}],
            execution_time_ms=12.3,
            records_available=1,
        )
        mock_neo4j_client.execute_query.return_value = expected_result

        query = CypherQuery(
            query="MATCH (n:Test) RETURN n.name as name, count(n) as count",
            parameters={"limit": 10},
            read_only=True,
        )

        result = await graph_service.execute_cypher_query(query)

        assert result == expected_result
        mock_neo4j_client.execute_query.assert_called_with(query)

    async def test_memory_caching(self, graph_service):
        """Test memory node caching functionality."""
        # Create a memory node
        memory_node = MemoryNode(
            id="test_memory_123",
            name="Test Memory",
            memory_type="test",
            observations=["test observation"],
        )

        # Cache the memory node
        graph_service._memory_cache["test_memory_123"] = memory_node  # noqa: SLF001

        # Verify it's cached
        assert "test_memory_123" in graph_service._memory_cache  # noqa: SLF001
        cached_node = graph_service._memory_cache["test_memory_123"]  # noqa: SLF001
        assert cached_node.name == "Test Memory"
        assert cached_node.memory_type == "test"

    async def test_create_node(self, graph_service, mock_neo4j_client):
        """Test individual node creation."""
        # Mock successful node creation
        mock_result = CypherResult(
            success=True,
            records=[{"id": "node_123", "created_at": datetime.now(UTC).isoformat()}],
            execution_time_ms=8.5,
            records_available=1,
        )
        mock_neo4j_client.execute_query.return_value = mock_result

        node = GraphNode(
            name="Test Entity",
            node_type=NodeType.ENTITY,
            description="A test entity",
            confidence_score=0.9,
        )

        result = await graph_service.create_node(node)

        assert isinstance(result, GraphNode)
        assert result.name == "Test Entity"
        assert result.node_type == NodeType.ENTITY

        # Verify Cypher execution
        mock_neo4j_client.execute_query.assert_called()
        query_call = mock_neo4j_client.execute_query.call_args[0][0]
        assert "CREATE" in query_call.query

    async def test_create_relationship(self, graph_service, mock_neo4j_client):
        """Test relationship creation."""
        # Mock successful relationship creation
        mock_result = CypherResult(
            success=True,
            records=[{"id": "rel_123", "created_at": datetime.now(UTC).isoformat()}],
            execution_time_ms=12.0,
            records_available=1,
        )
        mock_neo4j_client.execute_query.return_value = mock_result

        relationship = GraphRelationship(
            source_id="node_1",
            target_id="node_2",
            relationship_type=RelationshipType.KNOWS,
            weight=0.8,
            confidence=0.9,
        )

        result = await graph_service.create_relationship(relationship)

        assert isinstance(result, GraphRelationship)
        assert result.source_id == "node_1"
        assert result.target_id == "node_2"
        assert result.relationship_type == RelationshipType.KNOWS

        # Verify Cypher execution
        mock_neo4j_client.execute_query.assert_called()

    async def test_error_handling_database_unavailable(
        self, graph_service, mock_neo4j_client
    ):
        """Test error handling when database is unavailable."""
        mock_neo4j_client.execute_query.side_effect = ServiceUnavailable(
            "Database unavailable"
        )

        query = CypherQuery(query="MATCH (n) RETURN count(n)", read_only=True)

        result = await graph_service.execute_cypher_query(query)

        assert not result.success
        assert "Database unavailable" in result.error
        assert result.error_code == "ServiceUnavailable"

    async def test_error_handling_authentication_failed(
        self, graph_service, mock_neo4j_client
    ):
        """Test error handling for authentication failures."""
        mock_neo4j_client.execute_query.side_effect = AuthError("Authentication failed")

        query = CypherQuery(query="MATCH (n) RETURN count(n)", read_only=True)

        result = await graph_service.execute_cypher_query(query)

        assert not result.success
        assert "Authentication failed" in result.error
        assert result.error_code == "AuthError"

    async def test_knowledge_extraction_json_parsing_error(
        self,
        graph_service,
        mock_openai_client,
        mock_neo4j_client,  # noqa: ARG002
    ):
        """Test handling of invalid JSON from OpenAI."""
        # Mock invalid JSON response
        mock_openai_client.chat.completions.create.return_value.choices[
            0
        ].message.content = "Invalid JSON response"

        request = KnowledgeExtractionRequest(text="Some text to extract knowledge from")

        result = await graph_service.extract_knowledge_from_text(request)

        # Should handle gracefully and return empty results
        assert result.total_entities == 0
        assert result.total_relationships == 0
        assert result.average_confidence == 0.0

    async def test_f_contraction_merging(self, graph_service, mock_neo4j_client):
        """Test F-contraction merging for concept consolidation."""
        # Mock query results for similar entities
        mock_neo4j_client.execute_query.return_value = CypherResult(
            success=True,
            records=[
                {"similar_node": {"id": "node_1", "name": "Python Programming"}},
                {"similar_node": {"id": "node_2", "name": "Python Language"}},
            ],
            execution_time_ms=20.0,
            records_available=2,
        )

        # Mock merge operation
        mock_neo4j_client.execute_batch_queries.return_value = [
            CypherResult(
                success=True, records=[], execution_time_ms=15, records_available=0
            )
        ]

        node = GraphNode(
            name="Python",
            node_type=NodeType.CONCEPT,
            description="Programming language",
            confidence_score=0.9,
        )

        await graph_service._merge_similar_entities([node])  # noqa: SLF001

        # Verify merging logic was executed
        mock_neo4j_client.execute_query.assert_called()

    async def test_batch_operations(self, graph_service, mock_neo4j_client):
        """Test batch node and relationship operations."""
        # Mock batch query results
        mock_results = [
            CypherResult(
                success=True,
                records=[{"id": "node_1"}],
                execution_time_ms=5,
                records_available=1,
            ),
            CypherResult(
                success=True,
                records=[{"id": "node_2"}],
                execution_time_ms=6,
                records_available=1,
            ),
            CypherResult(
                success=True,
                records=[{"id": "rel_1"}],
                execution_time_ms=8,
                records_available=1,
            ),
        ]
        mock_neo4j_client.execute_batch_queries.return_value = mock_results

        nodes = [
            GraphNode(name="Node 1", node_type=NodeType.ENTITY),
            GraphNode(name="Node 2", node_type=NodeType.CONCEPT),
        ]

        relationships = [
            GraphRelationship(
                source_id="node_1",
                target_id="node_2",
                relationship_type=RelationshipType.RELATES_TO,
            )
        ]

        result = await graph_service.create_batch_nodes_and_relationships(
            nodes, relationships
        )

        assert result["nodes_created"] == 2
        assert result["relationships_created"] == 1

        # Verify batch execution
        mock_neo4j_client.execute_batch_queries.assert_called()


class TestGraphServiceIntegration:
    """Integration test scenarios."""

    async def test_end_to_end_knowledge_extraction_and_storage(
        self, graph_service, mock_openai_client, mock_neo4j_client
    ):
        """Test complete knowledge extraction and storage workflow."""
        # Mock OpenAI extraction
        mock_openai_client.chat.completions.create.return_value.choices[
            0
        ].message.content = """
        {
            "entities": [
                {
                    "name": "Alice",
                    "type": "Person",
                    "description": "Data scientist",
                    "confidence": 0.95,
                    "emotional_valence": 0.3,
                    "abstraction_level": 2
                }
            ],
            "relationships": []
        }
        """

        # Mock successful storage
        mock_neo4j_client.execute_batch_queries.return_value = [
            CypherResult(
                success=True,
                records=[{"id": "alice_1"}],
                execution_time_ms=10,
                records_available=1,
            )
        ]

        # Extract knowledge
        extraction_request = KnowledgeExtractionRequest(
            text=(
                "Alice is a talented data scientist working on "
                "machine learning projects."
            )
        )

        extraction_result = await graph_service.extract_knowledge_from_text(
            extraction_request
        )

        assert extraction_result.total_entities == 1
        assert extraction_result.extracted_nodes[0].name == "Alice"
        assert extraction_result.extracted_nodes[0].node_type == NodeType.PERSON

        # Verify complete workflow
        mock_openai_client.chat.completions.create.assert_called()
        mock_neo4j_client.execute_batch_queries.assert_called()

    async def test_memory_system_workflow(self, graph_service, mock_neo4j_client):
        """Test complete memory system workflow."""
        # Mock memory node creation
        mock_neo4j_client.execute_query.return_value = CypherResult(
            success=True,
            records=[
                {"id": "memory_alice", "created_at": datetime.now(UTC).isoformat()}
            ],
            execution_time_ms=12.0,
            records_available=1,
        )

        # Create memory node
        memory = await graph_service.create_memory_node(
            name="Alice",
            memory_type="person",
            observations=["intelligent", "collaborative", "detail-oriented"],
            context="colleague from ML team",
        )

        assert memory.name == "Alice"
        assert "intelligent" in memory.observations

        # Verify it's cached
        assert memory.id in graph_service._memory_cache  # noqa: SLF001

        # Mock memory retrieval
        mock_neo4j_client.execute_query.return_value = CypherResult(
            success=True,
            records=[
                {
                    "m": {
                        "id": memory.id,
                        "name": "Alice",
                        "memory_type": "person",
                        "observations": ["intelligent", "collaborative"],
                        "access_count": 1,
                    }
                }
            ],
            execution_time_ms=8.0,
            records_available=1,
        )

        # Retrieve memory
        retrieved = await graph_service.get_memory_by_name("Alice")

        assert retrieved is not None
        assert retrieved.name == "Alice"
        assert retrieved.access_count >= 1


@pytest.mark.asyncio
async def test_concurrent_operations(graph_service, mock_neo4j_client):
    """Test concurrent graph operations."""
    # Mock concurrent query results
    mock_neo4j_client.execute_query.return_value = CypherResult(
        success=True,
        records=[{"result": "success"}],
        execution_time_ms=50.0,
        records_available=1,
    )

    # Create multiple concurrent operations
    tasks = []
    for i in range(5):
        query = CypherQuery(
            query=f"CREATE (n:TestNode {{id: '{i}', name: 'Node {i}'}}) RETURN n",
            read_only=False,
        )
        tasks.append(graph_service.execute_cypher_query(query))

    # Execute concurrently
    results = await asyncio.gather(*tasks)

    # Verify all operations completed
    assert len(results) == 5
    assert all(result.success for result in results)

    # Verify client was called for each operation
    assert mock_neo4j_client.execute_query.call_count == 5
