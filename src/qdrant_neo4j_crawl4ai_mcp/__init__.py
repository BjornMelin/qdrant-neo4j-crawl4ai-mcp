"""
Unified MCP Intelligence Server

A production-ready Model Context Protocol server that abstracts Qdrant vector search,
Neo4j knowledge graphs, and Crawl4AI web intelligence into a cohesive platform for
AI assistant interactions.

This package provides:
- FastMCP 2.0 server foundation with service composition
- JWT authentication and authorization
- Rate limiting and security middleware
- Comprehensive error handling and logging
- Health checks and monitoring
- Production-grade deployment patterns

Author: Portfolio Project
License: MIT
"""

from qdrant_neo4j_crawl4ai_mcp.config import Settings, get_settings
from qdrant_neo4j_crawl4ai_mcp.main import create_app, main

__version__ = "1.0.0"
__author__ = "Portfolio Project"
__email__ = "developer@example.com"

__all__ = [
    "Settings",
    "__version__",
    "create_app",
    "get_settings",
    "main",
]
