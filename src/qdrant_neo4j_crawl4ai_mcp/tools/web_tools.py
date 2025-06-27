"""
FastMCP tools for web intelligence operations.

Provides MCP-compatible tool functions for web crawling, content extraction,
screenshot capture, and monitoring using the Crawl4AI integration.
"""

from typing import Any

from fastmcp import FastMCP
from pydantic import BaseModel, Field, HttpUrl
import structlog

from qdrant_neo4j_crawl4ai_mcp.models.web_models import (
    CrawlingStrategy,
    ExtractionConfig,
    ExtractionStrategy,
    OutputFormat,
    WebCrawlRequest,
    WebMonitorRequest,
    WebScreenshotRequest,
)
from qdrant_neo4j_crawl4ai_mcp.services.web_service import WebService

logger = structlog.get_logger(__name__)


class WebCrawlToolRequest(BaseModel):
    """Tool request model for web crawling."""

    url: str = Field(..., description="Target URL to crawl")
    max_depth: int = Field(default=1, ge=1, le=3, description="Maximum crawling depth")
    max_pages: int = Field(
        default=10, ge=1, le=50, description="Maximum pages to crawl"
    )
    output_format: str = Field(
        default="markdown", description="Output format: markdown, html, json"
    )
    strategy: str = Field(
        default="bfs", description="Crawling strategy: bfs, dfs, best_first"
    )
    include_external: bool = Field(
        default=False, description="Include external domains"
    )
    extract_content: bool = Field(default=True, description="Extract main content")
    capture_screenshots: bool = Field(default=False, description="Capture screenshots")
    wait_time: float = Field(
        default=0.0, ge=0.0, le=30.0, description="Wait time before extraction"
    )


class WebExtractToolRequest(BaseModel):
    """Tool request model for content extraction."""

    url: str = Field(..., description="Target URL for extraction")
    strategy: str = Field(
        default="llm", description="Extraction strategy: llm, css_selector, regex"
    )
    css_selector: str | None = Field(None, description="CSS selector for extraction")
    regex_pattern: str | None = Field(None, description="Regex pattern for extraction")
    instruction: str | None = Field(None, description="LLM extraction instruction")
    schema: dict[str, Any] | None = Field(
        None, description="JSON schema for structured extraction"
    )
    output_format: str = Field(default="markdown", description="Output format")


class WebScreenshotToolRequest(BaseModel):
    """Tool request model for screenshots."""

    url: str = Field(..., description="Target URL for screenshot")
    full_page: bool = Field(default=True, description="Capture full page")
    width: int = Field(default=1280, ge=320, le=3840, description="Screenshot width")
    height: int = Field(default=720, ge=240, le=2160, description="Screenshot height")
    format: str = Field(default="png", description="Image format: png, jpeg, webp")
    wait_for_selector: str | None = Field(None, description="Wait for CSS selector")
    wait_time: float = Field(
        default=2.0, ge=0.0, le=30.0, description="Wait time before capture"
    )


class WebMonitorToolRequest(BaseModel):
    """Tool request model for web monitoring."""

    url: str = Field(..., description="URL to monitor")
    check_interval: int = Field(
        default=300, ge=60, le=86400, description="Check interval in seconds"
    )
    css_selector: str | None = Field(None, description="CSS selector to monitor")
    webhook_url: str | None = Field(None, description="Webhook for notifications")
    max_checks: int = Field(
        default=100, ge=1, le=1000, description="Maximum number of checks"
    )


def register_web_tools(mcp: FastMCP, web_service: WebService) -> None:
    """
    Register web intelligence tools with FastMCP.

    Args:
        mcp: FastMCP application instance
        web_service: Web service instance
    """

    @mcp.tool()
    async def crawl_web_page(request: WebCrawlToolRequest) -> dict[str, Any]:
        """
        Crawl and extract content from a web page or website.

        This tool provides comprehensive web crawling capabilities with support for:
        - Single page or multi-page crawling with depth control
        - Multiple output formats (Markdown, HTML, JSON)
        - Different crawling strategies (BFS, DFS, Best-First)
        - Content extraction and link discovery
        - Screenshot capture and page interaction

        Args:
            request: Web crawl request with URL and configuration options

        Returns:
            Crawl result with extracted content, metadata, and statistics
        """
        try:
            logger.info(
                "Web crawl tool called", url=request.url, strategy=request.strategy
            )

            # Convert tool request to service request
            output_formats = []
            if request.output_format.lower() == "markdown":
                output_formats.append(OutputFormat.MARKDOWN)
            elif request.output_format.lower() == "html":
                output_formats.append(OutputFormat.HTML)
            elif request.output_format.lower() == "json":
                output_formats.append(OutputFormat.JSON)
            else:
                output_formats.append(OutputFormat.MARKDOWN)

            if request.capture_screenshots:
                output_formats.append(OutputFormat.SCREENSHOT)

            crawling_strategy = CrawlingStrategy.BFS
            if request.strategy.lower() == "dfs":
                crawling_strategy = CrawlingStrategy.DFS
            elif request.strategy.lower() == "best_first":
                crawling_strategy = CrawlingStrategy.BEST_FIRST

            # Create extraction config if content extraction is enabled
            extraction_config = None
            if request.extract_content:
                extraction_config = ExtractionConfig(
                    strategy=ExtractionStrategy.LLM,
                    llm_instruction="Extract the main content, preserving structure and key information",
                )

            web_request = WebCrawlRequest(
                url=HttpUrl(request.url),
                max_depth=request.max_depth,
                max_pages=request.max_pages,
                include_external=request.include_external,
                output_formats=output_formats,
                crawling_strategy=crawling_strategy,
                extraction_config=extraction_config,
                wait_time=request.wait_time,
            )

            # Perform crawl
            result = await web_service.crawl_web(web_request)

            # Format response
            response = {
                "status": result.status.value,
                "url": result.url,
                "total_pages": result.total_pages,
                "successful_pages": result.successful_pages,
                "failed_pages": result.failed_pages,
                "crawl_time_ms": result.crawl_time_ms,
                "content": [],
            }

            # Add content
            for content in result.content:
                response["content"].append(
                    {
                        "url": content.url,
                        "title": content.title,
                        "content": content.content[:2000] + "..."
                        if len(content.content) > 2000
                        else content.content,
                        "content_type": content.content_type.value,
                        "format": content.format.value,
                        "word_count": content.word_count,
                        "links_count": len(content.links),
                        "images_count": len(content.images),
                        "status_code": content.status_code,
                    }
                )

            # Add metadata
            response["metadata"] = {
                "urls_crawled": result.urls_crawled,
                "urls_failed": result.urls_failed,
                "robots_txt_allowed": result.robots_txt_allowed,
                "rate_limited": result.rate_limited,
                "errors": result.errors,
                "warnings": result.warnings,
            }

            return response

        except Exception as e:
            logger.exception("Web crawl tool failed", error=str(e), url=request.url)
            return {"status": "failed", "error": str(e), "url": request.url}

    @mcp.tool()
    async def extract_web_content(request: WebExtractToolRequest) -> dict[str, Any]:
        """
        Extract specific content from a web page using various strategies.

        This tool provides targeted content extraction with support for:
        - LLM-based intelligent extraction with custom instructions
        - CSS selector-based precise element extraction
        - Regex pattern-based text extraction
        - Structured data extraction with JSON schema validation
        - Multiple output formats and content types

        Args:
            request: Content extraction request with URL and strategy configuration

        Returns:
            Extracted content with metadata and extraction details
        """
        try:
            logger.info(
                "Web extract tool called", url=request.url, strategy=request.strategy
            )

            # Create extraction strategy
            extraction_strategy = ExtractionStrategy.LLM
            if request.strategy.lower() == "css_selector":
                extraction_strategy = ExtractionStrategy.CSS_SELECTOR
            elif request.strategy.lower() == "regex":
                extraction_strategy = ExtractionStrategy.REGEX

            extraction_config = ExtractionConfig(
                strategy=extraction_strategy,
                css_selector=request.css_selector,
                regex_pattern=request.regex_pattern,
                llm_instruction=request.instruction or "Extract the main content",
                schema=request.schema,
            )

            # Convert output format
            output_formats = [OutputFormat.MARKDOWN]
            if request.output_format.lower() == "html":
                output_formats = [OutputFormat.HTML]
            elif request.output_format.lower() == "json":
                output_formats = [OutputFormat.JSON]

            web_request = WebCrawlRequest(
                url=HttpUrl(request.url),
                max_depth=1,
                max_pages=1,
                output_formats=output_formats,
                extraction_config=extraction_config,
            )

            # Perform extraction
            result = await web_service.crawl_web(web_request)

            if result.status.value == "completed" and result.content:
                content = result.content[0]
                return {
                    "status": "success",
                    "url": content.url,
                    "title": content.title,
                    "content": content.content,
                    "content_type": content.content_type.value,
                    "word_count": content.word_count,
                    "character_count": content.character_count,
                    "extraction_time_ms": content.extraction_time_ms,
                    "metadata": content.metadata,
                }
            return {
                "status": "failed",
                "url": request.url,
                "error": result.errors[0] if result.errors else "Extraction failed",
                "warnings": result.warnings,
            }

        except Exception as e:
            logger.exception("Web extract tool failed", error=str(e), url=request.url)
            return {"status": "failed", "error": str(e), "url": request.url}

    @mcp.tool()
    async def capture_web_screenshot(
        request: WebScreenshotToolRequest,
    ) -> dict[str, Any]:
        """
        Capture a screenshot of a web page.

        This tool provides web page screenshot capture with support for:
        - Full page or viewport-specific screenshots
        - Multiple image formats (PNG, JPEG, WebP)
        - Custom viewport dimensions and quality settings
        - Wait conditions for dynamic content
        - Element hiding and page interaction

        Args:
            request: Screenshot request with URL and capture configuration

        Returns:
            Screenshot result with image data and metadata
        """
        try:
            logger.info("Web screenshot tool called", url=request.url)

            screenshot_request = WebScreenshotRequest(
                url=HttpUrl(request.url),
                full_page=request.full_page,
                width=request.width,
                height=request.height,
                format=request.format,
                wait_for_selector=request.wait_for_selector,
                wait_time=request.wait_time,
            )

            result = await web_service.screenshot_web(screenshot_request)

            return {
                "status": "success",
                "url": result.url,
                "image_data": result.image_data,
                "format": result.format,
                "width": result.width,
                "height": result.height,
                "file_size_bytes": result.file_size_bytes,
                "capture_time_ms": result.capture_time_ms,
                "timestamp": result.timestamp.isoformat(),
            }

        except Exception as e:
            logger.exception(
                "Web screenshot tool failed", error=str(e), url=request.url
            )
            return {"status": "failed", "error": str(e), "url": request.url}

    @mcp.tool()
    async def monitor_web_content(request: WebMonitorToolRequest) -> dict[str, Any]:
        """
        Start monitoring a web page for content changes.

        This tool provides web content monitoring with support for:
        - Scheduled content change detection
        - CSS selector-based monitoring of specific elements
        - Webhook notifications for detected changes
        - Configurable check intervals and limits
        - Change detection using content hashing

        Args:
            request: Monitor request with URL and monitoring configuration

        Returns:
            Monitor result with status and configuration details
        """
        try:
            logger.info("Web monitor tool called", url=request.url)

            monitor_request = WebMonitorRequest(
                url=HttpUrl(request.url),
                check_interval=request.check_interval,
                css_selector=request.css_selector,
                notification_webhook=HttpUrl(request.webhook_url)
                if request.webhook_url
                else None,
                max_checks=request.max_checks,
            )

            result = await web_service.start_monitoring(monitor_request)

            return {
                "status": "success",
                "monitor_id": result.id,
                "url": result.url,
                "monitor_status": result.status,
                "check_interval": request.check_interval,
                "max_checks": request.max_checks,
                "last_check": result.last_check.isoformat(),
                "next_check": result.next_check.isoformat(),
                "created_at": result.created_at.isoformat(),
            }

        except Exception as e:
            logger.exception("Web monitor tool failed", error=str(e), url=request.url)
            return {"status": "failed", "error": str(e), "url": request.url}

    @mcp.tool()
    async def get_web_monitor_status(monitor_id: str) -> dict[str, Any]:
        """
        Get the status of a web content monitor.

        This tool retrieves the current status and statistics for an active
        web content monitor, including check counts, change detection status,
        and error information.

        Args:
            monitor_id: Unique identifier of the monitor to check

        Returns:
            Monitor status with check statistics and change detection results
        """
        try:
            logger.info("Get web monitor status called", monitor_id=monitor_id)

            result = await web_service.get_monitor_status(monitor_id)

            return {
                "status": "success",
                "monitor_id": result.id,
                "url": result.url,
                "monitor_status": result.status,
                "last_check": result.last_check.isoformat(),
                "next_check": result.next_check.isoformat(),
                "change_detected": result.change_detected,
                "check_count": result.check_count,
                "error_count": result.error_count,
                "last_error": result.last_error,
                "created_at": result.created_at.isoformat(),
            }

        except Exception as e:
            logger.exception(
                "Get web monitor status failed", error=str(e), monitor_id=monitor_id
            )
            return {"status": "failed", "error": str(e), "monitor_id": monitor_id}

    @mcp.tool()
    async def stop_web_monitor(monitor_id: str) -> dict[str, Any]:
        """
        Stop an active web content monitor.

        This tool stops a running web content monitor and cleans up
        associated resources and background tasks.

        Args:
            monitor_id: Unique identifier of the monitor to stop

        Returns:
            Stop operation result with final status
        """
        try:
            logger.info("Stop web monitor called", monitor_id=monitor_id)

            result = await web_service.stop_monitoring(monitor_id)

            return {
                "status": "success",
                "message": "Monitor stopped successfully",
                "monitor_id": monitor_id,
                "timestamp": result["timestamp"],
            }

        except Exception as e:
            logger.exception(
                "Stop web monitor failed", error=str(e), monitor_id=monitor_id
            )
            return {"status": "failed", "error": str(e), "monitor_id": monitor_id}

    @mcp.tool()
    async def list_web_monitors() -> dict[str, Any]:
        """
        List all active web content monitors.

        This tool returns a list of all currently configured web content
        monitors with their status and basic configuration information.

        Returns:
            List of active monitors with status information
        """
        try:
            logger.info("List web monitors called")

            monitors = await web_service.list_monitors()

            return {
                "status": "success",
                "total_monitors": len(monitors),
                "monitors": [
                    {
                        "monitor_id": monitor.id,
                        "url": monitor.url,
                        "status": monitor.status,
                        "last_check": monitor.last_check.isoformat(),
                        "next_check": monitor.next_check.isoformat(),
                        "change_detected": monitor.change_detected,
                        "check_count": monitor.check_count,
                        "error_count": monitor.error_count,
                        "created_at": monitor.created_at.isoformat(),
                    }
                    for monitor in monitors
                ],
            }

        except Exception as e:
            logger.exception("List web monitors failed", error=str(e))
            return {"status": "failed", "error": str(e)}

    @mcp.tool()
    async def web_service_health() -> dict[str, Any]:
        """
        Get web service health status and statistics.

        This tool provides comprehensive health information about the web
        intelligence service, including browser status, memory usage,
        active operations, and performance metrics.

        Returns:
            Health status with service metrics and statistics
        """
        try:
            logger.info("Web service health check called")

            health = await web_service.health_check()
            stats = await web_service.get_statistics()

            return {
                "status": health.status,
                "service": health.service,
                "browser_available": health.browser_available,
                "memory_usage_mb": health.memory_usage_mb,
                "active_crawls": health.active_crawls,
                "total_crawls": health.total_crawls,
                "success_rate": health.success_rate,
                "average_response_time_ms": health.average_response_time_ms,
                "response_time_ms": health.response_time_ms,
                "timestamp": health.timestamp.isoformat(),
                "statistics": stats,
                "details": health.details,
            }

        except Exception as e:
            logger.exception("Web service health check failed", error=str(e))
            return {"status": "unhealthy", "error": str(e)}

    logger.info("Web intelligence tools registered", tool_count=8)
