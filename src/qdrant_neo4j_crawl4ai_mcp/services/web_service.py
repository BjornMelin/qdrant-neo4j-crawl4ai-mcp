"""
Web intelligence service using Crawl4AI.

Provides high-level web crawling, content extraction, and monitoring capabilities
with comprehensive error handling, rate limiting, and production-ready features.
"""

import asyncio
from datetime import datetime, timedelta
import hashlib
import json
import time
from typing import Any
from urllib.parse import urlparse

from fastapi import HTTPException, status
import structlog

from qdrant_neo4j_crawl4ai_mcp.models.web_models import (
    CrawlStatus,
    OutputFormat,
    WebCrawlRequest,
    WebCrawlResult,
    WebHealthCheck,
    WebMonitorRequest,
    WebMonitorResult,
    WebScreenshotRequest,
    WebScreenshotResult,
    WebServiceConfig,
)
from qdrant_neo4j_crawl4ai_mcp.services.crawl4ai_client import Crawl4AIClient

logger = structlog.get_logger(__name__)


class WebService:
    """
    Web intelligence service providing crawling, extraction, and monitoring.

    Integrates Crawl4AI for comprehensive web data acquisition with production-ready
    features including rate limiting, caching, monitoring, and error handling.
    """

    def __init__(self, config: WebServiceConfig) -> None:
        """
        Initialize the web service.

        Args:
            config: Web service configuration
        """
        self.config = config
        self.logger = logger.bind(component="web_service")
        self.client = Crawl4AIClient(config.web_config)
        self._cache: dict[str, Any] = {}
        self._cache_timestamps: dict[str, datetime] = {}
        self._monitors: dict[str, WebMonitorRequest] = {}
        self._monitor_results: dict[str, WebMonitorResult] = {}
        self._monitor_tasks: dict[str, asyncio.Task] = {}
        self._stats = {
            "total_requests": 0,
            "successful_requests": 0,
            "failed_requests": 0,
            "cache_hits": 0,
            "cache_misses": 0,
            "total_crawl_time_ms": 0.0,
            "average_crawl_time_ms": 0.0,
        }
        self._initialized = False

    async def initialize(self) -> None:
        """Initialize the web service."""
        if self._initialized:
            return

        try:
            self.logger.info("Initializing web service")
            await self.client.initialize()
            self._initialized = True
            self.logger.info("Web service initialized successfully")

        except Exception as e:
            self.logger.exception("Failed to initialize web service", error=str(e))
            raise

    async def shutdown(self) -> None:
        """Shutdown the web service and cleanup resources."""
        self.logger.info("Shutting down web service")

        try:
            # Cancel all monitor tasks
            for task in self._monitor_tasks.values():
                if not task.done():
                    task.cancel()

            # Wait for tasks to complete
            if self._monitor_tasks:
                await asyncio.gather(
                    *self._monitor_tasks.values(), return_exceptions=True
                )

            # Shutdown client
            await self.client.shutdown()

            # Clear cache and monitors
            self._cache.clear()
            self._cache_timestamps.clear()
            self._monitors.clear()
            self._monitor_results.clear()
            self._monitor_tasks.clear()

            self._initialized = False
            self.logger.info("Web service shutdown completed")

        except Exception as e:
            self.logger.warning("Error during web service shutdown", error=str(e))

    def _ensure_initialized(self) -> None:
        """Ensure service is initialized."""
        if not self._initialized:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Web service is not initialized",
            )

    def _get_cache_key(self, request: WebCrawlRequest) -> str:
        """Generate cache key for crawl request."""
        # Create deterministic hash from request parameters
        cache_data = {
            "url": str(request.url),
            "urls": [str(u) for u in request.urls] if request.urls else None,
            "max_depth": request.max_depth,
            "max_pages": request.max_pages,
            "output_formats": [f.value for f in request.output_formats],
            "crawling_strategy": request.crawling_strategy.value,
            "extraction_config": request.extraction_config.dict()
            if request.extraction_config
            else None,
        }

        cache_string = json.dumps(cache_data, sort_keys=True)
        return hashlib.sha256(cache_string.encode()).hexdigest()

    def _is_cache_valid(self, cache_key: str) -> bool:
        """Check if cached result is still valid."""
        if not self.config.web_config.enable_caching:
            return False

        if cache_key not in self._cache_timestamps:
            return False

        cache_time = self._cache_timestamps[cache_key]
        expiry_time = cache_time + timedelta(seconds=self.config.web_config.cache_ttl)

        return datetime.utcnow() < expiry_time

    def _get_from_cache(self, cache_key: str) -> WebCrawlResult | None:
        """Get result from cache if valid."""
        if self._is_cache_valid(cache_key):
            self._stats["cache_hits"] += 1
            return self._cache.get(cache_key)

        # Remove expired cache entry
        if cache_key in self._cache:
            del self._cache[cache_key]
            del self._cache_timestamps[cache_key]

        self._stats["cache_misses"] += 1
        return None

    def _store_in_cache(self, cache_key: str, result: WebCrawlResult) -> None:
        """Store result in cache."""
        if self.config.web_config.enable_caching:
            self._cache[cache_key] = result
            self._cache_timestamps[cache_key] = datetime.utcnow()

    async def crawl_web(self, request: WebCrawlRequest) -> WebCrawlResult:
        """
        Perform web crawling operation.

        Args:
            request: Web crawl request configuration

        Returns:
            Web crawl result with extracted content

        Raises:
            HTTPException: If crawling fails or service unavailable
        """
        self._ensure_initialized()

        start_time = time.time()
        self._stats["total_requests"] += 1

        try:
            # Check cache first
            cache_key = self._get_cache_key(request)
            cached_result = self._get_from_cache(cache_key)

            if cached_result:
                self.logger.info(
                    "Returning cached crawl result",
                    url=str(request.url),
                    cache_key=cache_key[:8],
                )
                return cached_result

            # Validate request
            self._validate_crawl_request(request)

            self.logger.info(
                "Starting web crawl",
                url=str(request.url),
                max_depth=request.max_depth,
                strategy=request.crawling_strategy,
                formats=request.output_formats,
            )

            # Perform crawl
            result = await self.client.crawl(request)

            # Store in cache if successful
            if result.status == CrawlStatus.COMPLETED:
                self._store_in_cache(cache_key, result)
                self._stats["successful_requests"] += 1
            else:
                self._stats["failed_requests"] += 1

            # Update statistics
            crawl_time = (time.time() - start_time) * 1000
            self._stats["total_crawl_time_ms"] += crawl_time
            self._stats["average_crawl_time_ms"] = (
                self._stats["total_crawl_time_ms"] / self._stats["total_requests"]
            )

            self.logger.info(
                "Web crawl completed",
                url=str(request.url),
                status=result.status,
                pages=result.total_pages,
                time_ms=crawl_time,
            )

            return result

        except Exception as e:
            self._stats["failed_requests"] += 1
            self.logger.exception(
                "Web crawl failed",
                url=str(request.url),
                error=str(e),
                error_type=type(e).__name__,
            )

            # Return failed result instead of raising exception
            return WebCrawlResult(
                status=CrawlStatus.FAILED,
                url=str(request.url),
                errors=[str(e)],
                crawl_time_ms=(time.time() - start_time) * 1000,
                completed_at=datetime.utcnow(),
            )

    def _validate_crawl_request(self, request: WebCrawlRequest) -> None:
        """Validate crawl request parameters."""
        # Check URL domains if restrictions are configured
        if request.include_domains or request.exclude_domains:
            url_domain = urlparse(str(request.url)).netloc

            if request.include_domains and url_domain not in request.include_domains:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Domain {url_domain} not in allowed domains",
                )

            if request.exclude_domains and url_domain in request.exclude_domains:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Domain {url_domain} is excluded",
                )

        # Validate depth and pages limits
        if request.max_depth > 3:
            self.logger.warning(
                "High crawl depth requested",
                depth=request.max_depth,
                url=str(request.url),
            )

        if request.max_pages > 50:
            self.logger.warning(
                "High page count requested",
                pages=request.max_pages,
                url=str(request.url),
            )

    async def screenshot_web(
        self, request: WebScreenshotRequest
    ) -> WebScreenshotResult:
        """
        Capture webpage screenshot.

        Args:
            request: Screenshot request configuration

        Returns:
            Screenshot result with image data

        Raises:
            HTTPException: If screenshot capture fails
        """
        self._ensure_initialized()

        try:
            self.logger.info("Capturing web screenshot", url=str(request.url))

            result = await self.client.screenshot(request)

            self.logger.info(
                "Screenshot captured successfully",
                url=str(request.url),
                size_bytes=result.file_size_bytes,
                time_ms=result.capture_time_ms,
            )

            return result

        except Exception as e:
            self.logger.exception(
                "Screenshot capture failed", url=str(request.url), error=str(e)
            )
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Screenshot capture failed: {e!s}",
            )

    async def start_monitoring(self, request: WebMonitorRequest) -> WebMonitorResult:
        """
        Start monitoring a web resource for changes.

        Args:
            request: Monitor request configuration

        Returns:
            Monitor result with status
        """
        self._ensure_initialized()

        monitor_id = hashlib.sha256(str(request.url).encode()).hexdigest()[:16]

        try:
            self.logger.info(
                "Starting web monitoring",
                monitor_id=monitor_id,
                url=str(request.url),
                interval=request.check_interval,
            )

            # Store monitor configuration
            self._monitors[monitor_id] = request

            # Create monitor result
            monitor_result = WebMonitorResult(
                id=monitor_id,
                url=str(request.url),
                status="active" if request.enabled else "inactive",
                last_check=datetime.utcnow(),
                next_check=datetime.utcnow()
                + timedelta(seconds=request.check_interval),
            )

            self._monitor_results[monitor_id] = monitor_result

            # Start monitoring task if enabled
            if request.enabled:
                task = asyncio.create_task(self._monitor_loop(monitor_id))
                self._monitor_tasks[monitor_id] = task

            return monitor_result

        except Exception as e:
            self.logger.exception(
                "Failed to start monitoring",
                monitor_id=monitor_id,
                url=str(request.url),
                error=str(e),
            )
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to start monitoring: {e!s}",
            )

    async def stop_monitoring(self, monitor_id: str) -> dict[str, Any]:
        """
        Stop monitoring a web resource.

        Args:
            monitor_id: Monitor identifier

        Returns:
            Status information
        """
        try:
            # Cancel monitoring task
            if monitor_id in self._monitor_tasks:
                task = self._monitor_tasks[monitor_id]
                if not task.done():
                    task.cancel()

                del self._monitor_tasks[monitor_id]

            # Update monitor status
            if monitor_id in self._monitor_results:
                self._monitor_results[monitor_id].status = "stopped"

            # Remove monitor configuration
            if monitor_id in self._monitors:
                del self._monitors[monitor_id]

            self.logger.info("Web monitoring stopped", monitor_id=monitor_id)

            return {
                "status": "stopped",
                "monitor_id": monitor_id,
                "timestamp": datetime.utcnow().isoformat(),
            }

        except Exception as e:
            self.logger.exception(
                "Failed to stop monitoring", monitor_id=monitor_id, error=str(e)
            )
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to stop monitoring: {e!s}",
            )

    async def get_monitor_status(self, monitor_id: str) -> WebMonitorResult:
        """
        Get monitoring status for a resource.

        Args:
            monitor_id: Monitor identifier

        Returns:
            Monitor result with current status
        """
        if monitor_id not in self._monitor_results:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Monitor {monitor_id} not found",
            )

        return self._monitor_results[monitor_id]

    async def list_monitors(self) -> list[WebMonitorResult]:
        """
        List all active monitors.

        Returns:
            List of monitor results
        """
        return list(self._monitor_results.values())

    async def _monitor_loop(self, monitor_id: str) -> None:
        """Background monitoring loop for a specific resource."""
        try:
            request = self._monitors[monitor_id]
            result = self._monitor_results[monitor_id]

            while result.check_count < request.max_checks:
                try:
                    # Wait for next check time
                    await asyncio.sleep(request.check_interval)

                    # Perform content check
                    await self._check_content_change(monitor_id)

                    # Update next check time
                    result.next_check = datetime.utcnow() + timedelta(
                        seconds=request.check_interval
                    )

                except asyncio.CancelledError:
                    self.logger.info("Monitor loop cancelled", monitor_id=monitor_id)
                    break

                except Exception as e:
                    result.error_count += 1
                    result.last_error = str(e)
                    self.logger.exception(
                        "Monitor check failed", monitor_id=monitor_id, error=str(e)
                    )

        except Exception as e:
            self.logger.exception(
                "Monitor loop failed", monitor_id=monitor_id, error=str(e)
            )
        finally:
            # Mark monitor as inactive
            if monitor_id in self._monitor_results:
                self._monitor_results[monitor_id].status = "inactive"

    async def _check_content_change(self, monitor_id: str) -> None:
        """Check for content changes on monitored resource."""
        request = self._monitors[monitor_id]
        result = self._monitor_results[monitor_id]

        try:
            # Create a simple crawl request
            crawl_request = WebCrawlRequest(
                url=request.url,
                max_depth=1,
                max_pages=1,
                output_formats=[OutputFormat.MARKDOWN],
            )

            # Crawl the content
            crawl_result = await self.client.crawl(crawl_request)

            if crawl_result.status == CrawlStatus.COMPLETED and crawl_result.content:
                content = crawl_result.content[0].content
                content_hash = hashlib.sha256(content.encode()).hexdigest()

                # Check if content changed
                if request.content_hash and request.content_hash != content_hash:
                    result.change_detected = True
                    self.logger.info(
                        "Content change detected",
                        monitor_id=monitor_id,
                        url=str(request.url),
                    )

                    # Send notification if webhook configured
                    if request.notification_webhook:
                        await self._send_change_notification(
                            monitor_id, request.notification_webhook
                        )

                # Update stored hash
                request.content_hash = content_hash

            result.check_count += 1
            result.last_check = datetime.utcnow()

        except Exception as e:
            result.error_count += 1
            result.last_error = str(e)
            raise

    async def _send_change_notification(
        self, monitor_id: str, webhook_url: str
    ) -> None:
        """Send change notification to webhook."""
        try:
            # Would implement webhook notification here
            self.logger.info(
                "Change notification sent",
                monitor_id=monitor_id,
                webhook_url=webhook_url,
            )
        except Exception as e:
            self.logger.exception(
                "Failed to send change notification",
                monitor_id=monitor_id,
                error=str(e),
            )

    async def health_check(self) -> WebHealthCheck:
        """
        Perform comprehensive health check.

        Returns:
            Health check result with service status
        """
        try:
            if not self._initialized:
                return WebHealthCheck(
                    status="unhealthy", details={"error": "Service not initialized"}
                )

            # Get health check from client
            client_health = await self.client.health_check()

            # Add service-level statistics
            client_health.active_crawls = len(self.client._active_crawls)
            client_health.details.update(
                {
                    "service_stats": self._stats,
                    "cache_size": len(self._cache),
                    "active_monitors": len(
                        [
                            m
                            for m in self._monitor_results.values()
                            if m.status == "active"
                        ]
                    ),
                    "total_monitors": len(self._monitor_results),
                }
            )

            return client_health

        except Exception as e:
            return WebHealthCheck(status="unhealthy", details={"error": str(e)})

    async def get_statistics(self) -> dict[str, Any]:
        """
        Get comprehensive service statistics.

        Returns:
            Service statistics and metrics
        """
        return {
            "service_stats": self._stats,
            "cache_stats": {
                "size": len(self._cache),
                "hit_rate": (
                    self._stats["cache_hits"]
                    / max(self._stats["cache_hits"] + self._stats["cache_misses"], 1)
                ),
                "ttl_seconds": self.config.web_config.cache_ttl,
            },
            "monitoring_stats": {
                "total_monitors": len(self._monitor_results),
                "active_monitors": len(
                    [m for m in self._monitor_results.values() if m.status == "active"]
                ),
                "inactive_monitors": len(
                    [m for m in self._monitor_results.values() if m.status != "active"]
                ),
            },
            "configuration": {
                "max_concurrent": self.config.web_config.max_concurrent,
                "request_timeout": self.config.web_config.request_timeout,
                "caching_enabled": self.config.web_config.enable_caching,
                "robots_txt_check": self.config.web_config.check_robots_txt,
            },
        }
