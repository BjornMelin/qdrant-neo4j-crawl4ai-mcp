"""
Neo4j database client with async support and production-ready patterns.

Provides optimized connection management, transaction handling, and
GraphRAG integration for the Unified MCP Intelligence Server.
"""

import asyncio
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from datetime import datetime, timedelta
import time
from typing import TYPE_CHECKING, Any

from neo4j import AsyncGraphDatabase, AsyncSession
from neo4j.exceptions import (
    AuthError,
    ConfigurationError,
    TransientError,
)
import structlog

from qdrant_neo4j_crawl4ai_mcp.models.graph_models import (
    CypherQuery,
    CypherResult,
    GraphHealthCheck,
    Neo4jServiceConfig,
)

if TYPE_CHECKING:
    from neo4j import AsyncDriver

logger = structlog.get_logger(__name__)


class Neo4jClient:
    """
    Production-ready Neo4j client with async support and optimal configurations.

    Features:
    - Async connection pooling with retry logic
    - Transaction management with automatic retries
    - Query result caching for performance
    - GraphRAG integration support
    - Comprehensive monitoring and logging
    """

    def __init__(self, config: Neo4jServiceConfig) -> None:
        """
        Initialize Neo4j client with configuration.

        Args:
            config: Neo4j service configuration
        """
        self.config = config
        self.driver: AsyncDriver | None = None
        self._query_cache: dict[str, tuple[Any, datetime]] = {}
        self._connection_healthy = False
        self._last_health_check = datetime.min
        self._query_stats = {
            "total_queries": 0,
            "successful_queries": 0,
            "failed_queries": 0,
            "total_time_ms": 0.0,
            "slow_queries": 0,
        }

        logger.info(
            "Neo4j client initialized",
            uri=config.uri,
            database=config.database,
            max_pool_size=config.max_connection_pool_size,
        )

    async def initialize(self) -> None:
        """Initialize the Neo4j driver and verify connectivity."""
        try:
            self.driver = AsyncGraphDatabase.driver(
                self.config.uri,
                auth=(self.config.username, self.config.password),
                max_connection_pool_size=self.config.max_connection_pool_size,
                connection_acquisition_timeout=self.config.connection_acquisition_timeout,
                max_transaction_retry_time=self.config.max_transaction_retry_time,
                encrypted=self.config.encrypted,
            )

            # Verify connectivity
            await self.verify_connectivity()

            # Initialize schema constraints and indexes
            await self._setup_schema()

            logger.info("Neo4j client initialized successfully")

        except Exception as e:
            logger.exception("Failed to initialize Neo4j client", error=str(e))
            raise

    async def shutdown(self) -> None:
        """Gracefully shutdown the Neo4j driver."""
        if self.driver:
            try:
                await self.driver.close()
                logger.info("Neo4j driver closed successfully")
            except Exception as e:
                logger.warning("Error closing Neo4j driver", error=str(e))
            finally:
                self.driver = None
                self._connection_healthy = False

    async def verify_connectivity(self) -> bool:
        """
        Verify database connectivity with a simple query.

        Returns:
            True if connection is healthy

        Raises:
            Exception if connection fails
        """
        if not self.driver:
            raise RuntimeError("Driver not initialized")

        try:
            async with self.driver.session(database=self.config.database) as session:
                result = await session.run("RETURN 1 as test")
                record = await result.single()

                if record and record["test"] == 1:
                    self._connection_healthy = True
                    self._last_health_check = datetime.utcnow()
                    logger.debug("Neo4j connectivity verified")
                    return True

        except Exception as e:
            self._connection_healthy = False
            logger.exception("Neo4j connectivity check failed", error=str(e))
            raise

        return False

    async def execute_query(
        self, query: CypherQuery, retry_count: int = 3
    ) -> CypherResult:
        """
        Execute a Cypher query with error handling and retries.

        Args:
            query: Cypher query to execute
            retry_count: Number of retries for transient errors

        Returns:
            Query execution result
        """
        if not self.driver:
            raise RuntimeError("Driver not initialized")

        start_time = time.time()
        attempt = 0
        last_error = None

        # Check cache first
        if self.config.enable_query_cache and query.read_only:
            cached_result = self._get_cached_result(query.query, query.parameters)
            if cached_result:
                logger.debug("Returning cached query result")
                return cached_result

        while attempt < retry_count:
            try:
                self._query_stats["total_queries"] += 1

                async with self.driver.session(
                    database=self.config.database
                ) as session:
                    if query.read_only:
                        result = await session.run(
                            query.query,
                            query.parameters,
                            timeout=query.timeout or self.config.default_query_timeout,
                        )
                    else:
                        result = await session.execute_write(
                            self._write_transaction,
                            query.query,
                            query.parameters,
                            query.timeout or self.config.default_query_timeout,
                        )

                    # Collect results
                    records = []
                    async for record in result:
                        records.append(dict(record))

                        if query.limit and len(records) >= query.limit:
                            break

                    # Collect statistics if requested
                    stats = None
                    if query.include_stats:
                        summary = await result.consume()
                        stats = {
                            "nodes_created": summary.counters.nodes_created,
                            "nodes_deleted": summary.counters.nodes_deleted,
                            "relationships_created": summary.counters.relationships_created,
                            "relationships_deleted": summary.counters.relationships_deleted,
                            "properties_set": summary.counters.properties_set,
                            "labels_added": summary.counters.labels_added,
                            "labels_removed": summary.counters.labels_removed,
                            "indexes_added": summary.counters.indexes_added,
                            "indexes_removed": summary.counters.indexes_removed,
                            "constraints_added": summary.counters.constraints_added,
                            "constraints_removed": summary.counters.constraints_removed,
                        }

                execution_time = (time.time() - start_time) * 1000

                result_obj = CypherResult(
                    success=True,
                    records=records,
                    execution_time_ms=execution_time,
                    records_available=len(records),
                    stats=stats,
                )

                # Update statistics
                self._query_stats["successful_queries"] += 1
                self._query_stats["total_time_ms"] += execution_time

                if execution_time > self.config.slow_query_threshold_ms:
                    self._query_stats["slow_queries"] += 1
                    logger.warning(
                        "Slow query detected",
                        execution_time_ms=execution_time,
                        query=query.query[:100] + "..."
                        if len(query.query) > 100
                        else query.query,
                    )

                # Cache result if applicable
                if self.config.enable_query_cache and query.read_only:
                    self._cache_result(query.query, query.parameters, result_obj)

                if self.config.enable_query_logging:
                    logger.debug(
                        "Query executed",
                        execution_time_ms=execution_time,
                        records_count=len(records),
                        read_only=query.read_only,
                    )

                return result_obj

            except TransientError as e:
                attempt += 1
                last_error = e
                wait_time = min(2**attempt, 30)  # Exponential backoff, max 30s

                logger.warning(
                    "Transient error, retrying",
                    attempt=attempt,
                    max_attempts=retry_count,
                    wait_time=wait_time,
                    error=str(e),
                )

                if attempt < retry_count:
                    await asyncio.sleep(wait_time)

            except (AuthError, ConfigurationError) as e:
                # Non-retryable errors
                logger.exception("Non-retryable database error", error=str(e))
                self._query_stats["failed_queries"] += 1

                return CypherResult(
                    success=False,
                    records=[],
                    execution_time_ms=(time.time() - start_time) * 1000,
                    records_available=0,
                    error=str(e),
                    error_code=type(e).__name__,
                )

            except Exception as e:
                attempt += 1
                last_error = e

                logger.exception(
                    "Unexpected query error",
                    attempt=attempt,
                    error=str(e),
                    error_type=type(e).__name__,
                )

                if attempt >= retry_count:
                    break

        # All retries failed
        self._query_stats["failed_queries"] += 1
        execution_time = (time.time() - start_time) * 1000

        logger.error(
            "Query failed after all retries",
            attempts=retry_count,
            final_error=str(last_error),
            execution_time_ms=execution_time,
        )

        return CypherResult(
            success=False,
            records=[],
            execution_time_ms=execution_time,
            records_available=0,
            error=str(last_error),
            error_code=type(last_error).__name__ if last_error else "UnknownError",
        )

    async def execute_batch_queries(
        self, queries: list[CypherQuery]
    ) -> list[CypherResult]:
        """
        Execute multiple queries in parallel with optimal batching.

        Args:
            queries: List of queries to execute

        Returns:
            List of query results
        """
        if not queries:
            return []

        # Separate read and write queries for optimal execution
        read_queries = [q for q in queries if q.read_only]
        write_queries = [q for q in queries if not q.read_only]

        results = []

        # Execute read queries in parallel
        if read_queries:
            read_tasks = [self.execute_query(q) for q in read_queries]
            read_results = await asyncio.gather(*read_tasks, return_exceptions=True)

            for result in read_results:
                if isinstance(result, Exception):
                    results.append(
                        CypherResult(
                            success=False,
                            records=[],
                            execution_time_ms=0,
                            records_available=0,
                            error=str(result),
                            error_code=type(result).__name__,
                        )
                    )
                else:
                    results.append(result)

        # Execute write queries sequentially to maintain consistency
        for query in write_queries:
            result = await self.execute_query(query)
            results.append(result)

        return results

    async def health_check(self) -> GraphHealthCheck:
        """
        Perform comprehensive health check of the Neo4j service.

        Returns:
            Health check result with database statistics
        """
        start_time = time.time()
        errors = []
        warnings = []

        try:
            # Verify connectivity
            await self.verify_connectivity()

            # Get database statistics
            stats_queries = [
                CypherQuery(
                    query="MATCH (n) RETURN count(n) as node_count", read_only=True
                ),
                CypherQuery(
                    query="MATCH ()-[r]->() RETURN count(r) as rel_count",
                    read_only=True,
                ),
                CypherQuery(
                    query="MATCH (n) RETURN labels(n) as labels, count(n) as count",
                    read_only=True,
                ),
                CypherQuery(
                    query="MATCH ()-[r]->() RETURN type(r) as type, count(r) as count",
                    read_only=True,
                ),
            ]

            results = await self.execute_batch_queries(stats_queries)

            # Extract statistics
            total_nodes = (
                results[0].records[0]["node_count"] if results[0].success else 0
            )
            total_relationships = (
                results[1].records[0]["rel_count"] if results[1].success else 0
            )

            # Node types count
            node_types_count = {}
            if results[2].success:
                for record in results[2].records:
                    labels = record["labels"]
                    count = record["count"]
                    if labels:
                        for label in labels:
                            node_types_count[label] = (
                                node_types_count.get(label, 0) + count
                            )

            # Relationship types count
            relationship_types_count = {}
            if results[3].success:
                for record in results[3].records:
                    rel_type = record["type"]
                    count = record["count"]
                    relationship_types_count[rel_type] = count

            # Get version information
            neo4j_version = None
            driver_version = None

            try:
                version_query = CypherQuery(
                    query="CALL dbms.components() YIELD name, versions RETURN name, versions",
                    read_only=True,
                )
                version_result = await self.execute_query(version_query)

                if version_result.success:
                    for record in version_result.records:
                        if record["name"] == "Neo4j Kernel":
                            neo4j_version = record["versions"][0]
                            break

            except Exception as e:
                warnings.append(f"Could not retrieve version info: {e!s}")

            # Calculate average query time
            avg_query_time = None
            if self._query_stats["successful_queries"] > 0:
                avg_query_time = (
                    self._query_stats["total_time_ms"]
                    / self._query_stats["successful_queries"]
                )

            # Check for issues
            if total_nodes == 0:
                warnings.append("Database appears to be empty")

            if self._query_stats["failed_queries"] > 0:
                failure_rate = (
                    self._query_stats["failed_queries"]
                    / self._query_stats["total_queries"]
                )
                if failure_rate > 0.1:  # More than 10% failure rate
                    warnings.append(f"High query failure rate: {failure_rate:.2%}")

            response_time_ms = (time.time() - start_time) * 1000

            return GraphHealthCheck(
                status="healthy" if not errors else "unhealthy",
                database_connected=self._connection_healthy,
                response_time_ms=response_time_ms,
                total_nodes=total_nodes,
                total_relationships=total_relationships,
                node_types_count=node_types_count,
                relationship_types_count=relationship_types_count,
                average_query_time_ms=avg_query_time,
                neo4j_version=neo4j_version,
                driver_version=driver_version,
                errors=errors,
                warnings=warnings,
            )

        except Exception as e:
            logger.exception("Health check failed", error=str(e))
            errors.append(str(e))

            return GraphHealthCheck(
                status="unhealthy",
                database_connected=False,
                response_time_ms=(time.time() - start_time) * 1000,
                total_nodes=0,
                total_relationships=0,
                errors=errors,
                warnings=warnings,
            )

    @asynccontextmanager
    async def session(self, **kwargs) -> AsyncGenerator[AsyncSession, None]:
        """
        Context manager for database sessions.

        Args:
            **kwargs: Additional session parameters

        Yields:
            Neo4j async session
        """
        if not self.driver:
            raise RuntimeError("Driver not initialized")

        async with self.driver.session(
            database=self.config.database, **kwargs
        ) as session:
            yield session

    async def _write_transaction(
        self, tx, query: str, parameters: dict[str, Any], timeout: int | None = None
    ) -> Any:
        """
        Execute a write transaction with the provided query.

        Args:
            tx: Transaction object
            query: Cypher query string
            parameters: Query parameters
            timeout: Query timeout

        Returns:
            Query result
        """
        return await tx.run(query, parameters, timeout=timeout)

    async def _setup_schema(self) -> None:
        """Set up database schema constraints and indexes."""
        try:
            schema_queries = [
                # Unique constraints for core node types
                CypherQuery(
                    query="CREATE CONSTRAINT memory_id IF NOT EXISTS FOR (m:Memory) REQUIRE m.id IS UNIQUE",
                    read_only=False,
                ),
                CypherQuery(
                    query="CREATE CONSTRAINT entity_id IF NOT EXISTS FOR (e:Entity) REQUIRE e.id IS UNIQUE",
                    read_only=False,
                ),
                CypherQuery(
                    query="CREATE CONSTRAINT person_id IF NOT EXISTS FOR (p:Person) REQUIRE p.id IS UNIQUE",
                    read_only=False,
                ),
                # Text indexes for fast lookups
                CypherQuery(
                    query="CREATE TEXT INDEX node_name_idx IF NOT EXISTS FOR (n:Entity) ON (n.name)",
                    read_only=False,
                ),
                CypherQuery(
                    query="CREATE TEXT INDEX memory_name_idx IF NOT EXISTS FOR (m:Memory) ON (m.name)",
                    read_only=False,
                ),
                # Vector indexes for embeddings (Neo4j 5.15+)
                CypherQuery(
                    query="""
                    CREATE VECTOR INDEX entity_embedding_idx IF NOT EXISTS
                    FOR (e:Entity) ON (e.embedding)
                    OPTIONS {
                        indexConfig: {
                            `vector.dimensions`: 1536,
                            `vector.similarity_function`: 'cosine'
                        }
                    }
                    """,
                    read_only=False,
                ),
            ]

            logger.info("Setting up database schema...")

            for query in schema_queries:
                try:
                    result = await self.execute_query(query)
                    if not result.success:
                        logger.warning(
                            "Schema setup query failed",
                            query=query.query[:100],
                            error=result.error,
                        )
                except Exception as e:
                    # Continue with other schema setup even if some fail
                    logger.warning(
                        "Schema setup error", query=query.query[:100], error=str(e)
                    )

            logger.info("Database schema setup completed")

        except Exception as e:
            logger.exception("Failed to setup database schema", error=str(e))
            # Don't raise exception - allow service to start with partial schema

    def _get_cached_result(
        self, query: str, parameters: dict[str, Any]
    ) -> CypherResult | None:
        """Get cached query result if available and not expired."""
        cache_key = self._get_cache_key(query, parameters)

        if cache_key in self._query_cache:
            result, timestamp = self._query_cache[cache_key]

            # Check if cache entry is still valid
            if datetime.utcnow() - timestamp < timedelta(
                seconds=self.config.cache_ttl_seconds
            ):
                return result
            # Remove expired entry
            del self._query_cache[cache_key]

        return None

    def _cache_result(
        self, query: str, parameters: dict[str, Any], result: CypherResult
    ) -> None:
        """Cache query result with timestamp."""
        cache_key = self._get_cache_key(query, parameters)
        self._query_cache[cache_key] = (result, datetime.utcnow())

        # Simple cache cleanup - remove oldest entries if cache is too large
        if len(self._query_cache) > 1000:
            oldest_keys = sorted(
                self._query_cache.keys(), key=lambda k: self._query_cache[k][1]
            )[:100]

            for key in oldest_keys:
                del self._query_cache[key]

    def _get_cache_key(self, query: str, parameters: dict[str, Any]) -> str:
        """Generate cache key from query and parameters."""
        import hashlib
        import json

        # Create deterministic string representation
        param_str = json.dumps(parameters, sort_keys=True, default=str)
        cache_string = f"{query}:{param_str}"

        # Return hash of the string
        return hashlib.md5(cache_string.encode()).hexdigest()

    def get_statistics(self) -> dict[str, Any]:
        """Get client performance statistics."""
        stats = self._query_stats.copy()

        # Calculate derived metrics
        if stats["total_queries"] > 0:
            stats["success_rate"] = stats["successful_queries"] / stats["total_queries"]
            stats["failure_rate"] = stats["failed_queries"] / stats["total_queries"]
            stats["average_time_ms"] = stats["total_time_ms"] / stats["total_queries"]
        else:
            stats["success_rate"] = 0.0
            stats["failure_rate"] = 0.0
            stats["average_time_ms"] = 0.0

        stats["cache_size"] = len(self._query_cache)
        stats["connection_healthy"] = self._connection_healthy
        stats["last_health_check"] = self._last_health_check.isoformat()

        return stats

    def clear_cache(self) -> None:
        """Clear query result cache."""
        self._query_cache.clear()
        logger.info("Query cache cleared")

    def reset_statistics(self) -> None:
        """Reset performance statistics."""
        self._query_stats = {
            "total_queries": 0,
            "successful_queries": 0,
            "failed_queries": 0,
            "total_time_ms": 0.0,
            "slow_queries": 0,
        }
        logger.info("Performance statistics reset")
