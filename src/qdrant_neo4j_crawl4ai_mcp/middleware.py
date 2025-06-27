"""
Security and monitoring middleware for the Unified MCP Server.

Provides comprehensive middleware stack including:
- Security headers and OWASP compliance
- Rate limiting and request throttling
- Structured logging and audit trails
- Performance monitoring and metrics
- Error handling and recovery
"""

from collections.abc import Callable
from datetime import datetime
import time

from fastapi import HTTPException, Request, Response, status
from fastapi.responses import JSONResponse
from prometheus_client import Counter, Histogram
from starlette.middleware.base import BaseHTTPMiddleware
import structlog

from qdrant_neo4j_crawl4ai_mcp.auth import rate_limiter
from qdrant_neo4j_crawl4ai_mcp.config import Settings, get_settings

# Set up structured logging
logger = structlog.get_logger(__name__)

# Prometheus metrics
REQUEST_COUNT = Counter(
    "http_requests_total", "Total HTTP requests", ["method", "endpoint", "status_code"]
)

REQUEST_DURATION = Histogram(
    "http_request_duration_seconds",
    "HTTP request duration in seconds",
    ["method", "endpoint"],
)

RATE_LIMIT_EXCEEDED = Counter(
    "rate_limit_exceeded_total", "Total rate limit exceeded events", ["client_ip"]
)


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """
    Middleware to add comprehensive security headers.

    Implements OWASP security headers and best practices for
    defense in depth security architecture.
    """

    def __init__(self, app, settings: Settings) -> None:
        super().__init__(app)
        self.settings = settings

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        """Add security headers to all responses."""
        response = await call_next(request)

        # OWASP Security Headers
        headers = {
            # Prevent MIME type sniffing
            "X-Content-Type-Options": "nosniff",
            # Prevent embedding in frames
            "X-Frame-Options": "DENY",
            # XSS Protection (legacy, but still useful)
            "X-XSS-Protection": "1; mode=block",
            # HSTS (only in production with HTTPS)
            "Strict-Transport-Security": (
                f"max-age={self.settings.hsts_max_age}; includeSubDomains; preload"
                if self.settings.is_production
                else "max-age=0"
            ),
            # Content Security Policy
            "Content-Security-Policy": self.settings.csp_policy,
            # Referrer Policy
            "Referrer-Policy": "strict-origin-when-cross-origin",
            # Permissions Policy (Feature Policy)
            "Permissions-Policy": (
                "geolocation=(), microphone=(), camera=(), payment=(), "
                "usb=(), magnetometer=(), gyroscope=(), speaker=()"
            ),
            # Remove server information
            "Server": "",
            # Cross-Origin policies
            "Cross-Origin-Embedder-Policy": "require-corp",
            "Cross-Origin-Opener-Policy": "same-origin",
            "Cross-Origin-Resource-Policy": "same-origin",
        }

        # Add all security headers
        for header, value in headers.items():
            response.headers[header] = value

        return response


class RateLimitMiddleware(BaseHTTPMiddleware):
    """
    Rate limiting middleware with configurable limits.

    Provides per-IP rate limiting with burst allowance and
    graceful degradation for high traffic scenarios.
    """

    def __init__(self, app, settings: Settings) -> None:
        super().__init__(app)
        self.settings = settings

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        """Apply rate limiting to requests."""
        client_ip = self._get_client_ip(request)

        # Skip rate limiting for health checks and metrics
        if request.url.path in ["/health", "/metrics", "/ready"]:
            return await call_next(request)

        # Check rate limit
        is_allowed = rate_limiter.is_allowed(
            identifier=client_ip,
            limit=self.settings.rate_limit_per_minute,
            window_seconds=60,
        )

        if not is_allowed:
            # Log rate limit exceeded
            logger.warning(
                "Rate limit exceeded",
                client_ip=client_ip,
                path=request.url.path,
                method=request.method,
                user_agent=request.headers.get("user-agent", "unknown"),
            )

            # Update metrics
            RATE_LIMIT_EXCEEDED.labels(client_ip=client_ip).inc()

            # Return rate limit error
            return JSONResponse(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                content={
                    "error": "Rate limit exceeded",
                    "detail": f"Maximum {self.settings.rate_limit_per_minute} requests per minute",
                    "retry_after": 60,
                },
                headers={"Retry-After": "60"},
            )

        return await call_next(request)

    def _get_client_ip(self, request: Request) -> str:
        """Extract client IP address from request."""
        # Check for forwarded IP headers (common in production behind proxies)
        forwarded_for = request.headers.get("X-Forwarded-For")
        if forwarded_for:
            # Take the first IP in the chain
            return forwarded_for.split(",")[0].strip()

        real_ip = request.headers.get("X-Real-IP")
        if real_ip:
            return real_ip

        # Fall back to direct client IP
        return request.client.host if request.client else "unknown"


class LoggingMiddleware(BaseHTTPMiddleware):
    """
    Comprehensive request/response logging middleware.

    Provides structured logging with security event correlation,
    performance metrics, and audit trail capabilities.
    """

    def __init__(self, app, settings: Settings) -> None:
        super().__init__(app)
        self.settings = settings

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        """Log request and response details."""
        start_time = time.time()

        # Extract request information
        client_ip = self._get_client_ip(request)
        method = request.method
        path = request.url.path
        query_params = str(request.query_params) if request.query_params else None
        user_agent = request.headers.get("user-agent", "unknown")
        request_id = request.headers.get(
            "X-Request-ID", f"req_{int(time.time() * 1000)}"
        )

        # Log incoming request
        logger.info(
            "Request started",
            request_id=request_id,
            method=method,
            path=path,
            query_params=query_params,
            client_ip=client_ip,
            user_agent=user_agent,
            timestamp=datetime.utcnow().isoformat(),
        )

        try:
            # Process request
            response = await call_next(request)

            # Calculate response time
            duration = time.time() - start_time

            # Log successful response
            logger.info(
                "Request completed",
                request_id=request_id,
                method=method,
                path=path,
                status_code=response.status_code,
                duration_ms=round(duration * 1000, 2),
                client_ip=client_ip,
                timestamp=datetime.utcnow().isoformat(),
            )

            # Update metrics
            REQUEST_COUNT.labels(
                method=method,
                endpoint=self._normalize_path(path),
                status_code=response.status_code,
            ).inc()

            REQUEST_DURATION.labels(
                method=method, endpoint=self._normalize_path(path)
            ).observe(duration)

            # Add request ID to response headers
            response.headers["X-Request-ID"] = request_id

            return response

        except Exception as e:
            # Calculate error response time
            duration = time.time() - start_time

            # Log error
            logger.exception(
                "Request failed",
                request_id=request_id,
                method=method,
                path=path,
                error=str(e),
                error_type=type(e).__name__,
                duration_ms=round(duration * 1000, 2),
                client_ip=client_ip,
                timestamp=datetime.utcnow().isoformat(),
            )

            # Update error metrics
            REQUEST_COUNT.labels(
                method=method, endpoint=self._normalize_path(path), status_code="500"
            ).inc()

            # Re-raise the exception
            raise

    def _get_client_ip(self, request: Request) -> str:
        """Extract client IP address from request."""
        forwarded_for = request.headers.get("X-Forwarded-For")
        if forwarded_for:
            return forwarded_for.split(",")[0].strip()

        real_ip = request.headers.get("X-Real-IP")
        if real_ip:
            return real_ip

        return request.client.host if request.client else "unknown"

    def _normalize_path(self, path: str) -> str:
        """Normalize path for metrics (remove path parameters)."""
        # Replace dynamic path segments with placeholders
        path_parts = path.split("/")
        normalized_parts = []

        for part in path_parts:
            # Replace UUIDs and IDs with placeholders
            if self._looks_like_id(part):
                normalized_parts.append("{id}")
            else:
                normalized_parts.append(part)

        return "/".join(normalized_parts)

    def _looks_like_id(self, part: str) -> bool:
        """Check if path part looks like an ID."""
        # Check for common ID patterns
        if len(part) > 8 and (
            part.isalnum()  # Alphanumeric IDs
            or "-" in part  # UUIDs
            or "_" in part  # Underscore IDs
        ):
            return True
        return False


class ErrorHandlingMiddleware(BaseHTTPMiddleware):
    """
    Global error handling middleware.

    Provides consistent error responses, security-aware error
    messages, and comprehensive error logging.
    """

    def __init__(self, app, settings: Settings) -> None:
        super().__init__(app)
        self.settings = settings

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        """Handle errors and provide consistent responses."""
        try:
            return await call_next(request)

        except HTTPException:
            # Re-raise HTTP exceptions (handled by FastAPI)
            raise

        except Exception as e:
            # Log unexpected errors
            logger.exception(
                "Unhandled exception",
                error=str(e),
                error_type=type(e).__name__,
                path=request.url.path,
                method=request.method,
                client_ip=request.client.host if request.client else "unknown",
            )

            # Return generic error in production, detailed in development
            if self.settings.is_production:
                error_detail = "Internal server error"
            else:
                error_detail = f"{type(e).__name__}: {e!s}"

            return JSONResponse(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                content={
                    "error": "Internal Server Error",
                    "detail": error_detail,
                    "timestamp": datetime.utcnow().isoformat(),
                },
            )


class PerformanceMiddleware(BaseHTTPMiddleware):
    """
    Performance monitoring middleware.

    Tracks response times, memory usage, and performance
    metrics for monitoring and optimization.
    """

    def __init__(self, app, settings: Settings) -> None:
        super().__init__(app)
        self.settings = settings

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        """Monitor request performance."""
        start_time = time.time()

        # Add performance headers to response
        response = await call_next(request)

        # Calculate performance metrics
        duration = time.time() - start_time

        # Add performance headers
        response.headers["X-Response-Time"] = f"{duration:.3f}s"
        response.headers["X-Process-Time"] = f"{round(duration * 1000, 2)}ms"

        # Log slow requests
        if duration > 2.0:  # Warn for requests over 2 seconds
            logger.warning(
                "Slow request detected",
                path=request.url.path,
                method=request.method,
                duration_ms=round(duration * 1000, 2),
                client_ip=request.client.host if request.client else "unknown",
            )

        return response


def setup_middleware(app, settings: Settings | None = None) -> None:
    """
    Set up all middleware for the application.

    Args:
        app: FastAPI application instance
        settings: Application settings (optional, will be loaded if not provided)
    """
    if settings is None:
        settings = get_settings()

    # Add middleware in reverse order (last added is executed first)

    # Performance monitoring (outermost)
    app.add_middleware(PerformanceMiddleware, settings=settings)

    # Error handling
    app.add_middleware(ErrorHandlingMiddleware, settings=settings)

    # Request/response logging
    app.add_middleware(LoggingMiddleware, settings=settings)

    # Rate limiting
    app.add_middleware(RateLimitMiddleware, settings=settings)

    # Security headers (innermost, closest to response)
    app.add_middleware(SecurityHeadersMiddleware, settings=settings)

    logger.info("Middleware stack configured", environment=settings.environment)
