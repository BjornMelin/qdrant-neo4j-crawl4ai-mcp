"""
Crawl4AI client for web intelligence operations.

Provides a high-level async client for Crawl4AI with comprehensive error handling,
rate limiting, and production-ready configuration management.
"""

import asyncio
from contextlib import asynccontextmanager
from datetime import datetime
import time
from typing import Any

import aiohttp
from crawl4ai import AsyncWebCrawler, CrawlResult
from crawl4ai.crawler_strategy import BFSCrawlerStrategy, DFSCrawlerStrategy
from crawl4ai.extraction_strategy import (
    JsonCssExtractionStrategy,
    LLMExtractionStrategy,
    RegexExtractionStrategy,
)
from crawl4ai.models import BrowserConfig, CacheMode, CrawlerRunConfig
from crawl4ai.utils import MemoryAdaptiveDispatcher, RateLimiter
import structlog

from qdrant_neo4j_crawl4ai_mcp.models.web_models import (
    ContentType,
    CrawlingStrategy,
    CrawlStatus,
    ExtractionConfig,
    ExtractionStrategy,
    OutputFormat,
    WebConfig,
    WebContent,
    WebCrawlRequest,
    WebCrawlResult,
    WebHealthCheck,
    WebScreenshotRequest,
    WebScreenshotResult,
)

logger = structlog.get_logger(__name__)


class Crawl4AIClient:
    """
    High-level async client for Crawl4AI web intelligence operations.

    Provides production-ready web crawling with rate limiting, error handling,
    memory management, and comprehensive monitoring capabilities.
    """

    def __init__(self, config: WebConfig) -> None:
        """
        Initialize the Crawl4AI client.

        Args:
            config: Web configuration settings
        """
        self.config = config
        self.logger = logger.bind(component="crawl4ai_client")
        self._crawler: AsyncWebCrawler | None = None
        self._session: aiohttp.ClientSession | None = None
        self._rate_limiter: RateLimiter | None = None
        self._dispatcher: MemoryAdaptiveDispatcher | None = None
        self._stats = {
            "total_crawls": 0,
            "successful_crawls": 0,
            "failed_crawls": 0,
            "total_time_ms": 0.0,
            "average_time_ms": 0.0,
        }
        self._active_crawls = set()
        self._initialized = False

    async def initialize(self) -> None:
        """Initialize the Crawl4AI client with browser and rate limiting."""
        if self._initialized:
            return

        try:
            self.logger.info("Initializing Crawl4AI client")

            # Create browser configuration
            browser_config = BrowserConfig(
                headless=True,
                verbose=False,
                extra_args=[
                    "--disable-dev-shm-usage",
                    "--no-sandbox",
                    "--disable-gpu",
                    "--disable-web-security",
                    "--disable-features=VizDisplayCompositor",
                ],
            )

            # Initialize rate limiter
            self._rate_limiter = RateLimiter(
                base_delay=(0.5, 1.0), max_delay=30.0, backoff_factor=2.0
            )

            # Initialize memory adaptive dispatcher
            self._dispatcher = MemoryAdaptiveDispatcher(
                memory_threshold_percent=85,
                max_concurrent=self.config.max_concurrent,
                rate_limiter=self._rate_limiter,
            )

            # Create async web crawler
            self._crawler = AsyncWebCrawler(config=browser_config, verbose=False)

            # Initialize browser session
            await self._crawler.__aenter__()

            # Create aiohttp session for direct HTTP requests
            self._session = aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=self.config.request_timeout),
                headers={"User-Agent": self.config.user_agent},
            )

            self._initialized = True
            self.logger.info("Crawl4AI client initialized successfully")

        except Exception as e:
            self.logger.exception("Failed to initialize Crawl4AI client", error=str(e))
            await self.shutdown()
            raise

    async def shutdown(self) -> None:
        """Shutdown the client and cleanup resources."""
        self.logger.info("Shutting down Crawl4AI client")

        try:
            if self._crawler:
                await self._crawler.__aexit__(None, None, None)
                self._crawler = None

            if self._session:
                await self._session.close()
                self._session = None

            self._rate_limiter = None
            self._dispatcher = None
            self._initialized = False

            self.logger.info("Crawl4AI client shutdown completed")

        except Exception as e:
            self.logger.warning("Error during Crawl4AI client shutdown", error=str(e))

    @asynccontextmanager
    async def _ensure_initialized(self):
        """Ensure client is initialized before operations."""
        if not self._initialized:
            await self.initialize()
        yield

    def _create_extraction_strategy(
        self, config: ExtractionConfig | None
    ) -> Any | None:
        """Create extraction strategy based on configuration."""
        if not config:
            return None

        try:
            if (
                config.strategy == ExtractionStrategy.CSS_SELECTOR
                and config.css_selector
            ):
                return JsonCssExtractionStrategy(config.css_selector)

            if config.strategy == ExtractionStrategy.REGEX and config.regex_pattern:
                return RegexExtractionStrategy(config.regex_pattern)

            if config.strategy == ExtractionStrategy.LLM and config.llm_instruction:
                return LLMExtractionStrategy(
                    provider="openai/gpt-4o-mini",
                    instruction=config.llm_instruction,
                    schema=config.schema,
                    chunk_token_threshold=config.chunk_size,
                    apply_chunking=True,
                )

            return None

        except Exception as e:
            self.logger.warning("Failed to create extraction strategy", error=str(e))
            return None

    def _create_crawling_strategy(self, request: WebCrawlRequest) -> Any | None:
        """Create crawling strategy based on request."""
        try:
            if request.crawling_strategy == CrawlingStrategy.BFS:
                return BFSCrawlerStrategy(
                    max_depth=request.max_depth,
                    max_pages=request.max_pages,
                    include_external=request.include_external,
                )
            if request.crawling_strategy == CrawlingStrategy.DFS:
                return DFSCrawlerStrategy(
                    max_depth=request.max_depth,
                    max_pages=request.max_pages,
                    include_external=request.include_external,
                )
            return None

        except Exception as e:
            self.logger.warning("Failed to create crawling strategy", error=str(e))
            return None

    async def crawl(self, request: WebCrawlRequest) -> WebCrawlResult:
        """
        Perform web crawling operation.

        Args:
            request: Web crawl request configuration

        Returns:
            Web crawl result with extracted content
        """
        async with self._ensure_initialized():
            crawl_id = f"crawl_{int(time.time() * 1000)}"
            self._active_crawls.add(crawl_id)
            start_time = time.time()

            try:
                self.logger.info(
                    "Starting web crawl",
                    crawl_id=crawl_id,
                    url=str(request.url),
                    max_depth=request.max_depth,
                    strategy=request.crawling_strategy,
                )

                # Create run configuration
                extraction_strategy = self._create_extraction_strategy(
                    request.extraction_config
                )
                crawling_strategy = self._create_crawling_strategy(request)

                run_config = CrawlerRunConfig(
                    check_robots_txt=self.config.check_robots_txt,
                    user_agent=self.config.user_agent,
                    cache_mode=CacheMode.ENABLED
                    if self.config.enable_caching
                    else CacheMode.DISABLED,
                    extraction_strategy=extraction_strategy,
                    crawling_strategy=crawling_strategy,
                    capture_network_requests=True,
                    capture_console_messages=True,
                    wait_for=request.wait_for_selector,
                    js_code=request.execute_js,
                    headers=request.custom_headers,
                    cookies=request.cookies,
                )

                # Handle multiple URLs vs single URL
                if request.urls and len(request.urls) > 1:
                    results = await self._crawl_multiple(request.urls, run_config)
                else:
                    url = request.urls[0] if request.urls else request.url
                    result = await self._crawler.arun(str(url), config=run_config)
                    results = [result]

                # Process results
                web_content = []
                urls_crawled = []
                urls_failed = []

                for result in results:
                    if result.success:
                        content = self._process_crawl_result(
                            result, request.output_formats
                        )
                        web_content.extend(content)
                        urls_crawled.append(result.url)
                    else:
                        urls_failed.append(result.url)
                        self.logger.warning(
                            "Crawl failed for URL",
                            url=result.url,
                            error=result.error_message,
                        )

                # Calculate metrics
                crawl_time = (time.time() - start_time) * 1000

                # Update statistics
                self._stats["total_crawls"] += 1
                if web_content:
                    self._stats["successful_crawls"] += 1
                else:
                    self._stats["failed_crawls"] += 1

                self._stats["total_time_ms"] += crawl_time
                self._stats["average_time_ms"] = (
                    self._stats["total_time_ms"] / self._stats["total_crawls"]
                )

                result = WebCrawlResult(
                    id=crawl_id,
                    status=CrawlStatus.COMPLETED if web_content else CrawlStatus.FAILED,
                    url=str(request.url),
                    urls_crawled=urls_crawled,
                    urls_failed=urls_failed,
                    content=web_content,
                    total_pages=len(results),
                    successful_pages=len(urls_crawled),
                    failed_pages=len(urls_failed),
                    crawl_time_ms=crawl_time,
                    average_page_time_ms=crawl_time / max(len(results), 1),
                    robots_txt_allowed=True,  # Would be set based on actual check
                    rate_limited=False,  # Would be set based on rate limiter status
                    completed_at=datetime.utcnow(),
                )

                self.logger.info(
                    "Web crawl completed",
                    crawl_id=crawl_id,
                    total_pages=result.total_pages,
                    successful_pages=result.successful_pages,
                    crawl_time_ms=crawl_time,
                )

                return result

            except Exception as e:
                self._stats["total_crawls"] += 1
                self._stats["failed_crawls"] += 1

                self.logger.exception(
                    "Web crawl failed",
                    crawl_id=crawl_id,
                    url=str(request.url),
                    error=str(e),
                )

                return WebCrawlResult(
                    id=crawl_id,
                    status=CrawlStatus.FAILED,
                    url=str(request.url),
                    errors=[str(e)],
                    crawl_time_ms=(time.time() - start_time) * 1000,
                    completed_at=datetime.utcnow(),
                )

            finally:
                self._active_crawls.discard(crawl_id)

    async def _crawl_multiple(
        self, urls: list[str], config: CrawlerRunConfig
    ) -> list[CrawlResult]:
        """Crawl multiple URLs concurrently."""

        async def crawl_single(url: str) -> CrawlResult:
            try:
                return await self._crawler.arun(str(url), config=config)
            except Exception as e:
                # Create a failed result
                return CrawlResult(url=str(url), success=False, error_message=str(e))

        # Use semaphore to limit concurrency
        semaphore = asyncio.Semaphore(self.config.max_concurrent)

        async def bounded_crawl(url: str) -> CrawlResult:
            async with semaphore:
                return await crawl_single(url)

        tasks = [bounded_crawl(url) for url in urls]
        return await asyncio.gather(*tasks, return_exceptions=False)

    def _process_crawl_result(
        self, result: CrawlResult, formats: list[OutputFormat]
    ) -> list[WebContent]:
        """Process crawl result into web content."""
        content_items = []

        try:
            for fmt in formats:
                if fmt == OutputFormat.MARKDOWN and result.markdown:
                    content_items.append(
                        WebContent(
                            url=result.url,
                            title=getattr(result, "title", None),
                            content=result.markdown,
                            content_type=ContentType.MARKDOWN,
                            format=OutputFormat.MARKDOWN,
                            word_count=len(result.markdown.split()),
                            character_count=len(result.markdown),
                            links=getattr(result, "links", []),
                            images=getattr(result, "images", []),
                            status_code=getattr(result, "status_code", 200),
                            extraction_time_ms=getattr(result, "extraction_time", 0.0),
                        )
                    )

                elif fmt == OutputFormat.HTML and result.html:
                    content_items.append(
                        WebContent(
                            url=result.url,
                            title=getattr(result, "title", None),
                            content=result.html,
                            content_type=ContentType.HTML,
                            format=OutputFormat.HTML,
                            word_count=len(result.cleaned_html.split())
                            if result.cleaned_html
                            else 0,
                            character_count=len(result.html),
                            links=getattr(result, "links", []),
                            images=getattr(result, "images", []),
                            status_code=getattr(result, "status_code", 200),
                            extraction_time_ms=getattr(result, "extraction_time", 0.0),
                        )
                    )

                elif fmt == OutputFormat.JSON and result.extracted_content:
                    content_items.append(
                        WebContent(
                            url=result.url,
                            title=getattr(result, "title", None),
                            content=str(result.extracted_content),
                            content_type=ContentType.JSON,
                            format=OutputFormat.JSON,
                            word_count=len(str(result.extracted_content).split()),
                            character_count=len(str(result.extracted_content)),
                            links=getattr(result, "links", []),
                            images=getattr(result, "images", []),
                            status_code=getattr(result, "status_code", 200),
                            extraction_time_ms=getattr(result, "extraction_time", 0.0),
                        )
                    )

        except Exception as e:
            self.logger.warning(
                "Error processing crawl result", error=str(e), url=result.url
            )

        return content_items

    async def screenshot(self, request: WebScreenshotRequest) -> WebScreenshotResult:
        """
        Capture webpage screenshot.

        Args:
            request: Screenshot request configuration

        Returns:
            Screenshot result with image data
        """
        async with self._ensure_initialized():
            start_time = time.time()

            try:
                self.logger.info("Capturing screenshot", url=str(request.url))

                # Configure screenshot parameters
                run_config = CrawlerRunConfig(
                    screenshot=True,
                    wait_for=request.wait_for_selector,
                    user_agent=self.config.user_agent,
                )

                result = await self._crawler.arun(str(request.url), config=run_config)

                if result.success and result.screenshot:
                    # Process screenshot (base64 encoded)
                    capture_time = (time.time() - start_time) * 1000

                    return WebScreenshotResult(
                        url=str(request.url),
                        image_data=result.screenshot,
                        format=request.format,
                        width=request.width,
                        height=request.height,
                        file_size_bytes=len(result.screenshot.encode("utf-8")),
                        capture_time_ms=capture_time,
                    )
                raise Exception(f"Screenshot capture failed: {result.error_message}")

            except Exception as e:
                self.logger.exception(
                    "Screenshot capture failed", url=str(request.url), error=str(e)
                )
                raise

    async def health_check(self) -> WebHealthCheck:
        """
        Perform health check on the web service.

        Returns:
            Health check result with service status
        """
        start_time = time.time()

        try:
            # Check if client is initialized
            if not self._initialized:
                return WebHealthCheck(
                    status="unhealthy",
                    browser_available=False,
                    details={"error": "Client not initialized"},
                )

            # Try a simple crawl operation
            test_url = "https://httpbin.org/html"
            run_config = CrawlerRunConfig(
                check_robots_txt=False, cache_mode=CacheMode.DISABLED
            )

            result = await self._crawler.arun(test_url, config=run_config)

            response_time = (time.time() - start_time) * 1000

            success_rate = 0.0
            if self._stats["total_crawls"] > 0:
                success_rate = (
                    self._stats["successful_crawls"] / self._stats["total_crawls"]
                )

            return WebHealthCheck(
                status="healthy" if result.success else "degraded",
                browser_available=result.success,
                memory_usage_mb=0.0,  # Would implement actual memory tracking
                active_crawls=len(self._active_crawls),
                total_crawls=self._stats["total_crawls"],
                success_rate=success_rate,
                average_response_time_ms=self._stats["average_time_ms"],
                response_time_ms=response_time,
                details={
                    "test_url": test_url,
                    "test_success": result.success,
                    "stats": self._stats,
                },
            )

        except Exception as e:
            response_time = (time.time() - start_time) * 1000

            return WebHealthCheck(
                status="unhealthy",
                browser_available=False,
                response_time_ms=response_time,
                details={"error": str(e)},
            )

    async def extract_content(self, url: str, strategy: ExtractionConfig) -> str | None:
        """
        Extract specific content from URL using configured strategy.

        Args:
            url: Target URL
            strategy: Extraction strategy configuration

        Returns:
            Extracted content or None if failed
        """
        async with self._ensure_initialized():
            try:
                extraction_strategy = self._create_extraction_strategy(strategy)

                run_config = CrawlerRunConfig(
                    extraction_strategy=extraction_strategy,
                    check_robots_txt=self.config.check_robots_txt,
                    user_agent=self.config.user_agent,
                )

                result = await self._crawler.arun(url, config=run_config)

                if result.success:
                    return result.extracted_content

                return None

            except Exception as e:
                self.logger.exception(
                    "Content extraction failed", url=url, error=str(e)
                )
                return None
