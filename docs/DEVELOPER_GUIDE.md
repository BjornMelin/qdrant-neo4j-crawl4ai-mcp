# Developer Guide: Agentic RAG MCP Server

## Table of Contents

1. [Development Environment Setup](#development-environment-setup)
2. [Code Organization & Patterns](#code-organization--patterns)
3. [MCP Tool Development](#mcp-tool-development)
4. [Service Integration Patterns](#service-integration-patterns)
5. [Testing Framework](#testing-framework)
6. [Code Quality & Standards](#code-quality--standards)
7. [Debugging & Development Tools](#debugging--development-tools)
8. [Contributing Guidelines](#contributing-guidelines)

---

## Development Environment Setup

### Prerequisites

Ensure you have the following installed:

- **Python 3.11+** (with asyncio support)
- **uv package manager** (for fast, deterministic package management)
- **Docker & Docker Compose** (for local services)
- **Git** (for version control)
- **VS Code** or similar IDE with Python support

### Quick Start

1. **Clone Repository**

   ```bash
   git clone <repository-url>
   cd qdrant-neo4j-crawl4ai-mcp
   ```

2. **Install Dependencies**

   ```bash
   # Install uv if not already installed
   curl -LsSf https://astral.sh/uv/install.sh | sh

   # Create virtual environment and install dependencies
   uv sync
   ```

3. **Environment Configuration**

   ```bash
   # Copy environment template
   cp .env.example .env

   # Edit configuration
   nano .env
   ```

4. **Start Development Services**

   ```bash
   # Start Qdrant and Neo4j databases
   docker-compose up -d qdrant neo4j

   # Verify services are running
   docker-compose ps
   ```

5. **Run Development Server**

   ```bash
   # Activate virtual environment
   source .venv/bin/activate

   # Start server in development mode
   uv run python -m qdrant_neo4j_crawl4ai_mcp.main
   ```

6. **Verify Installation**

   ```bash
   # Test health endpoint
   curl http://localhost:8000/health

   # Access interactive documentation
   open http://localhost:8000/docs
   ```

### Development Environment Variables

Create a `.env` file with the following configuration:

```bash
# Environment
ENVIRONMENT=development
DEBUG=true
LOG_LEVEL=DEBUG

# Server Configuration
HOST=0.0.0.0
PORT=8000
WORKERS=1

# Authentication
JWT_SECRET_KEY=development-secret-key-change-in-production
JWT_ALGORITHM=HS256
JWT_EXPIRE_MINUTES=1440

# Qdrant Configuration
QDRANT_URL=http://localhost:6333
QDRANT_API_KEY=
DEFAULT_COLLECTION=knowledge_base
DEFAULT_EMBEDDING_MODEL=all-MiniLM-L6-v2

# Neo4j Configuration
NEO4J_URI=bolt://localhost:7687
NEO4J_USER=neo4j
NEO4J_PASSWORD=password
NEO4J_DATABASE=neo4j

# OpenAI Configuration (for GraphRAG)
OPENAI_API_KEY=your-openai-api-key
OPENAI_EMBEDDING_MODEL=text-embedding-ada-002
OPENAI_LLM_MODEL=gpt-3.5-turbo

# Crawl4AI Configuration
CRAWL4AI_MAX_CONCURRENT=5
CRAWL4AI_REQUEST_TIMEOUT=30
CRAWL4AI_USER_AGENT=Agentic-RAG-MCP-Server/1.0

# Development Features
ENABLE_SWAGGER_UI=true
ENABLE_REDOC=true
ENABLE_CORS=true
ALLOWED_ORIGINS=["http://localhost:3000", "http://localhost:8080"]
```

---

## Code Organization & Patterns

### Project Structure

```text
src/qdrant_neo4j_crawl4ai_mcp/
├── main.py                  # FastAPI application entry point
├── config.py               # Configuration management with Pydantic
├── auth.py                 # Authentication & authorization
├── middleware.py           # Custom middleware stack
├── models/                 # Pydantic data models
│   ├── __init__.py
│   ├── vector_models.py    # Vector service models
│   ├── graph_models.py     # Graph service models
│   └── web_models.py       # Web service models
├── services/               # Core business logic
│   ├── __init__.py
│   ├── vector_service.py   # Qdrant vector operations
│   ├── graph_service.py    # Neo4j graph operations
│   ├── web_service.py      # Crawl4AI web operations
│   └── agentic_service.py  # Agentic intelligence coordination
└── tools/                  # MCP tool implementations
    ├── __init__.py
    ├── vector_tools.py     # Vector MCP tools
    ├── graph_tools.py      # Graph MCP tools
    └── web_tools.py        # Web MCP tools
```

### Architectural Patterns

#### 1. Service Layer Pattern

```python
# services/base_service.py
from abc import ABC, abstractmethod
from typing import Any, Dict, Optional
import structlog

logger = structlog.get_logger(__name__)

class BaseService(ABC):
    """Base service class with common patterns."""

    def __init__(self, config: Any):
        self.config = config
        self._client = None
        self._health_status = "unknown"

    @abstractmethod
    async def initialize(self) -> None:
        """Initialize service connections and resources."""
        pass

    @abstractmethod
    async def shutdown(self) -> None:
        """Clean shutdown of service resources."""
        pass

    @abstractmethod
    async def health_check(self) -> Dict[str, Any]:
        """Health check implementation."""
        pass

    async def __aenter__(self):
        await self.initialize()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.shutdown()
```

#### 2. Configuration Management

```python
# config.py
from pydantic import BaseSettings, SecretStr, validator
from typing import List, Optional
import os

class Settings(BaseSettings):
    """Application configuration with validation."""

    # Environment
    environment: str = "development"
    debug: bool = False
    log_level: str = "INFO"

    # Server
    host: str = "0.0.0.0"
    port: int = 8000
    workers: int = 1

    # Authentication
    jwt_secret_key: SecretStr
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 1440

    # Database connections
    qdrant_url: str = "http://localhost:6333"
    qdrant_api_key: Optional[str] = None
    neo4j_uri: str = "bolt://localhost:7687"
    neo4j_user: str = "neo4j"
    neo4j_password: SecretStr

    # OpenAI
    openai_api_key: Optional[SecretStr] = None

    @validator('environment')
    def validate_environment(cls, v):
        if v not in ['development', 'staging', 'production']:
            raise ValueError('Environment must be development, staging, or production')
        return v

    @property
    def is_development(self) -> bool:
        return self.environment == "development"

    @property
    def is_production(self) -> bool:
        return self.environment == "production"

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"

# Singleton pattern for settings
_settings: Optional[Settings] = None

def get_settings() -> Settings:
    global _settings
    if _settings is None:
        _settings = Settings()
    return _settings
```

#### 3. Pydantic Models with Validation

```python
# models/vector_models.py
from pydantic import BaseModel, Field, validator
from typing import List, Dict, Any, Optional
from datetime import datetime
from enum import Enum

class SearchMode(str, Enum):
    SEMANTIC = "semantic"
    KEYWORD = "keyword"
    HYBRID = "hybrid"

class VectorSearchRequest(BaseModel):
    """Request model for vector search operations."""

    query: str = Field(
        ...,
        min_length=1,
        max_length=2000,
        description="Search query text"
    )
    collection_name: str = Field(
        ...,
        regex="^[a-zA-Z0-9_-]+$",
        description="Target collection name"
    )
    limit: int = Field(
        default=10,
        ge=1,
        le=100,
        description="Maximum number of results"
    )
    score_threshold: float = Field(
        default=0.0,
        ge=0.0,
        le=1.0,
        description="Minimum similarity score"
    )
    mode: SearchMode = Field(
        default=SearchMode.SEMANTIC,
        description="Search mode"
    )
    filters: Dict[str, Any] = Field(
        default_factory=dict,
        description="Additional filters"
    )

    @validator('query')
    def validate_query(cls, v):
        if not v.strip():
            raise ValueError('Query cannot be empty or whitespace only')
        return v.strip()

class VectorSearchResult(BaseModel):
    """Individual search result."""

    id: str = Field(..., description="Document ID")
    score: float = Field(..., ge=0.0, le=1.0, description="Similarity score")
    payload: Optional[Dict[str, Any]] = Field(
        None,
        description="Document metadata"
    )
    vector: Optional[List[float]] = Field(
        None,
        description="Document vector (if requested)"
    )

class VectorSearchResponse(BaseModel):
    """Response model for vector search operations."""

    query: str = Field(..., description="Original query")
    collection_name: str = Field(..., description="Searched collection")
    results: List[VectorSearchResult] = Field(
        default_factory=list,
        description="Search results"
    )
    total_results: int = Field(..., ge=0, description="Total matching results")
    search_time_ms: float = Field(..., ge=0, description="Search duration")
    timestamp: datetime = Field(
        default_factory=datetime.utcnow,
        description="Response timestamp"
    )
```

#### 4. Async Service Implementation

```python
# services/vector_service.py
import asyncio
from typing import List, Optional, Dict, Any
from qdrant_client import QdrantClient
from qdrant_client.models import Distance, VectorParams, PointStruct
from sentence_transformers import SentenceTransformer
import structlog

from ..models.vector_models import (
    VectorSearchRequest,
    VectorSearchResponse,
    VectorStoreRequest,
    VectorStoreResponse
)
from .base_service import BaseService

logger = structlog.get_logger(__name__)

class VectorService(BaseService):
    """Qdrant vector database service."""

    def __init__(self, config: VectorServiceConfig):
        super().__init__(config)
        self._embedding_model = None
        self._embedding_cache = {}

    async def initialize(self) -> None:
        """Initialize Qdrant client and embedding model."""
        try:
            # Initialize Qdrant client
            self._client = QdrantClient(
                url=self.config.qdrant_url,
                api_key=self.config.qdrant_api_key,
                timeout=self.config.connection_timeout,
                prefer_grpc=True,  # Better performance
            )

            # Test connection
            await asyncio.get_event_loop().run_in_executor(
                None, self._client.get_collections
            )

            # Initialize embedding model
            self._embedding_model = SentenceTransformer(
                self.config.default_embedding_model
            )

            self._health_status = "healthy"
            logger.info("Vector service initialized successfully")

        except Exception as e:
            self._health_status = "unhealthy"
            logger.exception("Failed to initialize vector service", error=str(e))
            raise

    async def search_vectors(
        self,
        request: VectorSearchRequest
    ) -> VectorSearchResponse:
        """Perform vector similarity search."""
        start_time = asyncio.get_event_loop().time()

        try:
            # Generate query embedding
            query_vector = await self._generate_embedding(request.query)

            # Perform search
            search_result = await asyncio.get_event_loop().run_in_executor(
                None,
                lambda: self._client.search(
                    collection_name=request.collection_name,
                    query_vector=query_vector,
                    limit=request.limit,
                    score_threshold=request.score_threshold,
                    with_payload=request.include_payload,
                    with_vectors=request.include_vectors,
                )
            )

            # Process results
            results = [
                VectorSearchResult(
                    id=str(point.id),
                    score=point.score,
                    payload=point.payload,
                    vector=point.vector
                )
                for point in search_result
            ]

            search_time_ms = (asyncio.get_event_loop().time() - start_time) * 1000

            logger.info(
                "Vector search completed",
                collection=request.collection_name,
                query_length=len(request.query),
                results_count=len(results),
                search_time_ms=search_time_ms
            )

            return VectorSearchResponse(
                query=request.query,
                collection_name=request.collection_name,
                results=results,
                total_results=len(results),
                search_time_ms=search_time_ms
            )

        except Exception as e:
            logger.exception("Vector search failed", error=str(e))
            raise

    async def _generate_embedding(self, text: str) -> List[float]:
        """Generate embedding for text with caching."""
        # Check cache first
        cache_key = hash(text)
        if cache_key in self._embedding_cache:
            return self._embedding_cache[cache_key]

        # Generate embedding
        embedding = await asyncio.get_event_loop().run_in_executor(
            None,
            self._embedding_model.encode,
            text
        )

        # Cache result (limit cache size)
        if len(self._embedding_cache) > 1000:
            # Simple LRU: remove oldest entries
            oldest_keys = list(self._embedding_cache.keys())[:500]
            for key in oldest_keys:
                del self._embedding_cache[key]

        self._embedding_cache[cache_key] = embedding.tolist()
        return embedding.tolist()
```

---

## MCP Tool Development

### Tool Registration Pattern

```python
# tools/vector_tools.py
from fastmcp import FastMCP, Context
from typing import Annotated, Dict, Any, List
import structlog

from ..services.vector_service import VectorService
from ..models.vector_models import VectorSearchRequest

logger = structlog.get_logger(__name__)

def register_vector_tools(mcp: FastMCP, service: VectorService) -> None:
    """Register all vector-related MCP tools."""

    @mcp.tool()
    async def vector_search(
        query: Annotated[str, "Search query text"],
        collection_name: Annotated[str, "Collection to search"] = None,
        limit: Annotated[int, "Maximum results"] = 10,
        score_threshold: Annotated[float, "Minimum similarity score"] = 0.0,
        ctx: Context = None
    ) -> Dict[str, Any]:
        """
        Perform semantic vector search across document embeddings.

        This tool searches for semantically similar content using vector
        embeddings and returns ranked results with similarity scores.
        """
        if ctx:
            ctx.info(f"Vector search requested: {query[:50]}...")

        try:
            # Create search request
            search_request = VectorSearchRequest(
                query=query,
                collection_name=collection_name or "knowledge_base",
                limit=min(limit, 50),  # Cap limit
                score_threshold=max(0.0, min(1.0, score_threshold))
            )

            # Perform search
            response = await service.search_vectors(search_request)

            # Format response for MCP
            return {
                "status": "success",
                "query": response.query,
                "collection": response.collection_name,
                "results": [
                    {
                        "id": result.id,
                        "score": result.score,
                        "content": result.payload.get("content", "") if result.payload else "",
                        "metadata": result.payload or {}
                    }
                    for result in response.results
                ],
                "total_results": response.total_results,
                "search_time_ms": response.search_time_ms
            }

        except Exception as e:
            logger.exception("Vector search tool failed", error=str(e))
            return {
                "status": "error",
                "error": str(e),
                "error_type": type(e).__name__
            }

    @mcp.tool()
    async def vector_store(
        content: Annotated[str, "Content to store"],
        collection_name: Annotated[str, "Target collection"] = None,
        metadata: Annotated[Dict[str, Any], "Document metadata"] = None,
        tags: Annotated[List[str], "Document tags"] = None,
        ctx: Context = None
    ) -> Dict[str, Any]:
        """
        Store document content with vector embedding.

        Converts text content into vector embeddings and stores them
        for later semantic search retrieval.
        """
        if ctx:
            ctx.info(f"Vector store requested: {len(content)} characters")

        try:
            from ..models.vector_models import VectorStoreRequest

            store_request = VectorStoreRequest(
                content=content,
                collection_name=collection_name or "knowledge_base",
                metadata=metadata or {},
                tags=tags or []
            )

            response = await service.store_vector(store_request)

            return {
                "status": "success",
                "id": response.id,
                "collection_name": response.collection_name,
                "vector_dimensions": response.vector_dimensions,
                "embedding_time_ms": response.embedding_time_ms,
                "storage_time_ms": response.storage_time_ms
            }

        except Exception as e:
            logger.exception("Vector store tool failed", error=str(e))
            return {
                "status": "error",
                "error": str(e),
                "error_type": type(e).__name__
            }

    @mcp.tool()
    async def vector_collections(
        ctx: Context = None
    ) -> Dict[str, Any]:
        """
        List all available vector collections with statistics.

        Provides overview of collections, their sizes, and configuration.
        """
        if ctx:
            ctx.info("Vector collections list requested")

        try:
            response = await service.list_collections()

            return {
                "status": "success",
                "collections": [
                    {
                        "name": c.name,
                        "status": c.status.value,
                        "vector_size": c.vector_size,
                        "points_count": c.points_count,
                        "disk_usage_mb": round(c.disk_data_size / (1024 * 1024), 2)
                    }
                    for c in response.collections
                ],
                "total_collections": response.total_collections,
                "total_vectors": response.total_points
            }

        except Exception as e:
            logger.exception("Vector collections tool failed", error=str(e))
            return {
                "status": "error",
                "error": str(e),
                "error_type": type(e).__name__
            }
```

### Tool Testing Pattern

```python
# tests/unit/test_vector_tools.py
import pytest
from unittest.mock import AsyncMock, MagicMock
from fastmcp import FastMCP, Context

from src.qdrant_neo4j_crawl4ai_mcp.tools.vector_tools import register_vector_tools
from src.qdrant_neo4j_crawl4ai_mcp.models.vector_models import (
    VectorSearchResponse,
    VectorSearchResult
)

@pytest.fixture
def mock_vector_service():
    service = AsyncMock()

    # Mock search response
    service.search_vectors.return_value = VectorSearchResponse(
        query="test query",
        collection_name="test_collection",
        results=[
            VectorSearchResult(
                id="doc1",
                score=0.95,
                payload={"content": "Test document content"}
            )
        ],
        total_results=1,
        search_time_ms=150.0
    )

    return service

@pytest.fixture
def mcp_app(mock_vector_service):
    app = FastMCP("test-app")
    register_vector_tools(app, mock_vector_service)
    return app

@pytest.mark.asyncio
async def test_vector_search_tool(mcp_app, mock_vector_service):
    """Test vector search tool functionality."""

    # Get registered tool
    tools = mcp_app.list_tools()
    search_tool = next(tool for tool in tools if tool.name == "vector_search")

    # Execute tool
    result = await search_tool.function(
        query="test query",
        collection_name="test_collection",
        limit=5
    )

    # Verify results
    assert result["status"] == "success"
    assert result["query"] == "test query"
    assert len(result["results"]) == 1
    assert result["results"][0]["score"] == 0.95

    # Verify service was called correctly
    mock_vector_service.search_vectors.assert_called_once()
    call_args = mock_vector_service.search_vectors.call_args[0][0]
    assert call_args.query == "test query"
    assert call_args.collection_name == "test_collection"
    assert call_args.limit == 5

@pytest.mark.asyncio
async def test_vector_search_tool_error_handling(mcp_app, mock_vector_service):
    """Test error handling in vector search tool."""

    # Mock service error
    mock_vector_service.search_vectors.side_effect = Exception("Database connection failed")

    tools = mcp_app.list_tools()
    search_tool = next(tool for tool in tools if tool.name == "vector_search")

    result = await search_tool.function(query="test query")

    # Verify error response
    assert result["status"] == "error"
    assert "Database connection failed" in result["error"]
    assert result["error_type"] == "Exception"
```

---

## Service Integration Patterns

### Agentic Service Coordination

```python
# services/agentic_service.py
import asyncio
from typing import List, Dict, Any, Optional
from enum import Enum
import structlog

from .vector_service import VectorService
from .graph_service import GraphService
from .web_service import WebService
from ..models.agentic_models import (
    AgenticQuery,
    AgenticResponse,
    QueryComplexity,
    ConfidenceScore
)

logger = structlog.get_logger(__name__)

class QueryMode(str, Enum):
    AUTO = "auto"
    VECTOR_ONLY = "vector"
    GRAPH_ONLY = "graph"
    WEB_ONLY = "web"
    HYBRID = "hybrid"

class AgenticService:
    """Intelligent query orchestration across multiple services."""

    def __init__(
        self,
        vector_service: VectorService,
        graph_service: GraphService,
        web_service: WebService
    ):
        self.vector_service = vector_service
        self.graph_service = graph_service
        self.web_service = web_service
        self.fusion_engine = ResultFusionEngine()

    async def process_query(self, query: AgenticQuery) -> AgenticResponse:
        """
        Process query with intelligent routing and result fusion.
        """
        start_time = asyncio.get_event_loop().time()

        try:
            # Analyze query complexity and determine strategy
            complexity = await self._analyze_query_complexity(query.query)
            strategy = await self._determine_strategy(query, complexity)

            logger.info(
                "Agentic query processing started",
                query_length=len(query.query),
                complexity=complexity.value,
                strategy=strategy
            )

            # Execute based on strategy
            if strategy == QueryMode.AUTO or strategy == QueryMode.HYBRID:
                response = await self._execute_hybrid_search(query, complexity)
            elif strategy == QueryMode.VECTOR_ONLY:
                response = await self._execute_vector_search(query)
            elif strategy == QueryMode.GRAPH_ONLY:
                response = await self._execute_graph_search(query)
            elif strategy == QueryMode.WEB_ONLY:
                response = await self._execute_web_search(query)
            else:
                raise ValueError(f"Unknown strategy: {strategy}")

            processing_time = (asyncio.get_event_loop().time() - start_time) * 1000
            response.processing_time_ms = processing_time

            logger.info(
                "Agentic query completed",
                strategy=strategy,
                confidence=response.confidence,
                processing_time_ms=processing_time
            )

            return response

        except Exception as e:
            logger.exception("Agentic query processing failed", error=str(e))
            raise

    async def _analyze_query_complexity(self, query: str) -> QueryComplexity:
        """Analyze query to determine complexity and processing needs."""

        # Simple heuristics for demo - replace with ML model
        query_length = len(query.split())

        # Check for entity relationships (suggests graph search)
        relationship_keywords = [
            "related to", "connected to", "influenced by", "caused by",
            "similar to", "different from", "compared to"
        ]
        has_relationships = any(kw in query.lower() for kw in relationship_keywords)

        # Check for temporal/current info needs (suggests web search)
        temporal_keywords = [
            "latest", "recent", "current", "now", "today", "2025", "2026"
        ]
        needs_current_info = any(kw in query.lower() for kw in temporal_keywords)

        # Check for factual/definitional queries (suggests vector search)
        factual_keywords = [
            "what is", "define", "explain", "how to", "examples of"
        ]
        is_factual = any(kw in query.lower() for kw in factual_keywords)

        # Determine complexity
        if query_length > 20 or (has_relationships and needs_current_info):
            return QueryComplexity.HIGH
        elif query_length > 10 or has_relationships or needs_current_info:
            return QueryComplexity.MEDIUM
        else:
            return QueryComplexity.LOW

    async def _determine_strategy(
        self,
        query: AgenticQuery,
        complexity: QueryComplexity
    ) -> QueryMode:
        """Determine optimal search strategy based on query analysis."""

        if query.mode != QueryMode.AUTO:
            return query.mode

        # Auto-strategy selection based on complexity and content
        if complexity == QueryComplexity.HIGH:
            return QueryMode.HYBRID
        elif "relationship" in query.query.lower() or "connected" in query.query.lower():
            return QueryMode.GRAPH_ONLY
        elif "latest" in query.query.lower() or "current" in query.query.lower():
            return QueryMode.WEB_ONLY
        else:
            return QueryMode.VECTOR_ONLY

    async def _execute_hybrid_search(
        self,
        query: AgenticQuery,
        complexity: QueryComplexity
    ) -> AgenticResponse:
        """Execute parallel search across all services and fuse results."""

        # Create parallel tasks
        tasks = {}

        # Always include vector search for semantic similarity
        tasks["vector"] = asyncio.create_task(
            self._execute_vector_search(query)
        )

        # Add graph search if complexity suggests relationships
        if complexity in [QueryComplexity.MEDIUM, QueryComplexity.HIGH]:
            tasks["graph"] = asyncio.create_task(
                self._execute_graph_search(query)
            )

        # Add web search if query suggests need for current information
        current_info_keywords = ["latest", "recent", "current", "2025"]
        if any(kw in query.query.lower() for kw in current_info_keywords):
            tasks["web"] = asyncio.create_task(
                self._execute_web_search(query)
            )

        # Execute all tasks
        results = {}
        for source, task in tasks.items():
            try:
                results[source] = await task
            except Exception as e:
                logger.warning(f"Search failed for {source}", error=str(e))
                results[source] = None

        # Fuse results
        return await self.fusion_engine.fuse_results(query, results)

    async def _execute_vector_search(self, query: AgenticQuery) -> AgenticResponse:
        """Execute vector-only search."""
        from ..models.vector_models import VectorSearchRequest

        search_request = VectorSearchRequest(
            query=query.query,
            collection_name=query.collection_name or "knowledge_base",
            limit=query.limit
        )

        search_response = await self.vector_service.search_vectors(search_request)

        # Convert to agentic response
        content_parts = []
        total_confidence = 0.0

        for result in search_response.results:
            if result.payload and "content" in result.payload:
                content_parts.append(result.payload["content"])
                total_confidence += result.score

        avg_confidence = total_confidence / len(search_response.results) if search_response.results else 0.0

        return AgenticResponse(
            content="\n\n".join(content_parts),
            source="vector",
            confidence=avg_confidence,
            metadata={
                "search_type": "vector",
                "results_count": len(search_response.results),
                "search_time_ms": search_response.search_time_ms
            }
        )

class ResultFusionEngine:
    """Engine for fusing results from multiple sources using RRF."""

    async def fuse_results(
        self,
        query: AgenticQuery,
        results: Dict[str, Optional[AgenticResponse]]
    ) -> AgenticResponse:
        """Fuse results using Reciprocal Rank Fusion (RRF)."""

        # Filter successful results
        valid_results = {k: v for k, v in results.items() if v is not None}

        if not valid_results:
            return AgenticResponse(
                content="No results found",
                source="none",
                confidence=0.0,
                metadata={"error": "All searches failed"}
            )

        if len(valid_results) == 1:
            # Single source result
            source, response = next(iter(valid_results.items()))
            response.source = source
            return response

        # Multi-source fusion
        content_parts = []
        total_confidence = 0.0
        source_weights = {"vector": 0.4, "graph": 0.3, "web": 0.3}

        for source, response in valid_results.items():
            weight = source_weights.get(source, 0.2)
            weighted_confidence = response.confidence * weight
            total_confidence += weighted_confidence

            content_parts.append(f"**{source.title()} Search Results:**\n{response.content}")

        return AgenticResponse(
            content="\n\n".join(content_parts),
            source="hybrid",
            confidence=min(total_confidence, 1.0),
            metadata={
                "fusion_method": "RRF",
                "sources": list(valid_results.keys()),
                "source_count": len(valid_results)
            }
        )
```

---

## Testing Framework

### Test Structure

```text
tests/
├── conftest.py              # Shared fixtures and configuration
├── unit/                    # Unit tests for individual components
│   ├── test_vector_service.py
│   ├── test_graph_service.py
│   ├── test_web_service.py
│   └── test_agentic_service.py
├── integration/             # Integration tests across services
│   ├── test_cross_service_integration.py
│   └── test_unified_server.py
├── performance/             # Performance and load testing
│   └── test_load_benchmarks.py
├── property/                # Property-based testing
│   └── test_mcp_protocol.py
└── security/               # Security testing
    └── test_auth_security.py
```

### Comprehensive Test Fixtures

```python
# conftest.py
import pytest
import pytest_asyncio
from unittest.mock import AsyncMock, MagicMock
import asyncio
from typing import AsyncGenerator

from src.qdrant_neo4j_crawl4ai_mcp.config import Settings
from src.qdrant_neo4j_crawl4ai_mcp.services.vector_service import VectorService
from src.qdrant_neo4j_crawl4ai_mcp.services.graph_service import GraphService
from src.qdrant_neo4j_crawl4ai_mcp.services.web_service import WebService

@pytest.fixture(scope="session")
def event_loop():
    """Create event loop for async tests."""
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()

@pytest.fixture
def test_settings():
    """Test configuration settings."""
    return Settings(
        environment="test",
        debug=True,
        jwt_secret_key="test-secret-key",
        qdrant_url="http://localhost:6333",
        neo4j_uri="bolt://localhost:7687",
        neo4j_user="neo4j",
        neo4j_password="test-password"
    )

@pytest.fixture
async def mock_vector_service():
    """Mock vector service for testing."""
    service = AsyncMock(spec=VectorService)

    # Configure common return values
    service.health_check.return_value = {
        "status": "healthy",
        "service": "vector",
        "response_time_ms": 5.0
    }

    service.search_vectors.return_value = MagicMock(
        results=[],
        total_results=0,
        search_time_ms=100.0
    )

    return service

@pytest.fixture
async def mock_graph_service():
    """Mock graph service for testing."""
    service = AsyncMock(spec=GraphService)

    service.health_check.return_value = {
        "status": "healthy",
        "service": "graph",
        "response_time_ms": 8.0
    }

    return service

@pytest.fixture
async def mock_web_service():
    """Mock web service for testing."""
    service = AsyncMock(spec=WebService)

    service.health_check.return_value = {
        "status": "healthy",
        "service": "web",
        "response_time_ms": 12.0
    }

    return service

@pytest.fixture
async def test_app(test_settings, mock_vector_service, mock_graph_service, mock_web_service):
    """Create test FastAPI application."""
    from src.qdrant_neo4j_crawl4ai_mcp.main import create_app

    app = create_app(test_settings)

    # Replace services with mocks
    app.state.vector_service = mock_vector_service
    app.state.graph_service = mock_graph_service
    app.state.web_service = mock_web_service

    return app

@pytest.fixture
async def authenticated_client(test_app):
    """HTTP client with authentication."""
    from httpx import AsyncClient
    from src.qdrant_neo4j_crawl4ai_mcp.auth import create_demo_token

    token = create_demo_token("test_user", ["read", "write"], test_app.settings)

    async with AsyncClient(app=test_app, base_url="http://test") as client:
        client.headers.update({"Authorization": f"Bearer {token}"})
        yield client
```

### Integration Test Example

```python
# tests/integration/test_cross_service_integration.py
import pytest
from httpx import AsyncClient

@pytest.mark.asyncio
async def test_hybrid_intelligence_query(authenticated_client: AsyncClient):
    """Test hybrid query across multiple services."""

    query_data = {
        "query": "What are the latest developments in RAG architecture?",
        "mode": "hybrid",
        "limit": 10
    }

    response = await authenticated_client.post(
        "/api/v1/intelligence/query",
        json=query_data
    )

    assert response.status_code == 200
    data = response.json()

    # Verify response structure
    assert "content" in data
    assert "source" in data
    assert "confidence" in data
    assert "metadata" in data
    assert "timestamp" in data

    # Verify confidence score
    assert 0.0 <= data["confidence"] <= 1.0

    # Verify metadata contains processing information
    assert "query_mode" in data["metadata"]
    assert data["metadata"]["query_mode"] == "hybrid"

@pytest.mark.asyncio
async def test_service_health_checks(authenticated_client: AsyncClient):
    """Test all service health endpoints."""

    health_endpoints = [
        "/api/v1/vector/health",
        "/api/v1/graph/health",
        "/api/v1/web/health"
    ]

    for endpoint in health_endpoints:
        response = await authenticated_client.get(endpoint)
        assert response.status_code == 200

        data = response.json()
        assert data["status"] in ["healthy", "degraded", "unhealthy"]
        assert "service" in data
        assert "response_time_ms" in data
        assert "timestamp" in data
```

### Property-Based Testing

```python
# tests/property/test_mcp_protocol.py
import pytest
from hypothesis import given, strategies as st
from hypothesis.strategies import text, integers, floats

from src.qdrant_neo4j_crawl4ai_mcp.models.vector_models import VectorSearchRequest

@given(
    query=text(min_size=1, max_size=100),
    limit=integers(min_value=1, max_value=50),
    score_threshold=floats(min_value=0.0, max_value=1.0)
)
def test_vector_search_request_validation(query, limit, score_threshold):
    """Property-based test for vector search request validation."""

    try:
        request = VectorSearchRequest(
            query=query,
            collection_name="test_collection",
            limit=limit,
            score_threshold=score_threshold
        )

        # If creation succeeds, verify properties
        assert len(request.query.strip()) > 0
        assert 1 <= request.limit <= 50
        assert 0.0 <= request.score_threshold <= 1.0

    except ValueError:
        # Expected for invalid inputs
        pass

@pytest.mark.asyncio
@given(
    queries=st.lists(text(min_size=1, max_size=50), min_size=1, max_size=10)
)
async def test_batch_processing_properties(queries, mock_vector_service):
    """Test batch processing maintains ordering and completeness."""

    # Mock service responses
    mock_vector_service.search_vectors.return_value = MagicMock(
        results=[],
        total_results=0,
        search_time_ms=100.0
    )

    # Process queries
    results = []
    for query in queries:
        request = VectorSearchRequest(
            query=query,
            collection_name="test",
            limit=5
        )
        result = await mock_vector_service.search_vectors(request)
        results.append(result)

    # Verify properties
    assert len(results) == len(queries)  # Completeness
    assert all(r is not None for r in results)  # No None results
```

### Performance Testing

```python
# tests/performance/test_load_benchmarks.py
import pytest
import asyncio
import time
from typing import List

@pytest.mark.asyncio
async def test_concurrent_requests_performance(test_app):
    """Test performance under concurrent load."""

    async def make_request():
        from httpx import AsyncClient

        async with AsyncClient(app=test_app, base_url="http://test") as client:
            response = await client.get("/health")
            return response.status_code == 200

    # Test with increasing concurrency
    concurrency_levels = [1, 5, 10, 25, 50]
    results = {}

    for concurrency in concurrency_levels:
        start_time = time.time()

        # Create concurrent tasks
        tasks = [make_request() for _ in range(concurrency)]
        responses = await asyncio.gather(*tasks, return_exceptions=True)

        end_time = time.time()
        duration = end_time - start_time

        # Analyze results
        successful = sum(1 for r in responses if r is True)
        failed = len(responses) - successful

        results[concurrency] = {
            "duration": duration,
            "successful": successful,
            "failed": failed,
            "requests_per_second": len(responses) / duration
        }

        # Basic performance assertions
        assert successful > 0, f"No successful requests at concurrency {concurrency}"
        assert duration < 10.0, f"Request took too long: {duration}s"

    # Performance regression check
    baseline_rps = results[1]["requests_per_second"]
    high_load_rps = results[50]["requests_per_second"]

    # Should maintain at least 50% of baseline performance under load
    assert high_load_rps > baseline_rps * 0.5, "Performance degraded significantly under load"
```

---

## Code Quality & Standards

### Linting and Formatting

The project uses **ruff** for both linting and formatting:

```bash
# Format all code
uv run ruff format .

# Lint and fix issues
uv run ruff check . --fix

# Lint without fixes
uv run ruff check .
```

### Ruff Configuration

```toml
# pyproject.toml
[tool.ruff]
target-version = "py311"
line-length = 88
select = [
    "E",   # pycodestyle errors
    "W",   # pycodestyle warnings
    "F",   # Pyflakes
    "I",   # isort
    "B",   # flake8-bugbear
    "C4",  # flake8-comprehensions
    "UP",  # pyupgrade
]
ignore = [
    "E501",  # line too long, handled by formatter
    "B008",  # do not perform function calls in argument defaults
]

[tool.ruff.format]
quote-style = "double"
indent-style = "space"

[tool.ruff.lint.isort]
known-first-party = ["qdrant_neo4j_crawl4ai_mcp"]
```

### Type Checking

Use **mypy** for static type checking:

```bash
# Type check entire project
uv run mypy src/

# Type check specific file
uv run mypy src/qdrant_neo4j_crawl4ai_mcp/main.py
```

### MyPy Configuration

```toml
# pyproject.toml
[tool.mypy]
python_version = "3.11"
strict = true
warn_return_any = true
warn_unused_configs = true
disallow_untyped_defs = true
disallow_incomplete_defs = true
check_untyped_defs = true
disallow_untyped_decorators = true

[[tool.mypy.overrides]]
module = [
    "qdrant_client.*",
    "neo4j.*",
    "crawl4ai.*",
    "sentence_transformers.*"
]
ignore_missing_imports = true
```

### Pre-commit Hooks

```yaml
# .pre-commit-config.yaml
repos:
  - repo: https://github.com/astral-sh/ruff-pre-commit
    rev: v0.1.6
    hooks:
      - id: ruff
        args: [--fix, --exit-non-zero-on-fix]
      - id: ruff-format

  - repo: https://github.com/pre-commit/mirrors-mypy
    rev: v1.7.0
    hooks:
      - id: mypy
        additional_dependencies: [types-all]
```

### Code Standards

#### 1. Async/Await Patterns

```python
# Good: Proper async context management
async def process_request(request: Request) -> Response:
    async with service_context() as services:
        result = await services.vector.search(request.query)
        return format_response(result)

# Bad: Blocking operations in async context
async def process_request(request: Request) -> Response:
    result = blocking_search(request.query)  # Blocks event loop
    return format_response(result)
```

#### 2. Error Handling

```python
# Good: Specific exception handling with logging
async def search_documents(query: str) -> SearchResult:
    try:
        return await vector_service.search(query)
    except ConnectionError as e:
        logger.exception("Database connection failed", error=str(e))
        raise ServiceUnavailableError("Vector search temporarily unavailable")
    except ValidationError as e:
        logger.warning("Invalid query format", query=query, error=str(e))
        raise BadRequestError("Query format is invalid")

# Bad: Generic exception handling
async def search_documents(query: str) -> SearchResult:
    try:
        return await vector_service.search(query)
    except Exception:
        return None  # Silent failure
```

#### 3. Configuration Management

```python
# Good: Validated configuration with defaults
class ServiceConfig(BaseSettings):
    timeout: int = Field(default=30, ge=1, le=300)
    max_retries: int = Field(default=3, ge=0, le=10)

    @validator('timeout')
    def validate_timeout(cls, v):
        if v < 1:
            raise ValueError("Timeout must be positive")
        return v

# Bad: Unvalidated configuration
class ServiceConfig:
    def __init__(self):
        self.timeout = os.getenv("TIMEOUT", "30")  # String, not int
        self.max_retries = int(os.getenv("RETRIES", "-1"))  # No validation
```

---

## Debugging & Development Tools

### Development Server

```bash
# Run with hot reload
uv run uvicorn src.qdrant_neo4j_crawl4ai_mcp.main:create_app --reload --host 0.0.0.0 --port 8000

# Run with debug logging
DEBUG=true LOG_LEVEL=DEBUG uv run python -m qdrant_neo4j_crawl4ai_mcp.main
```

### Interactive API Documentation

When `DEBUG=true`, the server provides interactive documentation:

- **Swagger UI**: <http://localhost:8000/docs>
- **ReDoc**: <http://localhost:8000/redoc>
- **OpenAPI Schema**: <http://localhost:8000/openapi.json>

### Debugging Tools

#### 1. Structured Logging

```python
import structlog

logger = structlog.get_logger(__name__)

# Rich context logging
logger.info(
    "Processing user request",
    user_id=user.id,
    query_length=len(query),
    processing_mode=mode,
    request_id=request_id
)
```

#### 2. Health Check Debugging

```bash
# Check overall health
curl http://localhost:8000/health | jq

# Check specific service health
curl -H "Authorization: Bearer $TOKEN" http://localhost:8000/api/v1/vector/health | jq
```

#### 3. Metrics Debugging

```bash
# View Prometheus metrics
curl http://localhost:8000/metrics

# Filter specific metrics
curl http://localhost:8000/metrics | grep "http_requests_total"
```

#### 4. Database Connection Testing

```python
# Test Qdrant connection
from qdrant_client import QdrantClient

client = QdrantClient(url="http://localhost:6333")
print(client.get_collections())

# Test Neo4j connection
from neo4j import GraphDatabase

driver = GraphDatabase.driver("bolt://localhost:7687", auth=("neo4j", "password"))
with driver.session() as session:
    result = session.run("RETURN 1 as test")
    print(result.single()["test"])
```

### VS Code Configuration

```json
// .vscode/launch.json
{
    "version": "0.2.0",
    "configurations": [
        {
            "name": "Debug MCP Server",
            "type": "python",
            "request": "launch",
            "module": "qdrant_neo4j_crawl4ai_mcp.main",
            "envFile": "${workspaceFolder}/.env",
            "console": "integratedTerminal",
            "justMyCode": false
        }
    ]
}

// .vscode/settings.json
{
    "python.defaultInterpreterPath": ".venv/bin/python",
    "python.linting.enabled": true,
    "python.linting.ruffEnabled": true,
    "python.formatting.provider": "ruff",
    "python.testing.pytestEnabled": true,
    "python.testing.pytestArgs": ["tests/"]
}
```

---

## Contributing Guidelines

### Development Workflow

1. **Fork and Clone**

   ```bash
   git clone <your-fork-url>
   cd qdrant-neo4j-crawl4ai-mcp
   git remote add upstream <original-repo-url>
   ```

2. **Create Feature Branch**

   ```bash
   git checkout -b feature/your-feature-name
   ```

3. **Development Setup**

   ```bash
   uv sync
   pre-commit install
   ```

4. **Make Changes**

   - Follow code standards and patterns
   - Add comprehensive tests
   - Update documentation

5. **Quality Checks**

   ```bash
   # Format and lint
   uv run ruff format .
   uv run ruff check . --fix

   # Type checking
   uv run mypy src/

   # Run tests
   uv run pytest --cov=src --cov-report=html
   ```

6. **Commit and Push**

   ```bash
   git add .
   git commit -m "feat: add new vector search optimization"
   git push origin feature/your-feature-name
   ```

7. **Create Pull Request**

   - Use descriptive title and description
   - Link to related issues
   - Ensure all checks pass

### Commit Message Format

Follow conventional commit format:

```text
type(scope): description

[optional body]

[optional footer]
```

Types:

- `feat`: New feature
- `fix`: Bug fix
- `docs`: Documentation changes
- `style`: Formatting changes
- `refactor`: Code refactoring
- `test`: Adding tests
- `chore`: Maintenance tasks

Examples:

```text
feat(vector): add hybrid search capabilities
fix(auth): resolve JWT token expiration issue
docs(api): update endpoint documentation
test(integration): add cross-service test coverage
```

### Code Review Guidelines

#### For Contributors

- Keep changes focused and atomic
- Add tests for new functionality
- Update documentation
- Follow existing patterns and conventions
- Consider performance and security implications

#### For Reviewers

- Check for security vulnerabilities
- Verify test coverage
- Ensure code follows project standards
- Test functionality locally when needed
- Provide constructive feedback

### Release Process

1. **Version Bump**

   ```bash
   # Update version in pyproject.toml
   # Update CHANGELOG.md
   ```

2. **Create Release PR**

   ```bash
   git checkout -b release/v1.1.0
   git commit -m "chore: prepare release v1.1.0"
   ```

3. **Tag Release**

   ```bash
   git tag -a v1.1.0 -m "Release v1.1.0"
   git push origin v1.1.0
   ```

4. **Deploy**

- Automated deployment via CI/CD
- Manual verification in staging
- Production deployment approval

This developer guide provides comprehensive instructions for setting up, developing, testing, and contributing to the Agentic RAG MCP Server. Follow these patterns and standards to maintain code quality and ensure consistent development practices across the project.
