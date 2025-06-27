# Multi-stage Docker build for Qdrant Neo4j Crawl4AI MCP Server
# Optimized for security, performance, and minimal attack surface

# =============================================================================
# Builder Stage - Install dependencies and build application
# =============================================================================

FROM python:3.11-slim as builder

# Set build arguments
ARG BUILD_DATE
ARG VERSION=1.0.0
ARG VCS_REF

# Add metadata labels
LABEL maintainer="developer@example.com" \
      version="${VERSION}" \
      description="Qdrant Neo4j Crawl4AI MCP Server" \
      build-date="${BUILD_DATE}" \
      vcs-ref="${VCS_REF}"

# Create non-root user early
RUN groupadd -r appuser && useradd -r -g appuser appuser

# Install system dependencies for building
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Install uv package manager
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

# Set working directory
WORKDIR /app

# Copy dependency files
COPY pyproject.toml ./
COPY src/ ./src/

# Create virtual environment and install dependencies
RUN uv venv /app/.venv && \
    uv pip install -e . && \
    uv pip install uvicorn[standard]

# =============================================================================
# Runtime Stage - Minimal production image
# =============================================================================

FROM python:3.11-slim

# Install runtime dependencies and security updates
RUN apt-get update && apt-get upgrade -y && \
    apt-get install -y --no-install-recommends \
    tini \
    curl \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/* \
    && rm -rf /tmp/* \
    && rm -rf /var/tmp/*

# Create non-root user
RUN groupadd -r appuser && useradd -r -g appuser appuser

# Set working directory
WORKDIR /app

# Copy virtual environment from builder stage
COPY --from=builder --chown=appuser:appuser /app/.venv /app/.venv

# Copy application code
COPY --chown=appuser:appuser src/ ./src/
COPY --chown=appuser:appuser pyproject.toml ./

# Create directories for logs and data
RUN mkdir -p /app/logs /app/data && \
    chown -R appuser:appuser /app

# Switch to non-root user
USER appuser

# Set environment variables
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONPATH=/app/src \
    PATH="/app/.venv/bin:$PATH" \
    HOME=/app

# Expose port
EXPOSE 8000

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

# Use tini as init system for proper signal handling
ENTRYPOINT ["tini", "--"]

# Default command
CMD ["python", "-m", "qdrant_neo4j_crawl4ai_mcp.main"]

# =============================================================================
# Build metadata and labels
# =============================================================================

LABEL org.opencontainers.image.title="Qdrant Neo4j Crawl4AI MCP Server" \
      org.opencontainers.image.description="Production-ready MCP server abstracting Qdrant, Neo4j, and Crawl4AI" \
      org.opencontainers.image.version="${VERSION}" \
      org.opencontainers.image.created="${BUILD_DATE}" \
      org.opencontainers.image.revision="${VCS_REF}" \
      org.opencontainers.image.source="https://github.com/your-username/qdrant-neo4j-crawl4ai-mcp" \
      org.opencontainers.image.licenses="MIT" \
      org.opencontainers.image.vendor="Portfolio Project" \
      org.opencontainers.image.authors="developer@example.com"