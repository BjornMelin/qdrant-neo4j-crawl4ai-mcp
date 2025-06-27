"""
Vector database service with FastMCP integration.

Provides high-level vector operations with embedding generation,
semantic search, and collection management using Qdrant backend.
"""

import asyncio
import hashlib
import time
from typing import Any
import uuid

from qdrant_client import models
from sentence_transformers import SentenceTransformer
import structlog

from qdrant_neo4j_crawl4ai_mcp.models.vector_models import (
    CollectionConfig,
    CollectionListResponse,
    EmbeddingRequest,
    EmbeddingResponse,
    HealthCheckResult,
    SearchMode,
    VectorDistance,
    VectorPayload,
    VectorSearchRequest,
    VectorSearchResponse,
    VectorSearchResult,
    VectorServiceConfig,
    VectorStats,
    VectorStoreRequest,
    VectorStoreResponse,
)
from qdrant_neo4j_crawl4ai_mcp.services.qdrant_client import QdrantClient

logger = structlog.get_logger(__name__)


class VectorServiceError(Exception):
    """Vector service related errors."""


class EmbeddingService:
    """
    Embedding generation service with model management.

    Handles multiple embedding models with caching and batch processing.
    """

    def __init__(
        self, default_model: str = "sentence-transformers/all-MiniLM-L6-v2"
    ) -> None:
        """Initialize embedding service with default model."""
        self.default_model = default_model
        self._models: dict[str, SentenceTransformer] = {}
        self._model_info: dict[str, dict[str, Any]] = {}
        self._embedding_cache: dict[str, list[float]] = {}

        logger.info("Embedding service initialized", default_model=default_model)

    async def _load_model(self, model_name: str) -> SentenceTransformer:
        """Load and cache embedding model."""
        if model_name not in self._models:
            try:
                logger.info("Loading embedding model", model=model_name)

                # Load model in executor to avoid blocking
                loop = asyncio.get_event_loop()
                model = await loop.run_in_executor(
                    None, SentenceTransformer, model_name
                )

                self._models[model_name] = model
                self._model_info[model_name] = {
                    "dimensions": model.get_sentence_embedding_dimension(),
                    "max_seq_length": model.max_seq_length,
                    "name": model_name,
                }

                logger.info(
                    "Embedding model loaded successfully",
                    model=model_name,
                    dimensions=self._model_info[model_name]["dimensions"],
                    max_length=self._model_info[model_name]["max_seq_length"],
                )

            except Exception as e:
                logger.exception(
                    "Failed to load embedding model",
                    model=model_name,
                    error=str(e),
                    error_type=type(e).__name__,
                )
                raise VectorServiceError(
                    f"Failed to load model {model_name}: {e}"
                ) from e

        return self._models[model_name]

    def _get_cache_key(self, text: str, model_name: str) -> str:
        """Generate cache key for embedding."""
        content = f"{model_name}:{text}"
        return hashlib.sha256(content.encode()).hexdigest()

    async def generate_embeddings(
        self,
        texts: list[str],
        model_name: str | None = None,
        normalize: bool = True,
        use_cache: bool = True,
    ) -> tuple[list[list[float]], dict[str, Any]]:
        """
        Generate embeddings for texts with caching.

        Args:
            texts: List of texts to embed
            model_name: Override default model
            normalize: Whether to normalize vectors
            use_cache: Whether to use embedding cache

        Returns:
            Tuple of (embeddings, model_info)
        """
        model_name = model_name or self.default_model
        model = await self._load_model(model_name)

        start_time = time.time()
        embeddings = []
        cache_hits = 0

        # Check cache for each text
        uncached_texts = []
        uncached_indices = []

        for i, text in enumerate(texts):
            if use_cache:
                cache_key = self._get_cache_key(text, model_name)
                if cache_key in self._embedding_cache:
                    embeddings.append(self._embedding_cache[cache_key])
                    cache_hits += 1
                    continue

            embeddings.append(None)  # Placeholder
            uncached_texts.append(text)
            uncached_indices.append(i)

        # Generate embeddings for uncached texts
        if uncached_texts:
            try:
                loop = asyncio.get_event_loop()
                new_embeddings = await loop.run_in_executor(
                    None,
                    lambda: model.encode(
                        uncached_texts,
                        normalize_embeddings=normalize,
                        show_progress_bar=False,
                    ).tolist(),
                )

                # Update cache and results
                for i, embedding in enumerate(new_embeddings):
                    result_index = uncached_indices[i]
                    embeddings[result_index] = embedding

                    if use_cache:
                        cache_key = self._get_cache_key(uncached_texts[i], model_name)
                        self._embedding_cache[cache_key] = embedding

                        # Limit cache size
                        if len(self._embedding_cache) > 10000:
                            # Remove oldest entries (simple FIFO)
                            keys_to_remove = list(self._embedding_cache.keys())[:1000]
                            for key in keys_to_remove:
                                del self._embedding_cache[key]

            except Exception as e:
                logger.exception(
                    "Embedding generation failed",
                    model=model_name,
                    texts_count=len(uncached_texts),
                    error=str(e),
                )
                raise VectorServiceError(f"Embedding generation failed: {e}") from e

        processing_time = (time.time() - start_time) * 1000

        logger.debug(
            "Generated embeddings",
            model=model_name,
            texts_count=len(texts),
            cache_hits=cache_hits,
            cache_misses=len(uncached_texts),
            processing_time_ms=processing_time,
        )

        return embeddings, {
            "model": model_name,
            "dimensions": self._model_info[model_name]["dimensions"],
            "processing_time_ms": processing_time,
            "cache_hits": cache_hits,
            "cache_misses": len(uncached_texts),
        }

    def get_model_info(self, model_name: str | None = None) -> dict[str, Any]:
        """Get information about a loaded model."""
        model_name = model_name or self.default_model
        return self._model_info.get(model_name, {})


class VectorService:
    """
    Production-ready vector database service.

    Provides comprehensive vector operations with embedding generation,
    semantic search, and collection management.
    """

    def __init__(self, config: VectorServiceConfig) -> None:
        """Initialize vector service with configuration."""
        self.config = config
        self.qdrant_client = QdrantClient(config)
        self.embedding_service = EmbeddingService(config.default_embedding_model)
        self._stats = {
            "embeddings_generated": 0,
            "searches_performed": 0,
            "vectors_stored": 0,
            "total_search_time_ms": 0.0,
        }

        logger.info(
            "Vector service initialized",
            qdrant_url=config.qdrant_url,
            default_collection=config.default_collection,
            default_model=config.default_embedding_model,
        )

    async def initialize(self) -> None:
        """Initialize the vector service and create default collection."""
        try:
            await self.qdrant_client.connect()

            # Ensure default collection exists
            await self._ensure_default_collection()

            logger.info("Vector service initialized successfully")

        except Exception as e:
            logger.exception(
                "Vector service initialization failed",
                error=str(e),
                error_type=type(e).__name__,
            )
            raise

    async def shutdown(self) -> None:
        """Shutdown the vector service."""
        try:
            await self.qdrant_client.disconnect()
            logger.info("Vector service shutdown completed")
        except Exception as e:
            logger.warning("Error during vector service shutdown", error=str(e))

    async def _ensure_default_collection(self) -> None:
        """Ensure the default collection exists."""
        try:
            collections = await self.qdrant_client.list_collections()
            collection_names = [c.name for c in collections]

            if self.config.default_collection not in collection_names:
                # Get model info for vector dimensions
                model_info = self.embedding_service.get_model_info()
                dimensions = model_info.get(
                    "dimensions", 384
                )  # Default for all-MiniLM-L6-v2

                config = CollectionConfig(
                    name=self.config.default_collection,
                    vector_size=dimensions,
                    distance=VectorDistance.COSINE,
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

                await self.create_collection(config)

                logger.info(
                    "Created default collection",
                    name=self.config.default_collection,
                    dimensions=dimensions,
                )

        except Exception as e:
            logger.exception(
                "Failed to ensure default collection",
                collection=self.config.default_collection,
                error=str(e),
            )
            raise

    async def create_collection(self, config: CollectionConfig) -> bool:
        """Create a new vector collection."""
        try:
            result = await self.qdrant_client.create_collection(config)

            logger.info(
                "Created vector collection",
                name=config.name,
                vector_size=config.vector_size,
                distance=config.distance.value,
            )

            return result

        except Exception as e:
            logger.exception(
                "Failed to create collection", name=config.name, error=str(e)
            )
            raise VectorServiceError(
                f"Failed to create collection {config.name}: {e}"
            ) from e

    async def delete_collection(self, collection_name: str) -> bool:
        """Delete a vector collection."""
        try:
            result = await self.qdrant_client.delete_collection(collection_name)

            logger.info("Deleted vector collection", name=collection_name)
            return result

        except Exception as e:
            logger.exception(
                "Failed to delete collection", name=collection_name, error=str(e)
            )
            raise VectorServiceError(
                f"Failed to delete collection {collection_name}: {e}"
            ) from e

    async def list_collections(self) -> CollectionListResponse:
        """List all vector collections."""
        try:
            collections = await self.qdrant_client.list_collections()

            total_points = sum(c.points_count for c in collections)

            return CollectionListResponse(
                collections=collections,
                total_collections=len(collections),
                total_points=total_points,
            )

        except Exception as e:
            logger.exception("Failed to list collections", error=str(e))
            raise VectorServiceError(f"Failed to list collections: {e}") from e

    async def store_vector(self, request: VectorStoreRequest) -> VectorStoreResponse:
        """Store text as vector with embedding generation."""
        start_time = time.time()

        try:
            # Generate embedding
            embedding_start = time.time()
            embeddings, model_info = await self.embedding_service.generate_embeddings(
                [request.content],
                model_name=request.embedding_model,
                use_cache=self.config.enable_caching,
            )
            embedding_time = (time.time() - embedding_start) * 1000

            embedding = embeddings[0]
            vector_id = uuid.uuid4().hex

            # Create payload
            payload = VectorPayload(
                content=request.content,
                content_type=request.content_type,
                source=request.source,
                tags=request.tags,
                metadata=request.metadata,
            )

            # Create point
            point = models.PointStruct(
                id=vector_id, vector=embedding, payload=payload.dict()
            )

            # Store in Qdrant
            storage_start = time.time()
            await self.qdrant_client.upsert_points(
                collection_name=request.collection_name, points=[point], wait=True
            )
            storage_time = (time.time() - storage_start) * 1000

            # Update statistics
            self._stats["embeddings_generated"] += 1
            self._stats["vectors_stored"] += 1

            total_time = (time.time() - start_time) * 1000

            logger.info(
                "Stored vector successfully",
                id=vector_id,
                collection=request.collection_name,
                content_length=len(request.content),
                dimensions=model_info["dimensions"],
                total_time_ms=total_time,
            )

            return VectorStoreResponse(
                id=vector_id,
                collection_name=request.collection_name,
                status="success",
                embedding_time_ms=embedding_time,
                storage_time_ms=storage_time,
                vector_dimensions=model_info["dimensions"],
            )

        except Exception as e:
            logger.exception(
                "Failed to store vector",
                collection=request.collection_name,
                content_length=len(request.content),
                error=str(e),
            )
            raise VectorServiceError(f"Failed to store vector: {e}") from e

    async def search_vectors(
        self, request: VectorSearchRequest
    ) -> VectorSearchResponse:
        """Perform semantic vector search."""
        start_time = time.time()

        try:
            # Generate query embedding
            embeddings, model_info = await self.embedding_service.generate_embeddings(
                [request.query], use_cache=self.config.enable_caching
            )
            query_vector = embeddings[0]

            # Configure search parameters based on mode
            search_params = None
            if request.mode == SearchMode.EXACT:
                search_params = models.SearchParams(exact=True)
            elif request.mode == SearchMode.SEMANTIC:
                search_params = models.SearchParams(hnsw_ef=128, exact=False)
            elif request.mode == SearchMode.HYBRID:
                search_params = models.SearchParams(hnsw_ef=256, exact=False)

            # Build filters if provided
            query_filter = None
            if request.filters:
                filter_conditions = []

                for key, value in request.filters.items():
                    if isinstance(value, dict):
                        # Handle operators like {"gt": 10}
                        for op, op_value in value.items():
                            if op == "eq":
                                filter_conditions.append(
                                    models.FieldCondition(
                                        key=key, match=models.MatchValue(value=op_value)
                                    )
                                )
                            elif op in ["gt", "gte", "lt", "lte"]:
                                filter_conditions.append(
                                    models.FieldCondition(
                                        key=key, range=models.Range(**{op: op_value})
                                    )
                                )
                            elif op == "in":
                                filter_conditions.append(
                                    models.FieldCondition(
                                        key=key, match=models.MatchAny(any=op_value)
                                    )
                                )
                    else:
                        # Simple equality
                        filter_conditions.append(
                            models.FieldCondition(
                                key=key, match=models.MatchValue(value=value)
                            )
                        )

                if filter_conditions:
                    query_filter = models.Filter(must=filter_conditions)

            # Perform search
            search_start = time.time()
            results = await self.qdrant_client.search_points(
                collection_name=request.collection_name,
                query_vector=query_vector,
                limit=request.limit,
                score_threshold=request.score_threshold
                if request.score_threshold > 0
                else None,
                query_filter=query_filter,
                search_params=search_params,
                with_payload=request.include_payload,
                with_vectors=request.include_vectors,
            )
            search_time = (time.time() - search_start) * 1000

            # Convert results
            search_results = []
            for result in results:
                payload = None
                if request.include_payload and result.payload:
                    try:
                        payload = VectorPayload(**result.payload)
                    except Exception as e:
                        logger.warning(
                            "Failed to parse payload", point_id=result.id, error=str(e)
                        )

                search_results.append(
                    VectorSearchResult(
                        id=str(result.id),
                        score=result.score,
                        payload=payload,
                        vector=result.vector if request.include_vectors else None,
                    )
                )

            # Update statistics
            self._stats["searches_performed"] += 1
            self._stats["total_search_time_ms"] += search_time

            total_time = (time.time() - start_time) * 1000

            logger.info(
                "Vector search completed",
                collection=request.collection_name,
                query_length=len(request.query),
                results_count=len(search_results),
                mode=request.mode.value,
                search_time_ms=search_time,
                total_time_ms=total_time,
            )

            return VectorSearchResponse(
                query=request.query,
                collection_name=request.collection_name,
                results=search_results,
                total_found=len(search_results),
                search_time_ms=search_time,
                mode=request.mode,
            )

        except Exception as e:
            logger.exception(
                "Vector search failed",
                collection=request.collection_name,
                query_length=len(request.query),
                error=str(e),
            )
            raise VectorServiceError(f"Vector search failed: {e}") from e

    async def delete_vectors(self, collection_name: str, vector_ids: list[str]) -> bool:
        """Delete vectors by IDs."""
        try:
            result = await self.qdrant_client.delete_points(
                collection_name=collection_name, point_ids=vector_ids, wait=True
            )

            logger.info(
                "Deleted vectors", collection=collection_name, count=len(vector_ids)
            )

            return result

        except Exception as e:
            logger.exception(
                "Failed to delete vectors",
                collection=collection_name,
                ids_count=len(vector_ids),
                error=str(e),
            )
            raise VectorServiceError(f"Failed to delete vectors: {e}") from e

    async def generate_embeddings(self, request: EmbeddingRequest) -> EmbeddingResponse:
        """Generate embeddings for texts."""
        try:
            embeddings, model_info = await self.embedding_service.generate_embeddings(
                texts=request.texts,
                model_name=request.model,
                normalize=request.normalize,
                use_cache=self.config.enable_caching,
            )

            # Update statistics
            self._stats["embeddings_generated"] += len(request.texts)

            logger.debug(
                "Generated embeddings",
                texts_count=len(request.texts),
                model=model_info["model"],
                dimensions=model_info["dimensions"],
            )

            return EmbeddingResponse(
                embeddings=embeddings,
                model=model_info["model"],
                dimensions=model_info["dimensions"],
                processing_time_ms=model_info["processing_time_ms"],
            )

        except Exception as e:
            logger.exception(
                "Failed to generate embeddings",
                texts_count=len(request.texts),
                error=str(e),
            )
            raise VectorServiceError(f"Failed to generate embeddings: {e}") from e

    async def get_collection_stats(self, collection_name: str) -> dict[str, Any]:
        """Get statistics for a specific collection."""
        try:
            info = await self.qdrant_client.get_collection_info(collection_name)

            return {
                "name": info.name,
                "points_count": info.points_count,
                "indexed_vectors_count": info.indexed_vectors_count,
                "segments_count": info.segments_count,
                "disk_usage_bytes": info.disk_data_size,
                "ram_usage_bytes": info.ram_data_size,
                "vector_size": info.vector_size,
                "distance_metric": info.distance.value,
            }

        except Exception as e:
            logger.exception(
                "Failed to get collection stats",
                collection=collection_name,
                error=str(e),
            )
            raise VectorServiceError(f"Failed to get collection stats: {e}") from e

    async def get_service_stats(self) -> VectorStats:
        """Get comprehensive service statistics."""
        try:
            collections = await self.qdrant_client.list_collections()

            total_disk_usage = sum(c.disk_data_size for c in collections)
            total_ram_usage = sum(c.ram_data_size for c in collections)
            total_vectors = sum(c.points_count for c in collections)

            avg_search_time = 0.0
            if self._stats["searches_performed"] > 0:
                avg_search_time = (
                    self._stats["total_search_time_ms"]
                    / self._stats["searches_performed"]
                )

            return VectorStats(
                total_collections=len(collections),
                total_vectors=total_vectors,
                total_disk_usage=total_disk_usage,
                total_ram_usage=total_ram_usage,
                average_search_time_ms=avg_search_time,
                embeddings_generated=self._stats["embeddings_generated"],
                last_updated=time.time(),
            )

        except Exception as e:
            logger.exception("Failed to get service stats", error=str(e))
            raise VectorServiceError(f"Failed to get service stats: {e}") from e

    async def health_check(self) -> HealthCheckResult:
        """Perform comprehensive health check."""
        start_time = time.time()

        try:
            # Check Qdrant health
            qdrant_health = await self.qdrant_client.get_health_status()

            # Test embedding generation
            try:
                await self.embedding_service.generate_embeddings(
                    ["health check test"], use_cache=False
                )
                embedding_health = True
            except Exception:
                embedding_health = False

            response_time = (time.time() - start_time) * 1000

            status = (
                "healthy"
                if (qdrant_health.get("status") == "healthy" and embedding_health)
                else "unhealthy"
            )

            return HealthCheckResult(
                service="vector",
                status=status,
                response_time_ms=response_time,
                details={
                    "qdrant": qdrant_health,
                    "embedding_service": embedding_health,
                    "default_collection": self.config.default_collection,
                    "cache_enabled": self.config.enable_caching,
                },
            )

        except Exception as e:
            response_time = (time.time() - start_time) * 1000

            return HealthCheckResult(
                service="vector",
                status="unhealthy",
                response_time_ms=response_time,
                details={
                    "error": str(e),
                    "error_type": type(e).__name__,
                },
            )
