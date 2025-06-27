# API Reference: Agentic RAG MCP Server

## Table of Contents

1. [API Overview](#api-overview)
2. [Authentication](#authentication)
3. [Intelligence Endpoints](#intelligence-endpoints)
4. [Vector Intelligence API](#vector-intelligence-api)
5. [Graph Intelligence API](#graph-intelligence-api)
6. [Web Intelligence API](#web-intelligence-api)
7. [Administrative API](#administrative-api)
8. [Error Handling](#error-handling)
9. [Rate Limiting](#rate-limiting)
10. [SDK Examples](#sdk-examples)

---

## API Overview

The Agentic RAG MCP Server provides a RESTful API for accessing multi-modal AI intelligence services. The API is built on FastAPI with automatic OpenAPI documentation and supports both individual service access and unified agentic intelligence queries.

### Base URL

```
Production: https://your-domain.com/api/v1
Development: http://localhost:8000/api/v1
```

### API Versioning

- **Current Version**: v1
- **Version Header**: `API-Version: v1` (optional)
- **URL Versioning**: `/api/v1/` (required)

### Content Types

- **Request**: `application/json`
- **Response**: `application/json`
- **Authentication**: `Bearer <token>`

### Response Format

All API responses follow a consistent structure:

```json
{
  "status": "success|error",
  "data": {...},
  "message": "Human readable message",
  "timestamp": "2025-06-27T10:30:00Z",
  "request_id": "uuid-string"
}
```

---

## Authentication

### JWT Bearer Token Authentication

All API endpoints (except `/health` and `/auth/*`) require JWT authentication.

#### POST /auth/token

Generate an access token for API authentication.

**Request:**

```http
POST /auth/token
Content-Type: application/json

{
  "username": "your_username",
  "scopes": ["read", "write", "admin"]
}
```

**Response:**

```json
{
  "access_token": "eyJ0eXAiOiJKV1QiLCJhbGciOiJIUzI1NiJ9...",
  "token_type": "bearer",
  "expires_in": 86400,
  "scopes": ["read", "write"]
}
```

**Scopes:**

- `read`: Access to search and query operations
- `write`: Access to data storage and modification
- `admin`: Access to administrative functions

### Authentication Headers

```http
Authorization: Bearer eyJ0eXAiOiJKV1QiLCJhbGciOiJIUzI1NiJ9...
```

---

## Intelligence Endpoints

### POST /intelligence/query

Unified agentic intelligence query that automatically routes to appropriate services and fuses results.

**Authentication:** Requires `read` scope

**Request:**

```json
{
  "query": "What are the latest developments in RAG architecture?",
  "mode": "auto",
  "filters": {
    "domain": "AI/ML",
    "recency": "1_month",
    "confidence_threshold": 0.7
  },
  "limit": 10,
  "include_sources": true
}
```

**Parameters:**

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `query` | string | Yes | - | Natural language query (1-2000 chars) |
| `mode` | string | No | "auto" | Processing mode: auto, vector, graph, web, hybrid |
| `filters` | object | No | {} | Query-specific filters |
| `limit` | integer | No | 10 | Maximum results (1-100) |
| `include_sources` | boolean | No | true | Include source attribution |

**Response:**

```json
{
  "content": "Based on recent research and developments...",
  "source": "hybrid",
  "confidence": 0.92,
  "metadata": {
    "query_complexity": "high",
    "strategy_used": "parallel_hybrid",
    "sources_consulted": ["vector", "graph", "web"],
    "vector_results": 8,
    "graph_paths": 3,
    "web_sources": 5,
    "fusion_method": "RRF",
    "processing_time_ms": 1247
  },
  "sources": [
    {
      "type": "vector",
      "confidence": 0.89,
      "content": "Vector search results...",
      "document_id": "doc_123"
    },
    {
      "type": "graph",
      "confidence": 0.84,
      "content": "Graph relationship analysis...",
      "entities": ["RAG", "Architecture", "LLM"]
    },
    {
      "type": "web", 
      "confidence": 0.91,
      "content": "Recent web content...",
      "url": "https://example.com/rag-paper"
    }
  ],
  "timestamp": "2025-06-27T10:30:00Z"
}
```

---

## Vector Intelligence API

### POST /vector/search

Perform semantic vector search using Qdrant.

**Authentication:** Requires `read` scope

**Request:**

```json
{
  "query": "machine learning transformer architectures",
  "collection_name": "knowledge_base",
  "limit": 5,
  "score_threshold": 0.7,
  "search_mode": "semantic",
  "filters": {
    "content_type": "research_paper",
    "year": {"$gte": 2023}
  },
  "include_payload": true,
  "include_vectors": false
}
```

**Parameters:**

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `query` | string | Yes | - | Search query text |
| `collection_name` | string | No | "knowledge_base" | Target collection |
| `limit` | integer | No | 10 | Maximum results (1-100) |
| `score_threshold` | float | No | 0.0 | Minimum similarity score (0.0-1.0) |
| `search_mode` | string | No | "semantic" | Search mode: semantic, keyword, hybrid |
| `filters` | object | No | {} | Qdrant filters |
| `include_payload` | boolean | No | true | Include document metadata |
| `include_vectors` | boolean | No | false | Include embedding vectors |

**Response:**

```json
{
  "query": "machine learning transformer architectures",
  "collection_name": "knowledge_base",
  "results": [
    {
      "id": "doc_789",
      "score": 0.94,
      "payload": {
        "title": "Attention Is All You Need",
        "authors": ["Vaswani et al."],
        "content": "The transformer architecture...",
        "year": 2017,
        "citations": 45000,
        "content_type": "research_paper"
      },
      "vector": null
    }
  ],
  "total_results": 1,
  "search_time_ms": 45.2,
  "timestamp": "2025-06-27T10:30:00Z"
}
```

### POST /vector/store

Store document with vector embedding in Qdrant.

**Authentication:** Requires `write` scope

**Request:**

```json
{
  "content": "The transformer architecture revolutionized natural language processing...",
  "collection_name": "knowledge_base",
  "content_type": "article",
  "source": "https://example.com/transformer-article",
  "metadata": {
    "title": "Understanding Transformers",
    "author": "Jane Doe",
    "year": 2025,
    "topic": "deep_learning"
  },
  "tags": ["AI", "NLP", "transformers", "attention"],
  "embedding_model": "all-MiniLM-L6-v2"
}
```

**Response:**

```json
{
  "id": "point_456",
  "collection_name": "knowledge_base",
  "vector_dimensions": 384,
  "embedding_time_ms": 156.3,
  "storage_time_ms": 23.7,
  "status": "stored",
  "timestamp": "2025-06-27T10:30:00Z"
}
```

### GET /vector/collections

List all vector collections with statistics.

**Authentication:** Requires `read` scope

**Response:**

```json
{
  "collections": [
    {
      "name": "knowledge_base",
      "status": "green",
      "vector_size": 384,
      "distance_metric": "cosine",
      "points_count": 15420,
      "indexed_vectors": 15420,
      "segments_count": 3,
      "disk_usage_bytes": 245760000,
      "disk_usage_mb": 234.5,
      "ram_usage_bytes": 52428800,
      "ram_usage_mb": 50.0,
      "created_at": "2025-06-01T10:00:00Z",
      "updated_at": "2025-06-27T10:30:00Z"
    }
  ],
  "total_collections": 3,
  "total_vectors": 45670,
  "timestamp": "2025-06-27T10:30:00Z"
}
```

### POST /vector/collections

Create a new vector collection.

**Authentication:** Requires `write` scope

**Request:**

```json
{
  "name": "new_collection",
  "vector_size": 384,
  "distance": "cosine",
  "hnsw_config": {
    "m": 16,
    "ef_construct": 100
  },
  "optimizers_config": {
    "memmap_threshold": 20000
  }
}
```

### DELETE /vector/collections/{collection_name}

Delete a vector collection.

**Authentication:** Requires `admin` scope

### GET /vector/health

Get vector service health status.

**Authentication:** Requires `read` scope

**Response:**

```json
{
  "status": "healthy",
  "service": "vector",
  "response_time_ms": 5.2,
  "details": {
    "qdrant_version": "1.7.4",
    "collections_count": 3,
    "total_points": 45670,
    "memory_usage_mb": 512.3,
    "disk_usage_gb": 2.1
  },
  "timestamp": "2025-06-27T10:30:00Z"
}
```

---

## Graph Intelligence API

### POST /graph/query

Execute Cypher query against Neo4j knowledge graph.

**Authentication:** Requires `read` scope

**Request:**

```json
{
  "cypher": "MATCH (n:Person)-[r:WORKED_ON]->(p:Project {domain: 'AI'}) RETURN n.name, p.title, r.role LIMIT 10",
  "parameters": {
    "domain": "AI"
  },
  "include_stats": true
}
```

**Response:**

```json
{
  "query": "MATCH (n:Person)-[r:WORKED_ON]...",
  "results": [
    {
      "n.name": "Geoffrey Hinton",
      "p.title": "Deep Learning Research",
      "r.role": "Principal Investigator"
    }
  ],
  "columns": ["n.name", "p.title", "r.role"],
  "stats": {
    "nodes_created": 0,
    "nodes_deleted": 0,
    "relationships_created": 0,
    "relationships_deleted": 0,
    "properties_set": 0,
    "execution_time_ms": 23.4
  },
  "timestamp": "2025-06-27T10:30:00Z"
}
```

### POST /graph/memory

Store contextual memory in the knowledge graph.

**Authentication:** Requires `write` scope

**Request:**

```json
{
  "entity": "OpenAI",
  "entity_type": "Organization",
  "relationship": "DEVELOPED",
  "target": "GPT-4",
  "target_type": "Model",
  "context": "Large language model development project",
  "metadata": {
    "year": 2023,
    "significance": "high",
    "impact": "revolutionary"
  },
  "confidence": 0.95
}
```

**Response:**

```json
{
  "entity_id": "node_123",
  "target_id": "node_456", 
  "relationship_id": "rel_789",
  "nodes_created": 2,
  "relationships_created": 1,
  "properties_set": 8,
  "storage_time_ms": 45.6,
  "timestamp": "2025-06-27T10:30:00Z"
}
```

### POST /graph/relationships

Analyze relationships between entities.

**Authentication:** Requires `read` scope

**Request:**

```json
{
  "entities": ["OpenAI", "GPT-4", "Transformer"],
  "relationship_types": ["DEVELOPED", "USES", "BASED_ON"],
  "max_depth": 3,
  "include_properties": true
}
```

**Response:**

```json
{
  "entities": ["OpenAI", "GPT-4", "Transformer"],
  "relationships": [
    {
      "source": "OpenAI",
      "target": "GPT-4",
      "relationship": "DEVELOPED",
      "properties": {
        "year": 2023,
        "team_size": 100
      },
      "confidence": 0.98
    }
  ],
  "paths": [
    {
      "path": ["OpenAI", "DEVELOPED", "GPT-4", "USES", "Transformer"],
      "length": 2,
      "confidence": 0.92
    }
  ],
  "analysis_time_ms": 234.5,
  "timestamp": "2025-06-27T10:30:00Z"
}
```

### GET /graph/schema

Get graph schema information.

**Authentication:** Requires `read` scope

**Response:**

```json
{
  "node_labels": [
    {
      "label": "Person",
      "count": 1250,
      "properties": ["name", "email", "expertise"]
    },
    {
      "label": "Organization",
      "count": 340,
      "properties": ["name", "founded", "domain"]
    }
  ],
  "relationship_types": [
    {
      "type": "WORKED_ON",
      "count": 2450,
      "properties": ["role", "duration", "contribution"]
    }
  ],
  "constraints": [
    {
      "label": "Person",
      "property": "email",
      "type": "UNIQUE"
    }
  ],
  "indexes": [
    {
      "label": "Person",
      "property": "name",
      "type": "BTREE"
    }
  ],
  "timestamp": "2025-06-27T10:30:00Z"
}
```

### GET /graph/health

Get graph service health status.

**Authentication:** Requires `read` scope

**Response:**

```json
{
  "status": "healthy",
  "service": "graph",
  "response_time_ms": 8.3,
  "details": {
    "neo4j_version": "5.15.0",
    "database": "neo4j",
    "nodes_count": 15420,
    "relationships_count": 23450,
    "memory_usage_mb": 1024.7,
    "disk_usage_gb": 5.2
  },
  "timestamp": "2025-06-27T10:30:00Z"
}
```

---

## Web Intelligence API

### POST /web/crawl

Extract content from web sources using Crawl4AI.

**Authentication:** Requires `write` scope

**Request:**

```json
{
  "url": "https://example.com/research-paper",
  "extraction_mode": "intelligent",
  "output_formats": ["markdown", "text"],
  "include_links": true,
  "include_images": false,
  "respect_robots": true,
  "timeout": 30,
  "user_agent": "Agentic-RAG-MCP-Server/1.0",
  "extraction_strategy": {
    "type": "llm",
    "model": "gpt-3.5-turbo",
    "schema": {
      "title": "string",
      "authors": "array",
      "abstract": "string",
      "main_content": "string"
    }
  }
}
```

**Response:**

```json
{
  "url": "https://example.com/research-paper",
  "content": {
    "title": "Advanced RAG Architectures",
    "authors": ["Dr. Jane Smith", "Prof. John Doe"],
    "abstract": "This paper presents...",
    "main_content": "## Introduction\n\nRetrieval-Augmented Generation..."
  },
  "raw_content": "<!DOCTYPE html>...",
  "links": [
    {
      "url": "https://example.com/references",
      "text": "References",
      "type": "internal"
    }
  ],
  "metadata": {
    "status_code": 200,
    "content_type": "text/html",
    "content_length": 45600,
    "last_modified": "2025-06-26T15:30:00Z",
    "language": "en"
  },
  "extraction_time_ms": 2340.5,
  "timestamp": "2025-06-27T10:30:00Z"
}
```

### POST /web/search

Search and analyze web content.

**Authentication:** Requires `read` scope

**Request:**

```json
{
  "query": "latest RAG architecture research 2025",
  "search_engine": "auto",
  "max_results": 10,
  "date_range": "1_month",
  "content_types": ["research_paper", "blog_post", "news"],
  "extract_content": true,
  "summarize": true
}
```

**Response:**

```json
{
  "query": "latest RAG architecture research 2025",
  "results": [
    {
      "url": "https://arxiv.org/abs/2025.12345",
      "title": "Advanced RAG with Multi-Modal Fusion",
      "snippet": "We present a novel approach...",
      "content": "# Advanced RAG with Multi-Modal Fusion\n\n## Abstract...",
      "summary": "This paper introduces a multi-modal RAG system...",
      "score": 0.95,
      "published_date": "2025-06-20T00:00:00Z",
      "content_type": "research_paper"
    }
  ],
  "total_results": 47,
  "search_time_ms": 1250.3,
  "timestamp": "2025-06-27T10:30:00Z"
}
```

### POST /web/monitor

Monitor web sources for changes.

**Authentication:** Requires `write` scope

**Request:**

```json
{
  "urls": [
    "https://arxiv.org/list/cs.AI/recent",
    "https://openai.com/blog"
  ],
  "check_interval": "1h",
  "change_threshold": 0.1,
  "notification_webhook": "https://your-app.com/webhook",
  "monitor_elements": ["title", "content", "links"],
  "store_changes": true
}
```

**Response:**

```json
{
  "monitor_id": "monitor_789",
  "urls_count": 2,
  "check_interval": "1h",
  "next_check": "2025-06-27T11:30:00Z",
  "status": "active",
  "timestamp": "2025-06-27T10:30:00Z"
}
```

### GET /web/monitor/{monitor_id}

Get monitoring status and detected changes.

**Authentication:** Requires `read` scope

**Response:**

```json
{
  "monitor_id": "monitor_789",
  "status": "active",
  "urls": [
    {
      "url": "https://arxiv.org/list/cs.AI/recent",
      "last_check": "2025-06-27T10:00:00Z",
      "last_change": "2025-06-27T09:45:00Z",
      "change_score": 0.15,
      "changes_detected": 3
    }
  ],
  "recent_changes": [
    {
      "url": "https://arxiv.org/list/cs.AI/recent",
      "detected_at": "2025-06-27T09:45:00Z",
      "change_type": "new_content",
      "description": "New paper added: 'Novel RAG Architecture'"
    }
  ],
  "total_changes": 12,
  "timestamp": "2025-06-27T10:30:00Z"
}
```

### GET /web/health

Get web service health status.

**Authentication:** Requires `read` scope

**Response:**

```json
{
  "status": "healthy",
  "service": "web",
  "response_time_ms": 12.7,
  "details": {
    "crawl4ai_version": "0.6.0",
    "active_sessions": 3,
    "queued_requests": 0,
    "successful_crawls_24h": 1250,
    "failed_crawls_24h": 23,
    "success_rate": 0.98
  },
  "timestamp": "2025-06-27T10:30:00Z"
}
```

---

## Administrative API

### GET /admin/stats

Get comprehensive system statistics.

**Authentication:** Requires `admin` scope

**Response:**

```json
{
  "uptime_seconds": 86400,
  "startup_time": "2025-06-26T10:30:00Z",
  "version": "1.0.0",
  "environment": "production",
  "services": {
    "vector": {
      "status": "healthy",
      "collections": 3,
      "total_vectors": 45670,
      "memory_usage_mb": 512.3
    },
    "graph": {
      "status": "healthy",
      "nodes": 15420,
      "relationships": 23450,
      "memory_usage_mb": 1024.7
    },
    "web": {
      "status": "healthy",
      "active_sessions": 3,
      "success_rate": 0.98
    }
  },
  "request_stats": {
    "total_requests_24h": 12450,
    "successful_requests": 12234,
    "failed_requests": 216,
    "avg_response_time_ms": 234.5
  },
  "resource_usage": {
    "cpu_usage_percent": 45.2,
    "memory_usage_mb": 2048.0,
    "disk_usage_gb": 12.5
  },
  "timestamp": "2025-06-27T10:30:00Z"
}
```

### POST /admin/maintenance

Trigger maintenance operations.

**Authentication:** Requires `admin` scope

**Request:**

```json
{
  "operation": "optimize_indexes",
  "services": ["vector", "graph"],
  "force": false,
  "notify": true
}
```

**Response:**

```json
{
  "operation_id": "maint_456",
  "operation": "optimize_indexes",
  "status": "started",
  "estimated_duration_minutes": 15,
  "affected_services": ["vector", "graph"],
  "timestamp": "2025-06-27T10:30:00Z"
}
```

### GET /admin/logs

Get application logs with filtering.

**Authentication:** Requires `admin` scope

**Query Parameters:**

- `level`: Log level (DEBUG, INFO, WARNING, ERROR)
- `service`: Service name filter
- `start_time`: Start time (ISO 8601)
- `end_time`: End time (ISO 8601)
- `limit`: Maximum log entries (default: 100)

**Response:**

```json
{
  "logs": [
    {
      "timestamp": "2025-06-27T10:30:00Z",
      "level": "INFO",
      "service": "vector",
      "message": "Vector search completed",
      "metadata": {
        "query": "machine learning",
        "results_count": 5,
        "search_time_ms": 45.2
      }
    }
  ],
  "total_logs": 500,
  "filtered_logs": 150,
  "timestamp": "2025-06-27T10:30:00Z"
}
```

---

## Error Handling

### Standard Error Response

```json
{
  "error": {
    "code": "VALIDATION_ERROR",
    "message": "Request validation failed",
    "details": {
      "field": "query",
      "issue": "Query length must be between 1 and 2000 characters"
    },
    "request_id": "req_789"
  },
  "timestamp": "2025-06-27T10:30:00Z"
}
```

### HTTP Status Codes

| Code | Description | Common Scenarios |
|------|-------------|------------------|
| 200 | OK | Successful request |
| 201 | Created | Resource created successfully |
| 400 | Bad Request | Invalid request format or parameters |
| 401 | Unauthorized | Missing or invalid authentication |
| 403 | Forbidden | Insufficient permissions for operation |
| 404 | Not Found | Resource not found |
| 409 | Conflict | Resource already exists |
| 422 | Unprocessable Entity | Request validation failed |
| 429 | Too Many Requests | Rate limit exceeded |
| 500 | Internal Server Error | Server-side error |
| 503 | Service Unavailable | Service temporarily unavailable |

### Error Codes

| Code | Description |
|------|-------------|
| `AUTHENTICATION_FAILED` | Invalid or expired token |
| `AUTHORIZATION_FAILED` | Insufficient permissions |
| `VALIDATION_ERROR` | Request validation failed |
| `RESOURCE_NOT_FOUND` | Requested resource not found |
| `RESOURCE_CONFLICT` | Resource already exists |
| `RATE_LIMIT_EXCEEDED` | Too many requests |
| `SERVICE_UNAVAILABLE` | External service unavailable |
| `PROCESSING_ERROR` | Error during request processing |
| `TIMEOUT_ERROR` | Request timeout |

---

## Rate Limiting

### Rate Limit Headers

```http
X-RateLimit-Limit: 100
X-RateLimit-Remaining: 87
X-RateLimit-Reset: 1640995200
X-RateLimit-Window: 60
```

### Default Limits

| Scope | Requests per Minute | Burst Limit |
|-------|-------------------|-------------|
| `read` | 100 | 120 |
| `write` | 50 | 60 |
| `admin` | 30 | 40 |

### Rate Limit Exceeded Response

```json
{
  "error": {
    "code": "RATE_LIMIT_EXCEEDED",
    "message": "Rate limit exceeded",
    "details": {
      "limit": 100,
      "window_seconds": 60,
      "retry_after_seconds": 30
    }
  },
  "timestamp": "2025-06-27T10:30:00Z"
}
```

---

## SDK Examples

### Python SDK Example

```python
import asyncio
import httpx
from typing import Dict, Any, List

class AgenticRAGClient:
    def __init__(self, base_url: str, token: str):
        self.base_url = base_url
        self.headers = {"Authorization": f"Bearer {token}"}
    
    async def intelligence_query(
        self, 
        query: str, 
        mode: str = "auto",
        limit: int = 10
    ) -> Dict[str, Any]:
        """Perform agentic intelligence query."""
        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{self.base_url}/intelligence/query",
                json={
                    "query": query,
                    "mode": mode,
                    "limit": limit
                },
                headers=self.headers
            )
            response.raise_for_status()
            return response.json()
    
    async def vector_search(
        self, 
        query: str, 
        collection_name: str = "knowledge_base"
    ) -> Dict[str, Any]:
        """Perform vector search."""
        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{self.base_url}/vector/search",
                json={
                    "query": query,
                    "collection_name": collection_name
                },
                headers=self.headers
            )
            response.raise_for_status()
            return response.json()
    
    async def store_document(
        self, 
        content: str, 
        metadata: Dict[str, Any] = None
    ) -> Dict[str, Any]:
        """Store document with embedding."""
        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{self.base_url}/vector/store",
                json={
                    "content": content,
                    "metadata": metadata or {}
                },
                headers=self.headers
            )
            response.raise_for_status()
            return response.json()

# Usage
async def main():
    client = AgenticRAGClient(
        base_url="https://api.example.com/api/v1",
        token="your-jwt-token"
    )
    
    # Agentic intelligence query
    result = await client.intelligence_query(
        "What are the latest developments in RAG architecture?"
    )
    print(f"Response: {result['content']}")
    print(f"Confidence: {result['confidence']}")
    
    # Vector search
    search_result = await client.vector_search(
        "transformer attention mechanisms"
    )
    print(f"Found {len(search_result['results'])} results")
    
    # Store document
    store_result = await client.store_document(
        content="The transformer architecture uses attention mechanisms...",
        metadata={"topic": "deep_learning", "year": 2025}
    )
    print(f"Stored with ID: {store_result['id']}")

if __name__ == "__main__":
    asyncio.run(main())
```

### JavaScript SDK Example

```javascript
class AgenticRAGClient {
    constructor(baseUrl, token) {
        this.baseUrl = baseUrl;
        this.headers = {
            'Authorization': `Bearer ${token}`,
            'Content-Type': 'application/json'
        };
    }
    
    async intelligenceQuery(query, options = {}) {
        const response = await fetch(`${this.baseUrl}/intelligence/query`, {
            method: 'POST',
            headers: this.headers,
            body: JSON.stringify({
                query,
                mode: options.mode || 'auto',
                limit: options.limit || 10,
                filters: options.filters || {}
            })
        });
        
        if (!response.ok) {
            throw new Error(`API error: ${response.status}`);
        }
        
        return response.json();
    }
    
    async vectorSearch(query, collectionName = 'knowledge_base') {
        const response = await fetch(`${this.baseUrl}/vector/search`, {
            method: 'POST',
            headers: this.headers,
            body: JSON.stringify({
                query,
                collection_name: collectionName
            })
        });
        
        if (!response.ok) {
            throw new Error(`API error: ${response.status}`);
        }
        
        return response.json();
    }
    
    async webCrawl(url, options = {}) {
        const response = await fetch(`${this.baseUrl}/web/crawl`, {
            method: 'POST',
            headers: this.headers,
            body: JSON.stringify({
                url,
                extraction_mode: options.extractionMode || 'intelligent',
                include_links: options.includeLinks || true,
                timeout: options.timeout || 30
            })
        });
        
        if (!response.ok) {
            throw new Error(`API error: ${response.status}`);
        }
        
        return response.json();
    }
}

// Usage
const client = new AgenticRAGClient(
    'https://api.example.com/api/v1',
    'your-jwt-token'
);

// Agentic query
client.intelligenceQuery('Explain quantum computing basics')
    .then(result => {
        console.log('Response:', result.content);
        console.log('Confidence:', result.confidence);
    })
    .catch(error => console.error('Error:', error));
```

### cURL Examples

#### Get Authentication Token

```bash
curl -X POST "https://api.example.com/auth/token" \
  -H "Content-Type: application/json" \
  -d '{
    "username": "your_username",
    "scopes": ["read", "write"]
  }'
```

#### Agentic Intelligence Query

```bash
curl -X POST "https://api.example.com/api/v1/intelligence/query" \
  -H "Authorization: Bearer your-jwt-token" \
  -H "Content-Type: application/json" \
  -d '{
    "query": "What are the latest developments in RAG architecture?",
    "mode": "hybrid",
    "limit": 5
  }'
```

#### Vector Search

```bash
curl -X POST "https://api.example.com/api/v1/vector/search" \
  -H "Authorization: Bearer your-jwt-token" \
  -H "Content-Type: application/json" \
  -d '{
    "query": "machine learning transformers",
    "collection_name": "knowledge_base",
    "limit": 10,
    "score_threshold": 0.7
  }'
```

#### Store Document

```bash
curl -X POST "https://api.example.com/api/v1/vector/store" \
  -H "Authorization: Bearer your-jwt-token" \
  -H "Content-Type: application/json" \
  -d '{
    "content": "The transformer architecture uses attention mechanisms...",
    "metadata": {
      "title": "Understanding Transformers",
      "author": "Jane Doe",
      "year": 2025
    },
    "tags": ["AI", "NLP", "transformers"]
  }'
```

This comprehensive API reference provides detailed documentation for all endpoints, authentication methods, request/response formats, error handling, and SDK examples for the Agentic RAG MCP Server.
