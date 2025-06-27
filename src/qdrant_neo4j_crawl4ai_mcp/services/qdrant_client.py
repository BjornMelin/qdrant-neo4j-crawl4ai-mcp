"""
Async Qdrant client with connection pooling and error handling.

Provides a production-ready interface to Qdrant vector database with
comprehensive retry logic, connection management, and performance optimization.
"""

import asyncio
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
import time
from typing import Any

from qdrant_client import AsyncQdrantClient, models
from qdrant_client.http.exceptions import ResponseHandlingException, UnexpectedResponse
import structlog

from qdrant_neo4j_crawl4ai_mcp.models.vector_models import (
    CollectionConfig,
    CollectionInfo,
    CollectionStatus,
    VectorDistance,
    VectorQuantization,
    VectorServiceConfig,
)

logger = structlog.get_logger(__name__)


class QdrantConnectionError(Exception):
    """Qdrant connection-related errors."""


class QdrantOperationError(Exception):
    """Qdrant operation-related errors."""


class QdrantClient:
    """
    Production-ready async Qdrant client with advanced features.

    Features:
    - Connection pooling and reuse
    - Automatic retry with exponential backoff
    - Health monitoring and circuit breaker pattern
    - Performance optimization for batch operations
    - Comprehensive error handling and logging
    """

    def __init__(self, config: VectorServiceConfig) -> None:
        """
        Initialize Qdrant client with configuration.

        Args:
            config: Vector service configuration
        """
        self.config = config
        self._client: AsyncQdrantClient | None = None
        self._connection_pool_size = 10
        self._health_check_interval = 30
        self._last_health_check = 0.0
        self._is_healthy = True
        self._retry_count = 0
        self._circuit_breaker_threshold = 5
        self._circuit_breaker_reset_time = 60
        self._last_failure_time = 0.0

        logger.info(
            "Qdrant client initialized",
            url=config.qdrant_url,
            timeout=config.connection_timeout,
            max_retries=config.max_retries,
        )

    async def __aenter__(self) -> "QdrantClient":
        """Async context manager entry."""
        await self.connect()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        """Async context manager exit."""
        await self.disconnect()

    async def connect(self) -> None:
        """Establish connection to Qdrant server."""
        try:
            # Parse URL and configure client
            url_parts = self.config.qdrant_url.replace("http://", "").replace(
                "https://", ""
            )
            if ":" in url_parts:
                host, port = url_parts.split(":")
                port = int(port)
            else:
                host = url_parts
                port = 6333

            # Create client with optimal settings
            self._client = AsyncQdrantClient(
                host=host,
                port=port,
                api_key=self.config.qdrant_api_key,
                https="https" in self.config.qdrant_url,
                timeout=self.config.connection_timeout,
                # Connection pooling settings
                limits=models.Limits(
                    max_connections=self._connection_pool_size,
                    max_keepalive_connections=5,
                    keepalive_expiry=30.0,
                ),
            )

            # Verify connection with health check
            await self._health_check()

            logger.info(
                "Qdrant client connected successfully",
                host=host,
                port=port,
                https="https" in self.config.qdrant_url,
            )

        except Exception as e:
            self._is_healthy = False
            logger.exception(
                "Failed to connect to Qdrant",
                error=str(e),
                error_type=type(e).__name__,
                url=self.config.qdrant_url,
            )
            raise QdrantConnectionError(f"Failed to connect to Qdrant: {e}") from e

    async def disconnect(self) -> None:
        """Close connection to Qdrant server."""
        if self._client:
            try:
                await self._client.close()
                logger.info("Qdrant client disconnected")
            except Exception as e:
                logger.warning("Error during Qdrant disconnect", error=str(e))
            finally:
                self._client = None

    async def _ensure_connected(self) -> None:
        """Ensure client is connected and healthy."""
        if not self._client:
            await self.connect()

        # Check circuit breaker
        if not self._is_healthy:
            if time.time() - self._last_failure_time < self._circuit_breaker_reset_time:
                raise QdrantConnectionError("Circuit breaker open - Qdrant unavailable")
            # Try to reset circuit breaker
            await self._health_check()

        # Periodic health check
        if time.time() - self._last_health_check > self._health_check_interval:
            await self._health_check()

    async def _health_check(self) -> bool:
        """Perform health check on Qdrant connection."""
        try:
            if not self._client:
                return False

            # Simple health check - get collections
            await self._client.get_collections()

            self._is_healthy = True
            self._last_health_check = time.time()
            self._retry_count = 0

            logger.debug("Qdrant health check passed")
            return True

        except Exception as e:
            self._is_healthy = False
            self._last_failure_time = time.time()

            logger.warning(
                "Qdrant health check failed", error=str(e), error_type=type(e).__name__
            )
            return False

    async def _execute_with_retry(self, operation, *args, **kwargs) -> Any:
        """Execute operation with retry logic and circuit breaker."""
        await self._ensure_connected()

        last_exception = None

        for attempt in range(self.config.max_retries + 1):
            try:
                result = await operation(*args, **kwargs)

                # Reset failure count on success
                self._retry_count = 0
                return result

            except (
                ResponseHandlingException,
                UnexpectedResponse,
                ConnectionError,
            ) as e:
                last_exception = e
                self._retry_count += 1

                if attempt < self.config.max_retries:
                    delay = self.config.retry_delay * (
                        2**attempt
                    )  # Exponential backoff

                    logger.warning(
                        "Qdrant operation failed, retrying",
                        attempt=attempt + 1,
                        max_retries=self.config.max_retries,
                        delay=delay,
                        error=str(e),
                    )

                    await asyncio.sleep(delay)

                    # Try to reconnect if connection failed
                    if isinstance(e, ConnectionError):
                        try:
                            await self.disconnect()
                            await self.connect()
                        except Exception as reconnect_error:
                            logger.exception(
                                "Failed to reconnect to Qdrant",
                                error=str(reconnect_error),
                            )
                # Circuit breaker logic
                elif self._retry_count >= self._circuit_breaker_threshold:
                    self._is_healthy = False
                    self._last_failure_time = time.time()

                    logger.exception(
                        "Circuit breaker triggered for Qdrant",
                        retry_count=self._retry_count,
                        threshold=self._circuit_breaker_threshold,
                    )

        # All retries exhausted
        raise QdrantOperationError(
            f"Operation failed after {self.config.max_retries} retries: {last_exception}"
        ) from last_exception

    async def create_collection(
        self, config: CollectionConfig, recreate_if_exists: bool = False
    ) -> bool:
        """
        Create a new vector collection.

        Args:
            config: Collection configuration
            recreate_if_exists: Whether to recreate if collection exists

        Returns:
            True if created successfully
        """

        async def _create_collection():
            # Check if collection exists
            collections = await self._client.get_collections()
            exists = any(c.name == config.name for c in collections.collections)

            if exists and not recreate_if_exists:
                logger.info(f"Collection {config.name} already exists")
                return True

            if exists and recreate_if_exists:
                await self._client.delete_collection(config.name)
                logger.info(f"Deleted existing collection {config.name}")

            # Configure vector parameters
            vectors_config = models.VectorParams(
                size=config.vector_size,
                distance=getattr(models.Distance, config.distance.value),
            )

            # Configure optimizers
            optimizers_config = models.OptimizersConfig(
                default_segment_number=config.optimizers_config.get(
                    "default_segment_number", 2
                ),
                max_segment_size=config.optimizers_config.get(
                    "max_segment_size", 200000
                ),
                memmap_threshold=config.optimizers_config.get(
                    "memmap_threshold", 100000
                ),
                indexing_threshold=config.optimizers_config.get(
                    "indexing_threshold", 20000
                ),
                flush_interval_sec=config.optimizers_config.get(
                    "flush_interval_sec", 30
                ),
                max_optimization_threads=config.optimizers_config.get(
                    "max_optimization_threads", 2
                ),
            )

            # Configure HNSW index
            hnsw_config = models.HnswConfig(
                m=config.hnsw_config.get("m", 16),
                ef_construct=config.hnsw_config.get("ef_construct", 100),
                full_scan_threshold=config.hnsw_config.get(
                    "full_scan_threshold", 10000
                ),
                max_indexing_threads=config.hnsw_config.get("max_indexing_threads", 2),
            )

            # Configure quantization if specified
            quantization_config = None
            if config.quantization != VectorQuantization.NONE:
                if config.quantization == VectorQuantization.INT8:
                    quantization_config = models.QuantizationConfig(
                        scalar=models.ScalarQuantization(
                            type=models.ScalarType.INT8, quantile=0.99, always_ram=False
                        )
                    )

            # Create collection
            result = await self._client.create_collection(
                collection_name=config.name,
                vectors_config=vectors_config,
                shard_number=config.shard_number,
                replication_factor=config.replication_factor,
                optimizers_config=optimizers_config,
                hnsw_config=hnsw_config,
                quantization_config=quantization_config,
                on_disk_payload=True,  # Store payload on disk for memory efficiency
            )

            logger.info(
                "Created Qdrant collection",
                name=config.name,
                vector_size=config.vector_size,
                distance=config.distance.value,
                shards=config.shard_number,
            )

            return result

        return await self._execute_with_retry(_create_collection)

    async def delete_collection(self, collection_name: str) -> bool:
        """Delete a vector collection."""

        async def _delete_collection():
            result = await self._client.delete_collection(collection_name)
            logger.info("Deleted Qdrant collection", name=collection_name)
            return result

        return await self._execute_with_retry(_delete_collection)

    async def get_collection_info(self, collection_name: str) -> CollectionInfo:
        """Get detailed information about a collection."""

        async def _get_collection_info():
            info = await self._client.get_collection(collection_name)

            return CollectionInfo(
                name=collection_name,
                status=CollectionStatus.ACTIVE,  # Assume active if we can get info
                vector_size=info.config.params.vectors.size,
                distance=VectorDistance(info.config.params.vectors.distance.value),
                points_count=info.points_count or 0,
                indexed_vectors_count=info.indexed_vectors_count or 0,
                segments_count=len(info.segments) if info.segments else 0,
                disk_data_size=sum(
                    s.disk_usage_bytes or 0 for s in (info.segments or [])
                ),
                ram_data_size=sum(
                    s.ram_usage_bytes or 0 for s in (info.segments or [])
                ),
                config=info.config.dict() if hasattr(info.config, "dict") else {},
                created_at=info.created_at or time.time(),
                updated_at=time.time(),
            )

        return await self._execute_with_retry(_get_collection_info)

    async def list_collections(self) -> list[CollectionInfo]:
        """List all collections with their information."""

        async def _list_collections():
            collections = await self._client.get_collections()
            result = []

            for collection in collections.collections:
                try:
                    info = await self.get_collection_info(collection.name)
                    result.append(info)
                except Exception as e:
                    logger.warning(
                        "Failed to get collection info",
                        collection=collection.name,
                        error=str(e),
                    )
                    # Add basic info even if detailed info fails
                    result.append(
                        CollectionInfo(
                            name=collection.name,
                            status=CollectionStatus.ERROR,
                            vector_size=0,
                            distance=VectorDistance.COSINE,
                            points_count=0,
                            indexed_vectors_count=0,
                            segments_count=0,
                            disk_data_size=0,
                            ram_data_size=0,
                            config={},
                            created_at=time.time(),
                            updated_at=time.time(),
                        )
                    )

            return result

        return await self._execute_with_retry(_list_collections)

    async def upsert_points(
        self, collection_name: str, points: list[models.PointStruct], wait: bool = True
    ) -> bool:
        """Upsert vector points into collection."""

        async def _upsert_points():
            result = await self._client.upsert(
                collection_name=collection_name, points=points, wait=wait
            )

            logger.debug(
                "Upserted points to Qdrant",
                collection=collection_name,
                count=len(points),
                wait=wait,
            )

            return result

        return await self._execute_with_retry(_upsert_points)

    async def search_points(
        self,
        collection_name: str,
        query_vector: list[float],
        limit: int = 10,
        score_threshold: float | None = None,
        query_filter: models.Filter | None = None,
        search_params: models.SearchParams | None = None,
        with_payload: bool = True,
        with_vectors: bool = False,
    ) -> list[models.ScoredPoint]:
        """Search for similar vectors in collection."""

        async def _search_points():
            # Configure search parameters
            if search_params is None:
                search_params = models.SearchParams(
                    hnsw_ef=128,  # Good balance of speed vs accuracy
                    exact=False,
                )

            result = await self._client.search(
                collection_name=collection_name,
                query_vector=query_vector,
                limit=limit,
                score_threshold=score_threshold,
                query_filter=query_filter,
                search_params=search_params,
                with_payload=with_payload,
                with_vectors=with_vectors,
            )

            logger.debug(
                "Searched Qdrant collection",
                collection=collection_name,
                limit=limit,
                results=len(result),
                threshold=score_threshold,
            )

            return result

        return await self._execute_with_retry(_search_points)

    async def delete_points(
        self, collection_name: str, point_ids: list[str], wait: bool = True
    ) -> bool:
        """Delete points from collection."""

        async def _delete_points():
            result = await self._client.delete(
                collection_name=collection_name,
                points_selector=models.PointIdsList(points=point_ids),
                wait=wait,
            )

            logger.debug(
                "Deleted points from Qdrant",
                collection=collection_name,
                count=len(point_ids),
            )

            return result

        return await self._execute_with_retry(_delete_points)

    async def count_points(self, collection_name: str) -> int:
        """Count total points in collection."""

        async def _count_points():
            result = await self._client.count(
                collection_name=collection_name, exact=True
            )
            return result.count

        return await self._execute_with_retry(_count_points)

    @asynccontextmanager
    async def batch_context(
        self, collection_name: str
    ) -> AsyncGenerator[list[models.PointStruct], None]:
        """Context manager for efficient batch operations."""
        batch_points = []

        try:
            yield batch_points

            # Upsert all collected points in batch
            if batch_points:
                await self.upsert_points(collection_name, batch_points, wait=True)

                logger.info(
                    "Batch upsert completed",
                    collection=collection_name,
                    points=len(batch_points),
                )

        except Exception as e:
            logger.exception(
                "Batch operation failed",
                collection=collection_name,
                points=len(batch_points),
                error=str(e),
            )
            raise

    async def get_health_status(self) -> dict[str, Any]:
        """Get comprehensive health status."""
        try:
            await self._ensure_connected()

            # Get basic info
            collections = await self._client.get_collections()

            # Calculate total statistics
            total_points = 0
            total_collections = len(collections.collections)

            for collection in collections.collections:
                try:
                    count = await self.count_points(collection.name)
                    total_points += count
                except Exception:
                    pass  # Skip failed collections

            return {
                "status": "healthy" if self._is_healthy else "unhealthy",
                "connected": self._client is not None,
                "total_collections": total_collections,
                "total_points": total_points,
                "last_health_check": self._last_health_check,
                "retry_count": self._retry_count,
                "circuit_breaker_open": not self._is_healthy,
                "url": self.config.qdrant_url,
            }

        except Exception as e:
            return {
                "status": "unhealthy",
                "connected": False,
                "error": str(e),
                "error_type": type(e).__name__,
                "url": self.config.qdrant_url,
            }
