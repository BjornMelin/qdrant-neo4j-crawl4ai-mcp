"""
FastMCP tools for vector database operations.

Provides MCP-compatible tools for semantic search, vector storage,
and collection management with comprehensive error handling.
"""

from typing import Any

from fastmcp import FastMCP
import structlog

from qdrant_neo4j_crawl4ai_mcp.models.vector_models import (
    CollectionConfig,
    EmbeddingRequest,
    VectorSearchRequest,
    VectorStoreRequest,
)
from qdrant_neo4j_crawl4ai_mcp.services.vector_service import (
    VectorService,
    VectorServiceError,
)

logger = structlog.get_logger(__name__)


def register_vector_tools(mcp: FastMCP, vector_service: VectorService) -> None:
    """
    Register all vector database tools with FastMCP server.

    Args:
        mcp: FastMCP server instance
        vector_service: Vector service instance
    """

    @mcp.tool()
    async def store_vector_document(
        content: str,
        collection_name: str = "documents",
        content_type: str = "text",
        source: str | None = None,
        tags: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
        embedding_model: str | None = None,
    ) -> dict[str, Any]:
        """
        Store a document with vector embedding in Qdrant.

        This tool converts text content into vector embeddings and stores them
        in the specified collection for later semantic search retrieval.

        Args:
            content: Text content to embed and store (1-100,000 characters)
            collection_name: Target collection name (default: documents)
            content_type: Content type classification (default: text)
            source: Optional source identifier for the content
            tags: Optional list of tags for categorization
            metadata: Optional additional metadata dictionary
            embedding_model: Override default embedding model

        Returns:
            Dictionary with storage results including vector ID and metrics

        Example:
            >>> await store_vector_document(
            ...     content="Machine learning is a subset of artificial intelligence",
            ...     collection_name="knowledge_base",
            ...     content_type="definition",
            ...     tags=["ai", "ml", "technology"],
            ...     metadata={"category": "computer_science"}
            ... )
            {
                "status": "success",
                "id": "abc123def456",
                "collection_name": "knowledge_base",
                "vector_dimensions": 384,
                "embedding_time_ms": 45.2,
                "storage_time_ms": 12.8
            }
        """
        try:
            request = VectorStoreRequest(
                content=content,
                collection_name=collection_name,
                content_type=content_type,
                source=source,
                tags=tags or [],
                metadata=metadata or {},
                embedding_model=embedding_model,
            )

            response = await vector_service.store_vector(request)

            logger.info(
                "Vector document stored via MCP tool",
                id=response.id,
                collection=response.collection_name,
                content_length=len(content),
            )

            return {
                "status": "success",
                "id": response.id,
                "collection_name": response.collection_name,
                "vector_dimensions": response.vector_dimensions,
                "embedding_time_ms": response.embedding_time_ms,
                "storage_time_ms": response.storage_time_ms,
                "timestamp": response.timestamp.isoformat(),
            }

        except VectorServiceError as e:
            logger.exception("Failed to store vector document", error=str(e))
            return {
                "status": "error",
                "error": str(e),
                "error_type": "VectorServiceError",
            }
        except Exception as e:
            logger.exception("Unexpected error storing vector document", error=str(e))
            return {
                "status": "error",
                "error": "Internal server error",
                "error_type": type(e).__name__,
            }

    @mcp.tool()
    async def semantic_vector_search(
        query: str,
        collection_name: str = "documents",
        limit: int = 10,
        score_threshold: float = 0.0,
        mode: str = "semantic",
        content_type: str | None = None,
        tags: list[str] | None = None,
        include_vectors: bool = False,
        include_content: bool = True,
    ) -> dict[str, Any]:
        """
        Perform semantic similarity search across vector embeddings.

        This tool finds documents similar to the query text using vector
        similarity search with configurable filters and thresholds.

        Args:
            query: Natural language search query (1-1,000 characters)
            collection_name: Collection to search (default: documents)
            limit: Maximum number of results (1-100, default: 10)
            score_threshold: Minimum similarity score (0.0-1.0, default: 0.0)
            mode: Search mode - semantic/hybrid/exact (default: semantic)
            content_type: Filter by content type
            tags: Filter by tags (must contain all specified tags)
            include_vectors: Include vector embeddings in response
            include_content: Include original content in response

        Returns:
            Dictionary with search results and metadata

        Example:
            >>> await semantic_vector_search(
            ...     query="artificial intelligence machine learning",
            ...     collection_name="knowledge_base",
            ...     limit=5,
            ...     score_threshold=0.7,
            ...     tags=["technology"]
            ... )
            {
                "status": "success",
                "query": "artificial intelligence machine learning",
                "collection_name": "knowledge_base",
                "results": [
                    {
                        "id": "abc123",
                        "score": 0.89,
                        "content": "Machine learning is a subset of AI...",
                        "metadata": {"category": "computer_science"}
                    }
                ],
                "total_found": 1,
                "search_time_ms": 23.4
            }
        """
        try:
            # Build filters
            filters = {}
            if content_type:
                filters["content_type"] = content_type
            if tags:
                filters["tags"] = {"in": tags}

            request = VectorSearchRequest(
                query=query,
                collection_name=collection_name,
                limit=limit,
                score_threshold=score_threshold,
                mode=mode,
                filters=filters,
                include_vectors=include_vectors,
                include_payload=include_content,
            )

            response = await vector_service.search_vectors(request)

            # Format results
            formatted_results = []
            for result in response.results:
                formatted_result = {"id": result.id, "score": result.score}

                if include_content and result.payload:
                    formatted_result["content"] = result.payload.content
                    formatted_result["content_type"] = result.payload.content_type
                    formatted_result["source"] = result.payload.source
                    formatted_result["tags"] = result.payload.tags
                    formatted_result["metadata"] = result.payload.metadata

                if include_vectors and result.vector:
                    formatted_result["vector"] = result.vector

                formatted_results.append(formatted_result)

            logger.info(
                "Vector search completed via MCP tool",
                collection=collection_name,
                query_length=len(query),
                results_count=len(formatted_results),
                mode=mode,
            )

            return {
                "status": "success",
                "query": response.query,
                "collection_name": response.collection_name,
                "results": formatted_results,
                "total_found": response.total_found,
                "search_time_ms": response.search_time_ms,
                "mode": response.mode.value,
                "timestamp": response.timestamp.isoformat(),
            }

        except VectorServiceError as e:
            logger.exception("Vector search failed", error=str(e))
            return {
                "status": "error",
                "error": str(e),
                "error_type": "VectorServiceError",
            }
        except Exception as e:
            logger.exception("Unexpected error in vector search", error=str(e))
            return {
                "status": "error",
                "error": "Internal server error",
                "error_type": type(e).__name__,
            }

    @mcp.tool()
    async def create_vector_collection(
        name: str,
        vector_size: int,
        distance_metric: str = "Cosine",
        description: str | None = None,
    ) -> dict[str, Any]:
        """
        Create a new vector collection for storing embeddings.

        This tool creates a new collection with specified configuration
        for storing and searching vector embeddings.

        Args:
            name: Collection name (1-64 chars, alphanumeric + hyphens/underscores)
            vector_size: Vector dimensions (1-2048, must match embedding model)
            distance_metric: Distance metric - Cosine/Dot/Euclidean (default: Cosine)
            description: Optional collection description

        Returns:
            Dictionary with creation results

        Example:
            >>> await create_vector_collection(
            ...     name="research_papers",
            ...     vector_size=768,
            ...     distance_metric="Cosine",
            ...     description="Academic research papers collection"
            ... )
            {
                "status": "success",
                "name": "research_papers",
                "vector_size": 768,
                "distance_metric": "Cosine",
                "created": true
            }
        """
        try:
            # Validate distance metric
            valid_metrics = ["Cosine", "Dot", "Euclidean", "Manhattan"]
            if distance_metric not in valid_metrics:
                return {
                    "status": "error",
                    "error": f"Invalid distance metric. Must be one of: {valid_metrics}",
                    "error_type": "ValidationError",
                }

            config = CollectionConfig(
                name=name,
                vector_size=vector_size,
                distance=distance_metric,
                optimizers_config={
                    "default_segment_number": 2,
                    "max_segment_size": 200000,
                    "memmap_threshold": 100000,
                    "indexing_threshold": 20000,
                },
                hnsw_config={
                    "m": 16,
                    "ef_construct": 100,
                    "full_scan_threshold": 10000,
                },
            )

            result = await vector_service.create_collection(config)

            logger.info(
                "Vector collection created via MCP tool",
                name=name,
                vector_size=vector_size,
                distance_metric=distance_metric,
            )

            return {
                "status": "success",
                "name": name,
                "vector_size": vector_size,
                "distance_metric": distance_metric,
                "created": result,
                "description": description,
            }

        except VectorServiceError as e:
            logger.exception("Failed to create vector collection", error=str(e))
            return {
                "status": "error",
                "error": str(e),
                "error_type": "VectorServiceError",
            }
        except Exception as e:
            logger.exception("Unexpected error creating collection", error=str(e))
            return {
                "status": "error",
                "error": "Internal server error",
                "error_type": type(e).__name__,
            }

    @mcp.tool()
    async def list_vector_collections() -> dict[str, Any]:
        """
        List all available vector collections with their statistics.

        This tool provides an overview of all collections, their sizes,
        and configuration details for management and monitoring.

        Returns:
            Dictionary with collection list and statistics

        Example:
            >>> await list_vector_collections()
            {
                "status": "success",
                "collections": [
                    {
                        "name": "documents",
                        "vector_size": 384,
                        "points_count": 1250,
                        "distance_metric": "Cosine",
                        "disk_usage_mb": 15.2
                    }
                ],
                "total_collections": 1,
                "total_vectors": 1250
            }
        """
        try:
            response = await vector_service.list_collections()

            # Format collection information
            formatted_collections = []
            for collection in response.collections:
                formatted_collections.append(
                    {
                        "name": collection.name,
                        "status": collection.status.value,
                        "vector_size": collection.vector_size,
                        "distance_metric": collection.distance.value,
                        "points_count": collection.points_count,
                        "indexed_vectors": collection.indexed_vectors_count,
                        "segments_count": collection.segments_count,
                        "disk_usage_bytes": collection.disk_data_size,
                        "disk_usage_mb": round(
                            collection.disk_data_size / (1024 * 1024), 2
                        ),
                        "ram_usage_bytes": collection.ram_data_size,
                        "ram_usage_mb": round(
                            collection.ram_data_size / (1024 * 1024), 2
                        ),
                        "created_at": collection.created_at.isoformat(),
                        "updated_at": collection.updated_at.isoformat(),
                    }
                )

            logger.info(
                "Listed vector collections via MCP tool",
                total_collections=response.total_collections,
                total_points=response.total_points,
            )

            return {
                "status": "success",
                "collections": formatted_collections,
                "total_collections": response.total_collections,
                "total_vectors": response.total_points,
                "timestamp": response.timestamp.isoformat(),
            }

        except VectorServiceError as e:
            logger.exception("Failed to list collections", error=str(e))
            return {
                "status": "error",
                "error": str(e),
                "error_type": "VectorServiceError",
            }
        except Exception as e:
            logger.exception("Unexpected error listing collections", error=str(e))
            return {
                "status": "error",
                "error": "Internal server error",
                "error_type": type(e).__name__,
            }

    @mcp.tool()
    async def generate_text_embeddings(
        texts: list[str], model: str | None = None, normalize: bool = True
    ) -> dict[str, Any]:
        """
        Generate vector embeddings for text inputs.

        This tool converts text into numerical vector representations
        using pre-trained embedding models for similarity analysis.

        Args:
            texts: List of texts to embed (1-100 items, each 1-10,000 chars)
            model: Override default embedding model name
            normalize: Whether to normalize vectors to unit length

        Returns:
            Dictionary with embeddings and metadata

        Example:
            >>> await generate_text_embeddings(
            ...     texts=["Hello world", "Machine learning"],
            ...     normalize=True
            ... )
            {
                "status": "success",
                "embeddings": [
                    [0.1, 0.2, -0.3, ...],
                    [0.4, -0.1, 0.8, ...]
                ],
                "model": "sentence-transformers/all-MiniLM-L6-v2",
                "dimensions": 384,
                "processing_time_ms": 42.1
            }
        """
        try:
            request = EmbeddingRequest(texts=texts, model=model, normalize=normalize)

            response = await vector_service.generate_embeddings(request)

            logger.info(
                "Generated embeddings via MCP tool",
                texts_count=len(texts),
                model=response.model,
                dimensions=response.dimensions,
            )

            return {
                "status": "success",
                "embeddings": response.embeddings,
                "model": response.model,
                "dimensions": response.dimensions,
                "processing_time_ms": response.processing_time_ms,
                "timestamp": response.timestamp.isoformat(),
            }

        except VectorServiceError as e:
            logger.exception("Failed to generate embeddings", error=str(e))
            return {
                "status": "error",
                "error": str(e),
                "error_type": "VectorServiceError",
            }
        except Exception as e:
            logger.exception("Unexpected error generating embeddings", error=str(e))
            return {
                "status": "error",
                "error": "Internal server error",
                "error_type": type(e).__name__,
            }

    @mcp.tool()
    async def delete_vector_collection(
        collection_name: str, confirm: bool = False
    ) -> dict[str, Any]:
        """
        Delete a vector collection and all its data.

        This tool permanently removes a collection and all stored vectors.
        Use with caution as this operation cannot be undone.

        Args:
            collection_name: Name of collection to delete
            confirm: Must be True to confirm deletion

        Returns:
            Dictionary with deletion results

        Example:
            >>> await delete_vector_collection(
            ...     collection_name="test_collection",
            ...     confirm=True
            ... )
            {
                "status": "success",
                "collection_name": "test_collection",
                "deleted": true
            }
        """
        try:
            if not confirm:
                return {
                    "status": "error",
                    "error": "Deletion not confirmed. Set confirm=True to proceed.",
                    "error_type": "ConfirmationRequired",
                }

            result = await vector_service.delete_collection(collection_name)

            logger.warning(
                "Vector collection deleted via MCP tool",
                collection=collection_name,
                confirmed=confirm,
            )

            return {
                "status": "success",
                "collection_name": collection_name,
                "deleted": result,
                "warning": "Collection and all data permanently deleted",
            }

        except VectorServiceError as e:
            logger.exception("Failed to delete collection", error=str(e))
            return {
                "status": "error",
                "error": str(e),
                "error_type": "VectorServiceError",
            }
        except Exception as e:
            logger.exception("Unexpected error deleting collection", error=str(e))
            return {
                "status": "error",
                "error": "Internal server error",
                "error_type": type(e).__name__,
            }

    @mcp.tool()
    async def get_vector_service_stats() -> dict[str, Any]:
        """
        Get comprehensive statistics about the vector service.

        This tool provides detailed metrics about collections, storage,
        performance, and service health for monitoring and optimization.

        Returns:
            Dictionary with service statistics and health metrics

        Example:
            >>> await get_vector_service_stats()
            {
                "status": "success",
                "stats": {
                    "total_collections": 3,
                    "total_vectors": 15420,
                    "total_disk_usage_mb": 234.5,
                    "average_search_time_ms": 18.2,
                    "embeddings_generated": 15420
                },
                "health": {
                    "service": "vector",
                    "status": "healthy",
                    "response_time_ms": 15.3
                }
            }
        """
        try:
            # Get service statistics
            stats = await vector_service.get_service_stats()

            # Get health check
            health = await vector_service.health_check()

            logger.debug("Retrieved vector service stats via MCP tool")

            return {
                "status": "success",
                "stats": {
                    "total_collections": stats.total_collections,
                    "total_vectors": stats.total_vectors,
                    "total_disk_usage_bytes": stats.total_disk_usage,
                    "total_disk_usage_mb": round(
                        stats.total_disk_usage / (1024 * 1024), 2
                    ),
                    "total_ram_usage_bytes": stats.total_ram_usage,
                    "total_ram_usage_mb": round(
                        stats.total_ram_usage / (1024 * 1024), 2
                    ),
                    "average_search_time_ms": stats.average_search_time_ms,
                    "embeddings_generated": stats.embeddings_generated,
                    "last_updated": stats.last_updated.isoformat(),
                },
                "health": {
                    "service": health.service,
                    "status": health.status,
                    "response_time_ms": health.response_time_ms,
                    "details": health.details,
                    "timestamp": health.timestamp.isoformat(),
                },
            }

        except VectorServiceError as e:
            logger.exception("Failed to get service stats", error=str(e))
            return {
                "status": "error",
                "error": str(e),
                "error_type": "VectorServiceError",
            }
        except Exception as e:
            logger.exception("Unexpected error getting service stats", error=str(e))
            return {
                "status": "error",
                "error": "Internal server error",
                "error_type": type(e).__name__,
            }

    logger.info("Vector database tools registered with FastMCP server")
