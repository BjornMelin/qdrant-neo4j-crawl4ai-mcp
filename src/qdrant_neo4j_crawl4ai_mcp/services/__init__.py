"""
Service layer for the Unified MCP Server.

This package contains all business logic services that integrate with
external systems and provide high-level operations for the application.
"""

from .qdrant_client import QdrantClient, QdrantConnectionError, QdrantOperationError
from .vector_service import EmbeddingService, VectorService, VectorServiceError

__all__ = [
    "EmbeddingService",
    # Qdrant client
    "QdrantClient",
    "QdrantConnectionError",
    "QdrantOperationError",
    # Vector service
    "VectorService",
    "VectorServiceError",
]
