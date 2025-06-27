"""
Performance and load testing for the Unified MCP Intelligence Server.

This module provides comprehensive performance benchmarking, load testing,
and validation to ensure production readiness and scalability under various
load conditions.

Key Features:
- Concurrent request load testing with realistic patterns
- Memory usage validation and leak detection
- Response time benchmarking with SLA compliance
- Service capacity limits and scaling characteristics
- Resource utilization monitoring during sustained load
- Performance regression detection across different load patterns
"""

import asyncio
from dataclasses import dataclass, field
from datetime import datetime
import gc
import json
import os
import statistics
import time
from typing import Any

import httpx
import psutil
import pytest

from qdrant_neo4j_crawl4ai_mcp.config import Settings
from qdrant_neo4j_crawl4ai_mcp.main import create_app


@dataclass
class PerformanceMetrics:
    """Performance metrics collection for benchmarking."""

    test_name: str
    total_requests: int = 0
    successful_requests: int = 0
    failed_requests: int = 0
    start_time: float = field(default_factory=time.time)
    end_time: float | None = None
    response_times: list[float] = field(default_factory=list)
    memory_usage_mb: list[float] = field(default_factory=list)
    cpu_usage_percent: list[float] = field(default_factory=list)
    error_details: list[str] = field(default_factory=list)

    @property
    def duration_seconds(self) -> float:
        """Total test duration in seconds."""
        if self.end_time is None:
            return time.time() - self.start_time
        return self.end_time - self.start_time

    @property
    def requests_per_second(self) -> float:
        """Calculate requests per second."""
        if self.duration_seconds == 0:
            return 0.0
        return self.total_requests / self.duration_seconds

    @property
    def success_rate(self) -> float:
        """Calculate success rate percentage."""
        if self.total_requests == 0:
            return 0.0
        return (self.successful_requests / self.total_requests) * 100

    @property
    def avg_response_time_ms(self) -> float:
        """Average response time in milliseconds."""
        if not self.response_times:
            return 0.0
        return statistics.mean(self.response_times) * 1000

    @property
    def p95_response_time_ms(self) -> float:
        """95th percentile response time in milliseconds."""
        if not self.response_times:
            return 0.0
        sorted_times = sorted(self.response_times)
        p95_index = int(0.95 * len(sorted_times))
        return sorted_times[p95_index] * 1000

    @property
    def p99_response_time_ms(self) -> float:
        """99th percentile response time in milliseconds."""
        if not self.response_times:
            return 0.0
        sorted_times = sorted(self.response_times)
        p99_index = int(0.99 * len(sorted_times))
        return sorted_times[p99_index] * 1000

    @property
    def max_memory_usage_mb(self) -> float:
        """Maximum memory usage during test."""
        if not self.memory_usage_mb:
            return 0.0
        return max(self.memory_usage_mb)

    @property
    def avg_cpu_usage_percent(self) -> float:
        """Average CPU usage during test."""
        if not self.cpu_usage_percent:
            return 0.0
        return statistics.mean(self.cpu_usage_percent)

    def finish(self):
        """Mark test as finished and record end time."""
        self.end_time = time.time()

    def add_request_result(
        self, success: bool, response_time: float, error: str | None = None
    ):
        """Add a request result to metrics."""
        self.total_requests += 1
        if success:
            self.successful_requests += 1
        else:
            self.failed_requests += 1
            if error:
                self.error_details.append(error)

        self.response_times.append(response_time)

    def record_system_metrics(self):
        """Record current system resource usage."""
        process = psutil.Process()

        # Memory usage in MB
        memory_info = process.memory_info()
        memory_mb = memory_info.rss / (1024 * 1024)
        self.memory_usage_mb.append(memory_mb)

        # CPU usage percentage
        cpu_percent = process.cpu_percent()
        self.cpu_usage_percent.append(cpu_percent)


@pytest.fixture
def performance_test_settings():
    """Settings optimized for performance testing."""
    return Settings(
        environment="testing",
        debug=False,
        log_level="WARNING",
        enable_swagger_ui=False,
        enable_redoc=False,
        workers=1,
        # Optimized timeouts for performance testing
        connection_timeout=30,
        max_retries=1,
        retry_delay=0.1,
        # Memory optimizations
        enable_caching=True,
        # Auth settings for testing
        jwt_secret_key="test-performance-secret-key-for-benchmarks",
        jwt_expire_minutes=60,
    )


@pytest.fixture
async def performance_test_app(performance_test_settings):
    """Create optimized app for performance testing."""
    return create_app(performance_test_settings)


@pytest.fixture
async def performance_client(performance_test_app):
    """HTTP client for performance testing."""
    async with httpx.AsyncClient(
        app=performance_test_app,
        base_url="http://test",
        timeout=30.0,
        limits=httpx.Limits(
            max_keepalive_connections=100, max_connections=200, keepalive_expiry=30.0
        ),
    ) as client:
        yield client


@pytest.fixture
def auth_token(performance_client):
    """Create authentication token for performance tests."""

    async def _create_token():
        response = await performance_client.post(
            "/auth/token",
            json={"username": "performance_user", "scopes": ["read", "write"]},
        )
        assert response.status_code == 200
        return response.json()["access_token"]

    return _create_token


@pytest.fixture
def auth_headers_factory(auth_token):
    """Factory for creating auth headers."""

    async def _create_headers():
        token = await auth_token()
        return {"Authorization": f"Bearer {token}"}

    return _create_headers


class TestConcurrentLoadPatterns:
    """Test various concurrent load patterns and capacity limits."""

    @pytest.mark.performance
    @pytest.mark.slow
    async def test_concurrent_health_check_load(
        self, performance_client: httpx.AsyncClient
    ):
        """Test health check endpoint under high concurrent load."""
        metrics = PerformanceMetrics("concurrent_health_check_load")

        async def single_health_check():
            start_time = time.time()
            try:
                response = await performance_client.get("/health")
                end_time = time.time()
                success = response.status_code == 200
                metrics.add_request_result(success, end_time - start_time)
                return success
            except Exception as e:
                end_time = time.time()
                metrics.add_request_result(False, end_time - start_time, str(e))
                return False

        # Test with increasing concurrency levels
        concurrency_levels = [10, 25, 50, 100]

        for concurrency in concurrency_levels:
            metrics = PerformanceMetrics(f"health_check_concurrency_{concurrency}")

            # Create concurrent tasks
            tasks = [single_health_check() for _ in range(concurrency)]

            # Execute and measure
            time.time()
            await asyncio.gather(*tasks, return_exceptions=True)
            metrics.finish()

            # Record system metrics
            metrics.record_system_metrics()

            # Performance assertions
            assert metrics.success_rate >= 95.0, (
                f"Success rate {metrics.success_rate}% below 95% for concurrency {concurrency}"
            )
            assert metrics.avg_response_time_ms <= 100.0, (
                f"Avg response time {metrics.avg_response_time_ms}ms above 100ms"
            )
            assert metrics.p95_response_time_ms <= 200.0, (
                f"P95 response time {metrics.p95_response_time_ms}ms above 200ms"
            )

            # Memory usage should remain reasonable
            assert metrics.max_memory_usage_mb <= 500.0, (
                f"Memory usage {metrics.max_memory_usage_mb}MB too high"
            )

    @pytest.mark.performance
    async def test_vector_search_load_pattern(
        self, performance_client: httpx.AsyncClient, auth_headers_factory
    ):
        """Test vector search endpoint under realistic load patterns."""
        headers = await auth_headers_factory()
        metrics = PerformanceMetrics("vector_search_load")

        # Various search queries to simulate realistic patterns
        search_queries = [
            "artificial intelligence machine learning",
            "data science analytics",
            "python programming tutorial",
            "web development frameworks",
            "database optimization techniques",
            "cloud computing architecture",
            "cybersecurity best practices",
            "mobile app development",
            "devops automation tools",
            "software engineering patterns",
        ]

        async def perform_vector_search(query: str):
            start_time = time.time()
            try:
                response = await performance_client.post(
                    "/api/v1/vector/search",
                    json={"query": query, "mode": "auto", "limit": 10},
                    headers=headers,
                )
                end_time = time.time()
                success = response.status_code == 200
                metrics.add_request_result(success, end_time - start_time)
                return success, response
            except Exception as e:
                end_time = time.time()
                metrics.add_request_result(False, end_time - start_time, str(e))
                return False, None

        # Simulate realistic traffic pattern with burst and sustained load
        burst_tasks = []
        for _ in range(50):  # Burst of 50 concurrent requests
            query = search_queries[_ % len(search_queries)]
            burst_tasks.append(perform_vector_search(query))

        # Record system metrics during burst
        initial_memory = psutil.Process().memory_info().rss / (1024 * 1024)

        # Execute burst load
        await asyncio.gather(*burst_tasks, return_exceptions=True)

        # Record post-burst metrics
        metrics.record_system_metrics()

        # Sustained load pattern
        for batch in range(5):  # 5 batches of sustained load
            batch_tasks = []
            for _ in range(20):  # 20 requests per batch
                query = search_queries[(_ + batch) % len(search_queries)]
                batch_tasks.append(perform_vector_search(query))

            # Execute batch with slight delay between batches
            await asyncio.gather(*batch_tasks, return_exceptions=True)
            await asyncio.sleep(0.1)  # 100ms between batches

            # Record metrics during sustained load
            metrics.record_system_metrics()

        metrics.finish()

        # Performance SLA validations
        assert metrics.success_rate >= 90.0, (
            f"Vector search success rate {metrics.success_rate}% below 90%"
        )
        assert metrics.avg_response_time_ms <= 500.0, (
            f"Avg response time {metrics.avg_response_time_ms}ms above 500ms"
        )
        assert metrics.p95_response_time_ms <= 1000.0, (
            f"P95 response time {metrics.p95_response_time_ms}ms above 1s"
        )
        assert metrics.p99_response_time_ms <= 2000.0, (
            f"P99 response time {metrics.p99_response_time_ms}ms above 2s"
        )

        # Memory growth validation
        memory_growth = metrics.max_memory_usage_mb - initial_memory
        assert memory_growth <= 100.0, (
            f"Memory growth {memory_growth}MB excessive during load test"
        )

    @pytest.mark.performance
    async def test_mixed_endpoint_load_simulation(
        self, performance_client: httpx.AsyncClient, auth_headers_factory
    ):
        """Test mixed endpoint load simulation mimicking real-world usage."""
        headers = await auth_headers_factory()
        metrics = PerformanceMetrics("mixed_endpoint_load")

        async def health_check_request():
            start_time = time.time()
            try:
                response = await performance_client.get("/health")
                end_time = time.time()
                success = response.status_code == 200
                metrics.add_request_result(success, end_time - start_time)
                return "health", success
            except Exception as e:
                end_time = time.time()
                metrics.add_request_result(False, end_time - start_time, str(e))
                return "health", False

        async def vector_search_request():
            start_time = time.time()
            try:
                response = await performance_client.post(
                    "/api/v1/vector/search",
                    json={"query": "test search query", "mode": "vector", "limit": 5},
                    headers=headers,
                )
                end_time = time.time()
                success = response.status_code == 200
                metrics.add_request_result(success, end_time - start_time)
                return "vector_search", success
            except Exception as e:
                end_time = time.time()
                metrics.add_request_result(False, end_time - start_time, str(e))
                return "vector_search", False

        async def intelligence_query_request():
            start_time = time.time()
            try:
                response = await performance_client.post(
                    "/api/v1/intelligence/query",
                    json={
                        "query": "test intelligence query",
                        "mode": "auto",
                        "limit": 10,
                    },
                    headers=headers,
                )
                end_time = time.time()
                success = response.status_code == 200
                metrics.add_request_result(success, end_time - start_time)
                return "intelligence", success
            except Exception as e:
                end_time = time.time()
                metrics.add_request_result(False, end_time - start_time, str(e))
                return "intelligence", False

        async def user_profile_request():
            start_time = time.time()
            try:
                response = await performance_client.get(
                    "/api/v1/profile", headers=headers
                )
                end_time = time.time()
                success = response.status_code == 200
                metrics.add_request_result(success, end_time - start_time)
                return "profile", success
            except Exception as e:
                end_time = time.time()
                metrics.add_request_result(False, end_time - start_time, str(e))
                return "profile", False

        # Realistic traffic mix distribution (based on typical API usage patterns)
        request_mix = [
            (health_check_request, 30),  # 30% health checks (monitoring)
            (vector_search_request, 40),  # 40% vector searches (primary feature)
            (intelligence_query_request, 25),  # 25% intelligence queries
            (user_profile_request, 5),  # 5% profile requests
        ]

        # Generate mixed load pattern
        mixed_tasks = []
        total_requests = 200

        for request_func, percentage in request_mix:
            request_count = int((percentage / 100) * total_requests)
            for _ in range(request_count):
                mixed_tasks.append(request_func())

        # Randomize request order to simulate real traffic
        import random

        random.shuffle(mixed_tasks)

        # Execute mixed load with batching to avoid overwhelming
        batch_size = 25
        endpoint_results = {
            "health": [],
            "vector_search": [],
            "intelligence": [],
            "profile": [],
        }

        for i in range(0, len(mixed_tasks), batch_size):
            batch = mixed_tasks[i : i + batch_size]

            # Record system metrics
            metrics.record_system_metrics()

            # Execute batch
            batch_results = await asyncio.gather(*batch, return_exceptions=True)

            # Categorize results by endpoint
            for result in batch_results:
                if isinstance(result, tuple):
                    endpoint, success = result
                    endpoint_results[endpoint].append(success)

            # Small delay between batches to simulate realistic request spacing
            await asyncio.sleep(0.05)  # 50ms between batches

        metrics.finish()

        # Overall performance validation
        assert metrics.success_rate >= 90.0, (
            f"Mixed load success rate {metrics.success_rate}% below 90%"
        )
        assert metrics.avg_response_time_ms <= 400.0, (
            f"Mixed load avg response time {metrics.avg_response_time_ms}ms above 400ms"
        )
        assert metrics.requests_per_second >= 5.0, (
            f"Throughput {metrics.requests_per_second} RPS below minimum 5 RPS"
        )

        # Per-endpoint success rate validation
        for endpoint, results in endpoint_results.items():
            if results:
                success_rate = (sum(results) / len(results)) * 100
                assert success_rate >= 85.0, (
                    f"{endpoint} success rate {success_rate}% below 85%"
                )

        # Resource usage validation
        assert metrics.max_memory_usage_mb <= 1000.0, (
            f"Memory usage {metrics.max_memory_usage_mb}MB too high"
        )
        assert metrics.avg_cpu_usage_percent <= 80.0, (
            f"CPU usage {metrics.avg_cpu_usage_percent}% too high"
        )

        # Print per-endpoint results
        for endpoint, results in endpoint_results.items():
            if results:
                success_rate = (sum(results) / len(results)) * 100


class TestMemoryAndResourceValidation:
    """Test memory usage, resource consumption, and leak detection."""

    @pytest.mark.performance
    @pytest.mark.slow
    async def test_memory_leak_detection_under_sustained_load(
        self, performance_client: httpx.AsyncClient, auth_headers_factory
    ):
        """Test for memory leaks during sustained load over extended period."""
        headers = await auth_headers_factory()
        process = psutil.Process()

        # Baseline memory measurement
        gc.collect()  # Force garbage collection
        baseline_memory = process.memory_info().rss / (1024 * 1024)

        metrics = PerformanceMetrics("memory_leak_detection")
        memory_samples = []

        async def sustained_request_batch():
            """Execute a batch of varied requests."""
            batch_tasks = []

            # Mix of different request types
            for i in range(10):
                if i % 3 == 0:
                    # Health checks
                    batch_tasks.append(performance_client.get("/health"))
                elif i % 3 == 1:
                    # Vector searches
                    batch_tasks.append(
                        performance_client.post(
                            "/api/v1/vector/search",
                            json={"query": f"test query {i}", "limit": 5},
                            headers=headers,
                        )
                    )
                else:
                    # Intelligence queries
                    batch_tasks.append(
                        performance_client.post(
                            "/api/v1/intelligence/query",
                            json={"query": f"intelligence test {i}", "mode": "auto"},
                            headers=headers,
                        )
                    )

            # Execute batch
            responses = await asyncio.gather(*batch_tasks, return_exceptions=True)

            # Count successful requests
            successful = sum(
                1
                for r in responses
                if isinstance(r, httpx.Response) and r.status_code == 200
            )
            return successful, len(batch_tasks)

        # Run sustained load for multiple cycles
        total_cycles = 20

        for cycle in range(total_cycles):
            # Execute request batch
            successful, total = await sustained_request_batch()
            metrics.total_requests += total
            metrics.successful_requests += successful

            # Force garbage collection to detect real leaks
            gc.collect()

            # Sample memory usage
            current_memory = process.memory_info().rss / (1024 * 1024)
            memory_samples.append(current_memory)
            metrics.memory_usage_mb.append(current_memory)

            # Small delay between cycles
            await asyncio.sleep(0.1)

            # Log memory usage every 5 cycles
            if cycle % 5 == 0:
                memory_growth = current_memory - baseline_memory

        metrics.finish()

        # Analyze memory usage patterns
        final_memory = memory_samples[-1]
        max_memory = max(memory_samples)
        statistics.mean(memory_samples)
        memory_growth = final_memory - baseline_memory

        # Memory leak detection thresholds
        assert memory_growth <= 50.0, (
            f"Significant memory growth detected: {memory_growth:.1f}MB"
        )
        assert max_memory <= baseline_memory + 100.0, (
            f"Peak memory usage too high: {max_memory:.1f}MB"
        )

        # Linear regression to detect memory growth trend
        if len(memory_samples) >= 10:
            x_values = list(range(len(memory_samples)))
            n = len(memory_samples)
            sum_x = sum(x_values)
            sum_y = sum(memory_samples)
            sum_xy = sum(x * y for x, y in zip(x_values, memory_samples, strict=False))
            sum_x_squared = sum(x * x for x in x_values)

            # Calculate slope (memory growth rate per cycle)
            slope = (n * sum_xy - sum_x * sum_y) / (n * sum_x_squared - sum_x * sum_x)

            # Slope should be minimal (< 0.5MB per cycle growth)
            assert slope <= 0.5, (
                f"Memory growth trend detected: {slope:.3f}MB per cycle"
            )

    @pytest.mark.performance
    async def test_concurrent_request_resource_limits(
        self, performance_client: httpx.AsyncClient, auth_headers_factory
    ):
        """Test resource consumption under high concurrency."""
        headers = await auth_headers_factory()
        process = psutil.Process()

        # Track resource usage
        initial_memory = process.memory_info().rss / (1024 * 1024)
        initial_open_files = len(process.open_files())

        metrics = PerformanceMetrics("resource_limits_test")

        async def resource_intensive_request():
            """Make a request that potentially uses resources."""
            start_time = time.time()
            try:
                response = await performance_client.post(
                    "/api/v1/vector/search",
                    json={
                        "query": "resource intensive search with complex parameters",
                        "mode": "auto",
                        "limit": 20,
                        "filters": {"complexity": "high", "depth": "maximum"},
                    },
                    headers=headers,
                )
                end_time = time.time()
                success = response.status_code == 200
                metrics.add_request_result(success, end_time - start_time)
                return success
            except Exception as e:
                end_time = time.time()
                metrics.add_request_result(False, end_time - start_time, str(e))
                return False

        # Test with increasing concurrency levels
        concurrency_levels = [20, 50, 100]

        for concurrency in concurrency_levels:
            # Create concurrent tasks
            tasks = [resource_intensive_request() for _ in range(concurrency)]

            # Monitor resources during execution
            time.time()
            results = await asyncio.gather(*tasks, return_exceptions=True)
            time.time()

            # Measure resource usage after concurrent load
            current_memory = process.memory_info().rss / (1024 * 1024)
            current_open_files = len(process.open_files())

            memory_increase = current_memory - initial_memory
            file_increase = current_open_files - initial_open_files

            # Resource usage validation
            assert memory_increase <= 200.0, (
                f"Memory increase {memory_increase}MB too high for concurrency {concurrency}"
            )
            assert file_increase <= 50, (
                f"Open file increase {file_increase} too high for concurrency {concurrency}"
            )

            # Performance validation
            successful_requests = sum(1 for r in results if r is True)
            success_rate = (successful_requests / concurrency) * 100

            assert success_rate >= 80.0, (
                f"Success rate {success_rate}% too low for concurrency {concurrency}"
            )

            # Allow system to recover between tests
            await asyncio.sleep(0.5)
            gc.collect()

        metrics.finish()

        # Final resource cleanup validation
        final_memory = process.memory_info().rss / (1024 * 1024)
        final_open_files = len(process.open_files())

        # Resources should return close to initial levels
        final_memory_increase = final_memory - initial_memory
        final_file_increase = final_open_files - initial_open_files

        assert final_memory_increase <= 100.0, (
            f"Final memory increase {final_memory_increase}MB indicates resource leak"
        )
        assert final_file_increase <= 20, (
            f"Final file handle increase {final_file_increase} indicates resource leak"
        )


class TestPerformanceRegression:
    """Test for performance regressions and SLA compliance."""

    @pytest.mark.performance
    async def test_response_time_sla_compliance(
        self, performance_client: httpx.AsyncClient, auth_headers_factory
    ):
        """Test SLA compliance for response times across different endpoints."""
        headers = await auth_headers_factory()

        # Define SLA requirements (in milliseconds)
        sla_requirements = {
            "health_check": {"avg": 50, "p95": 100, "p99": 200},
            "vector_search": {"avg": 300, "p95": 600, "p99": 1000},
            "intelligence_query": {"avg": 400, "p95": 800, "p99": 1500},
            "user_profile": {"avg": 100, "p95": 200, "p99": 400},
        }

        async def benchmark_endpoint(
            endpoint_name: str, request_func, num_requests: int = 50
        ):
            """Benchmark a specific endpoint."""
            response_times = []
            successful_requests = 0

            for _ in range(num_requests):
                start_time = time.time()
                try:
                    response = await request_func()
                    end_time = time.time()

                    if response.status_code == 200:
                        successful_requests += 1

                    response_time = (end_time - start_time) * 1000  # Convert to ms
                    response_times.append(response_time)

                except Exception:
                    end_time = time.time()
                    response_time = (end_time - start_time) * 1000
                    response_times.append(response_time)

            # Calculate performance metrics
            avg_time = statistics.mean(response_times)
            sorted_times = sorted(response_times)
            p95_time = sorted_times[int(0.95 * len(sorted_times))]
            p99_time = sorted_times[int(0.99 * len(sorted_times))]
            success_rate = (successful_requests / num_requests) * 100

            return {
                "avg_ms": avg_time,
                "p95_ms": p95_time,
                "p99_ms": p99_time,
                "success_rate": success_rate,
                "response_times": response_times,
            }

        # Benchmark each endpoint
        benchmark_results = {}

        # Health check endpoint
        benchmark_results["health_check"] = await benchmark_endpoint(
            "health_check", lambda: performance_client.get("/health")
        )

        # Vector search endpoint
        benchmark_results["vector_search"] = await benchmark_endpoint(
            "vector_search",
            lambda: performance_client.post(
                "/api/v1/vector/search",
                json={"query": "benchmark test query", "limit": 10},
                headers=headers,
            ),
        )

        # Intelligence query endpoint
        benchmark_results["intelligence_query"] = await benchmark_endpoint(
            "intelligence_query",
            lambda: performance_client.post(
                "/api/v1/intelligence/query",
                json={"query": "benchmark intelligence test", "mode": "auto"},
                headers=headers,
            ),
        )

        # User profile endpoint
        benchmark_results["user_profile"] = await benchmark_endpoint(
            "user_profile",
            lambda: performance_client.get("/api/v1/profile", headers=headers),
        )

        # Validate SLA compliance
        for endpoint, results in benchmark_results.items():
            sla = sla_requirements[endpoint]

            # Success rate validation
            assert results["success_rate"] >= 95.0, (
                f"{endpoint} success rate {results['success_rate']:.1f}% below 95%"
            )

            # Average response time SLA
            assert results["avg_ms"] <= sla["avg"], (
                f"{endpoint} avg response time {results['avg_ms']:.1f}ms exceeds SLA {sla['avg']}ms"
            )

            # P95 response time SLA
            assert results["p95_ms"] <= sla["p95"], (
                f"{endpoint} P95 response time {results['p95_ms']:.1f}ms exceeds SLA {sla['p95']}ms"
            )

            # P99 response time SLA
            assert results["p99_ms"] <= sla["p99"], (
                f"{endpoint} P99 response time {results['p99_ms']:.1f}ms exceeds SLA {sla['p99']}ms"
            )

    @pytest.mark.performance
    async def test_throughput_capacity_limits(
        self, performance_client: httpx.AsyncClient, auth_headers_factory
    ):
        """Test system throughput capacity and identify bottlenecks."""
        headers = await auth_headers_factory()

        # Test different request rates to find capacity limits
        target_rps_levels = [5, 10, 20, 30]  # requests per second

        async def sustained_load_test(target_rps: int, duration_seconds: int):
            """Run sustained load test at specific RPS for given duration."""
            metrics = PerformanceMetrics(f"throughput_test_{target_rps}_rps")

            interval = 1.0 / target_rps  # Time between requests
            end_time = time.time() + duration_seconds

            async def timed_request():
                start_time = time.time()
                try:
                    response = await performance_client.post(
                        "/api/v1/vector/search",
                        json={"query": "throughput test query", "limit": 5},
                        headers=headers,
                    )
                    end_time = time.time()
                    success = response.status_code == 200
                    metrics.add_request_result(success, end_time - start_time)
                    return success
                except Exception as e:
                    end_time = time.time()
                    metrics.add_request_result(False, end_time - start_time, str(e))
                    return False

            # Launch requests at target rate
            tasks = []
            next_request_time = time.time()

            while time.time() < end_time:
                # Wait until it's time for the next request
                current_time = time.time()
                if current_time >= next_request_time:
                    tasks.append(asyncio.create_task(timed_request()))
                    next_request_time += interval

                    # Record system metrics periodically
                    if len(tasks) % 10 == 0:
                        metrics.record_system_metrics()
                else:
                    await asyncio.sleep(0.001)  # Small sleep to prevent busy waiting

            # Wait for all requests to complete
            if tasks:
                await asyncio.gather(*tasks, return_exceptions=True)

            metrics.finish()
            return metrics

        # Test throughput at different levels
        throughput_results = {}

        for target_rps in target_rps_levels:
            # Use shorter duration for higher RPS to avoid overwhelming
            test_duration = 15 if target_rps <= 10 else 10

            metrics = await sustained_load_test(target_rps, test_duration)

            throughput_results[target_rps] = {
                "target_rps": target_rps,
                "actual_rps": metrics.requests_per_second,
                "success_rate": metrics.success_rate,
                "avg_response_time_ms": metrics.avg_response_time_ms,
                "p95_response_time_ms": metrics.p95_response_time_ms,
                "max_memory_mb": metrics.max_memory_usage_mb,
                "avg_cpu_percent": metrics.avg_cpu_usage_percent,
            }

            # Basic validation - system should handle reasonable load
            if target_rps <= 20:  # For reasonable load levels
                assert metrics.success_rate >= 90.0, (
                    f"Success rate {metrics.success_rate:.1f}% too low at {target_rps} RPS"
                )
                assert metrics.avg_response_time_ms <= 1000.0, (
                    f"Response time {metrics.avg_response_time_ms:.1f}ms too high at {target_rps} RPS"
                )

            # Allow system to recover between tests
            await asyncio.sleep(2)
            gc.collect()

        # Analyze capacity characteristics
        max_successful_rps = 0
        for target_rps, results in throughput_results.items():
            if results["success_rate"] >= 90.0:
                max_successful_rps = max(max_successful_rps, results["actual_rps"])

        # System should handle at least 10 RPS with good performance
        assert max_successful_rps >= 10.0, (
            f"System capacity {max_successful_rps:.1f} RPS below minimum requirement of 10 RPS"
        )

        # Save detailed results for analysis
        return throughput_results


# Helper function for performance test reporting
def save_performance_report(test_results: dict[str, Any], filename: str | None = None):
    """Save performance test results to JSON file for analysis."""
    if filename is None:
        timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        filename = f"performance_report_{timestamp}.json"

    report_data = {
        "timestamp": datetime.utcnow().isoformat(),
        "test_results": test_results,
        "system_info": {
            "cpu_count": psutil.cpu_count(),
            "total_memory_mb": psutil.virtual_memory().total / (1024 * 1024),
            "python_version": os.sys.version,
            "platform": os.name,
        },
    }

    os.makedirs("performance_reports", exist_ok=True)
    report_path = os.path.join("performance_reports", filename)

    with open(report_path, "w") as f:
        json.dump(report_data, f, indent=2, default=str)

    return report_path


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
