"""
Unit tests for vector database service.

Tests cover embedding generation, vector storage, semantic search,
and collection management with comprehensive mocking.
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from qdrant_client import models

from qdrant_neo4j_crawl4ai_mcp.models.vector_models import (
    CollectionConfig,
    CollectionInfo,
    CollectionStatus,
    EmbeddingRequest,
    SearchMode,
    VectorDistance,
    VectorSearchRequest,
    VectorServiceConfig,
    VectorStoreRequest,
)
from qdrant_neo4j_crawl4ai_mcp.services.vector_service import (
    EmbeddingService,
    VectorService,
    VectorServiceError,
)


@pytest.fixture
def vector_config():
    """Test vector service configuration."""
    return VectorServiceConfig(
        qdrant_url="http://localhost:6333",
        qdrant_api_key=None,
        default_collection="test_collection",
        default_embedding_model="sentence-transformers/all-MiniLM-L6-v2",
        connection_timeout=30,
        max_retries=3,
        retry_delay=1.0,
        enable_caching=True,
    )


@pytest.fixture
def mock_qdrant_client():
    """Mock Qdrant client."""
    client = AsyncMock()
    client.connect.return_value = None
    client.disconnect.return_value = None
    client.list_collections.return_value = []
    client.create_collection.return_value = True
    client.delete_collection.return_value = True
    client.upsert_points.return_value = True
    client.search_points.return_value = []
    client.get_health_status.return_value = {"status": "healthy"}
    return client


@pytest.fixture
def mock_embedding_service():
    """Mock embedding service."""
    service = AsyncMock()
    service.generate_embeddings.return_value = (
        [[0.1, 0.2, 0.3, 0.4] * 96],  # 384-dimensional vector
        {
            "model": "sentence-transformers/all-MiniLM-L6-v2",
            "dimensions": 384,
            "processing_time_ms": 45.2,
            "cache_hits": 0,
            "cache_misses": 1,
        },
    )
    service.get_model_info.return_value = {
        "dimensions": 384,
        "max_seq_length": 512,
        "name": "sentence-transformers/all-MiniLM-L6-v2",
    }
    return service


class TestEmbeddingService:
    """Test embedding service functionality."""

    @pytest.mark.asyncio
    async def test_load_model_success(self):
        """Test successful model loading."""
        with patch(
            "qdrant_neo4j_crawl4ai_mcp.services.vector_service.SentenceTransformer"
        ) as mock_st:
            mock_model = MagicMock()
            mock_model.get_sentence_embedding_dimension.return_value = 384
            mock_model.max_seq_length = 512
            mock_st.return_value = mock_model

            service = EmbeddingService()
            model = await service._load_model("test-model")  # noqa: SLF001

            assert model == mock_model
            assert "test-model" in service._models  # noqa: SLF001
            assert "test-model" in service._model_info  # noqa: SLF001

    @pytest.mark.asyncio
    async def test_load_model_failure(self):
        """Test model loading failure."""
        with patch(
            "qdrant_neo4j_crawl4ai_mcp.services.vector_service.SentenceTransformer",
            side_effect=Exception("Model not found"),
        ):
            service = EmbeddingService()

            with pytest.raises(VectorServiceError, match="Failed to load model"):
                await service._load_model("invalid-model")  # noqa: SLF001

    @pytest.mark.asyncio
    async def test_generate_embeddings_success(self):
        """Test successful embedding generation."""
        with patch(
            "qdrant_neo4j_crawl4ai_mcp.services.vector_service.SentenceTransformer"
        ) as mock_st:
            mock_model = MagicMock()
            mock_model.get_sentence_embedding_dimension.return_value = 384
            mock_model.max_seq_length = 512
            mock_model.encode.return_value = MagicMock()
            mock_model.encode.return_value.tolist.return_value = [[0.1, 0.2, 0.3] * 128]
            mock_st.return_value = mock_model

            service = EmbeddingService()
            embeddings, model_info = await service.generate_embeddings(
                ["Test text"], normalize=True, use_cache=False
            )

            assert len(embeddings) == 1
            assert len(embeddings[0]) == 384
            assert model_info["dimensions"] == 384
            assert "processing_time_ms" in model_info

    @pytest.mark.asyncio
    async def test_embedding_cache(self):
        """Test embedding caching functionality."""
        with patch(
            "qdrant_neo4j_crawl4ai_mcp.services.vector_service.SentenceTransformer"
        ) as mock_st:
            mock_model = MagicMock()
            mock_model.get_sentence_embedding_dimension.return_value = 384
            mock_model.max_seq_length = 512
            mock_model.encode.return_value = MagicMock()
            mock_model.encode.return_value.tolist.return_value = [[0.1, 0.2, 0.3] * 128]
            mock_st.return_value = mock_model

            service = EmbeddingService()

            # First call - should generate embedding
            embeddings1, info1 = await service.generate_embeddings(
                ["Test text"], use_cache=True
            )

            # Second call - should use cache
            embeddings2, info2 = await service.generate_embeddings(
                ["Test text"], use_cache=True
            )

            assert embeddings1 == embeddings2
            assert info2["cache_hits"] == 1
            assert info2["cache_misses"] == 0


class TestVectorService:
    """Test vector service functionality."""

    @pytest.mark.asyncio
    async def test_initialization(self, vector_config, mock_qdrant_client):
        """Test vector service initialization."""
        with patch(
            "qdrant_neo4j_crawl4ai_mcp.services.vector_service.QdrantClient",
            return_value=mock_qdrant_client,
        ):
            service = VectorService(vector_config)

            assert service.config == vector_config
            assert service.qdrant_client == mock_qdrant_client
            assert service.embedding_service is not None

    @pytest.mark.asyncio
    async def test_store_vector_success(
        self, vector_config, mock_qdrant_client, mock_embedding_service
    ):
        """Test successful vector storage."""
        with patch(
            "qdrant_neo4j_crawl4ai_mcp.services.vector_service.QdrantClient",
            return_value=mock_qdrant_client,
        ):
            service = VectorService(vector_config)
            service.embedding_service = mock_embedding_service

            request = VectorStoreRequest(
                content="Test document content",
                collection_name="test_collection",
                content_type="text",
                tags=["test", "document"],
                metadata={"author": "test_user"},
            )

            response = await service.store_vector(request)

            assert response.status == "success"
            assert response.collection_name == "test_collection"
            assert response.vector_dimensions == 384
            assert mock_qdrant_client.upsert_points.called

    @pytest.mark.asyncio
    async def test_search_vectors_success(
        self, vector_config, mock_qdrant_client, mock_embedding_service
    ):
        """Test successful vector search."""
        # Mock search results
        mock_result = models.ScoredPoint(
            id="test-id-123",
            version=1,
            score=0.95,
            payload={
                "content": "Matching document content",
                "content_type": "text",
                "source": None,
                "tags": ["test"],
                "metadata": {},
            },
            vector=None,
        )
        mock_qdrant_client.search_points.return_value = [mock_result]

        with patch(
            "qdrant_neo4j_crawl4ai_mcp.services.vector_service.QdrantClient",
            return_value=mock_qdrant_client,
        ):
            service = VectorService(vector_config)
            service.embedding_service = mock_embedding_service

            request = VectorSearchRequest(
                query="Find similar documents",
                collection_name="test_collection",
                limit=5,
                score_threshold=0.7,
                mode=SearchMode.SEMANTIC,
            )

            response = await service.search_vectors(request)

            assert response.query == "Find similar documents"
            assert response.collection_name == "test_collection"
            assert len(response.results) == 1
            assert response.results[0].id == "test-id-123"
            assert response.results[0].score == 0.95

    @pytest.mark.asyncio
    async def test_create_collection_success(self, vector_config, mock_qdrant_client):
        """Test successful collection creation."""
        with patch(
            "qdrant_neo4j_crawl4ai_mcp.services.vector_service.QdrantClient",
            return_value=mock_qdrant_client,
        ):
            service = VectorService(vector_config)

            config = CollectionConfig(
                name="new_collection", vector_size=384, distance=VectorDistance.COSINE
            )

            result = await service.create_collection(config)

            assert result is True
            assert mock_qdrant_client.create_collection.called

    @pytest.mark.asyncio
    async def test_delete_collection_success(self, vector_config, mock_qdrant_client):
        """Test successful collection deletion."""
        with patch(
            "qdrant_neo4j_crawl4ai_mcp.services.vector_service.QdrantClient",
            return_value=mock_qdrant_client,
        ):
            service = VectorService(vector_config)

            result = await service.delete_collection("test_collection")

            assert result is True
            assert mock_qdrant_client.delete_collection.called

    @pytest.mark.asyncio
    async def test_list_collections_success(self, vector_config, mock_qdrant_client):
        """Test successful collection listing."""
        mock_collection = CollectionInfo(
            name="test_collection",
            status=CollectionStatus.ACTIVE,
            vector_size=384,
            distance=VectorDistance.COSINE,
            points_count=100,
            indexed_vectors_count=100,
            segments_count=1,
            disk_data_size=1024000,
            ram_data_size=512000,
            config={},
            created_at=1640995200.0,
            updated_at=1640995200.0,
        )
        mock_qdrant_client.list_collections.return_value = [mock_collection]

        with patch(
            "qdrant_neo4j_crawl4ai_mcp.services.vector_service.QdrantClient",
            return_value=mock_qdrant_client,
        ):
            service = VectorService(vector_config)

            response = await service.list_collections()

            assert response.total_collections == 1
            assert response.total_points == 100
            assert len(response.collections) == 1
            assert response.collections[0].name == "test_collection"

    @pytest.mark.asyncio
    async def test_generate_embeddings_success(
        self, vector_config, mock_qdrant_client, mock_embedding_service
    ):
        """Test successful embedding generation."""
        with patch(
            "qdrant_neo4j_crawl4ai_mcp.services.vector_service.QdrantClient",
            return_value=mock_qdrant_client,
        ):
            service = VectorService(vector_config)
            service.embedding_service = mock_embedding_service

            request = EmbeddingRequest(
                texts=["Text one", "Text two"],
                model="sentence-transformers/all-MiniLM-L6-v2",
                normalize=True,
            )

            response = await service.generate_embeddings(request)

            assert len(response.embeddings) == 1  # Mock returns single embedding
            assert response.model == "sentence-transformers/all-MiniLM-L6-v2"
            assert response.dimensions == 384
            assert response.processing_time_ms > 0

    @pytest.mark.asyncio
    async def test_health_check_success(
        self, vector_config, mock_qdrant_client, mock_embedding_service
    ):
        """Test successful health check."""
        with patch(
            "qdrant_neo4j_crawl4ai_mcp.services.vector_service.QdrantClient",
            return_value=mock_qdrant_client,
        ):
            service = VectorService(vector_config)
            service.embedding_service = mock_embedding_service

            result = await service.health_check()

            assert result.service == "vector"
            assert result.status == "healthy"
            assert result.response_time_ms > 0
            assert "qdrant" in result.details

    @pytest.mark.asyncio
    async def test_health_check_failure(
        self, vector_config, mock_qdrant_client, mock_embedding_service
    ):
        """Test health check failure."""
        mock_qdrant_client.get_health_status.side_effect = Exception(
            "Connection failed"
        )

        with patch(
            "qdrant_neo4j_crawl4ai_mcp.services.vector_service.QdrantClient",
            return_value=mock_qdrant_client,
        ):
            service = VectorService(vector_config)
            service.embedding_service = mock_embedding_service

            result = await service.health_check()

            assert result.service == "vector"
            assert result.status == "unhealthy"
            assert "error" in result.details

    @pytest.mark.asyncio
    async def test_vector_service_error_handling(
        self, vector_config, mock_qdrant_client
    ):
        """Test error handling in vector service operations."""
        mock_qdrant_client.upsert_points.side_effect = Exception("Qdrant error")

        with patch(
            "qdrant_neo4j_crawl4ai_mcp.services.vector_service.QdrantClient",
            return_value=mock_qdrant_client,
        ):
            service = VectorService(vector_config)

            request = VectorStoreRequest(
                content="Test content", collection_name="test_collection"
            )

            with pytest.raises(VectorServiceError, match="Failed to store vector"):
                await service.store_vector(request)


class TestVectorModels:
    """Test vector model validation."""

    def test_vector_store_request_validation(self):
        """Test vector store request validation."""
        # Valid request
        request = VectorStoreRequest(
            content="Valid content", collection_name="valid_collection"
        )
        assert request.content == "Valid content"
        assert request.collection_name == "valid_collection"

        # Invalid content length
        with pytest.raises(ValueError, match="Content cannot be empty"):
            VectorStoreRequest(
                content="",  # Empty content
                collection_name="test",
            )

        # Invalid collection name
        with pytest.raises(ValueError, match="collection name"):
            VectorStoreRequest(
                content="Valid content",
                collection_name="",  # Empty collection name
            )

    def test_vector_search_request_validation(self):
        """Test vector search request validation."""
        # Valid request
        request = VectorSearchRequest(
            query="Valid query",
            collection_name="test_collection",
            limit=10,
            score_threshold=0.7,
        )
        assert request.query == "Valid query"
        assert request.limit == 10
        assert request.score_threshold == 0.7

        # Invalid limit
        with pytest.raises(ValueError, match="limit"):
            VectorSearchRequest(
                query="Valid query",
                collection_name="test",
                limit=0,  # Invalid limit
            )

        # Invalid score threshold
        with pytest.raises(ValueError, match="score_threshold"):
            VectorSearchRequest(
                query="Valid query",
                collection_name="test",
                score_threshold=1.5,  # Invalid threshold > 1.0
            )

    def test_collection_config_validation(self):
        """Test collection configuration validation."""
        # Valid config
        config = CollectionConfig(
            name="valid_collection", vector_size=384, distance=VectorDistance.COSINE
        )
        assert config.name == "valid_collection"
        assert config.vector_size == 384
        assert config.distance == VectorDistance.COSINE

        # Invalid vector size
        with pytest.raises(ValueError, match="vector_size"):
            CollectionConfig(
                name="test",
                vector_size=0,  # Invalid size
                distance=VectorDistance.COSINE,
            )

    def test_embedding_request_validation(self):
        """Test embedding request validation."""
        # Valid request
        request = EmbeddingRequest(texts=["Text one", "Text two"], normalize=True)
        assert len(request.texts) == 2
        assert request.normalize is True

        # Empty texts
        with pytest.raises(ValueError, match="texts cannot be empty"):
            EmbeddingRequest(texts=[])

        # Too many texts
        with pytest.raises(ValueError, match="Too many texts"):
            EmbeddingRequest(texts=["text"] * 101)  # Over 100 limit


# Performance and integration tests
class TestVectorServiceIntegration:
    """Integration tests for vector service."""

    @pytest.mark.asyncio
    async def test_end_to_end_workflow(
        self, vector_config, mock_qdrant_client, mock_embedding_service
    ):
        """Test complete workflow from storage to search."""
        with patch(
            "qdrant_neo4j_crawl4ai_mcp.services.vector_service.QdrantClient",
            return_value=mock_qdrant_client,
        ):
            service = VectorService(vector_config)
            service.embedding_service = mock_embedding_service

            # Store a document
            store_request = VectorStoreRequest(
                content="Machine learning is a subset of artificial intelligence",
                collection_name="knowledge_base",
                tags=["ai", "ml", "technology"],
            )

            store_response = await service.store_vector(store_request)
            assert store_response.status == "success"

            # Search for similar documents
            search_request = VectorSearchRequest(
                query="artificial intelligence and machine learning",
                collection_name="knowledge_base",
                limit=5,
                score_threshold=0.7,
            )

            # Mock search result
            mock_result = models.ScoredPoint(
                id=store_response.id,
                version=1,
                score=0.95,
                payload={
                    "content": (
                        "Machine learning is a subset of artificial intelligence"
                    ),
                    "content_type": "text",
                    "source": None,
                    "tags": ["ai", "ml", "technology"],
                    "metadata": {},
                },
            )
            mock_qdrant_client.search_points.return_value = [mock_result]

            search_response = await service.search_vectors(search_request)

            assert len(search_response.results) == 1
            assert search_response.results[0].score == 0.95

    @pytest.mark.asyncio
    async def test_concurrent_operations(
        self, vector_config, mock_qdrant_client, mock_embedding_service
    ):
        """Test concurrent vector operations."""
        with patch(
            "qdrant_neo4j_crawl4ai_mcp.services.vector_service.QdrantClient",
            return_value=mock_qdrant_client,
        ):
            service = VectorService(vector_config)
            service.embedding_service = mock_embedding_service

            # Create multiple store requests
            requests = [
                VectorStoreRequest(
                    content=f"Document content {i}", collection_name="test_collection"
                )
                for i in range(5)
            ]

            # Execute concurrently
            tasks = [service.store_vector(req) for req in requests]
            responses = await asyncio.gather(*tasks)

            # Verify all succeeded
            assert len(responses) == 5
            assert all(r.status == "success" for r in responses)
            assert len({r.id for r in responses}) == 5  # All unique IDs


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
