"""
Neo4j graph database tools for FastMCP integration.

Provides MCP tools for knowledge graph operations, memory management,
and GraphRAG integration for the Unified MCP Intelligence Server.
"""

from datetime import datetime
from typing import Any

from fastmcp import FastMCP
import structlog

from qdrant_neo4j_crawl4ai_mcp.models.graph_models import (
    CypherQuery,
    GraphAnalysisRequest,
    GraphNode,
    GraphRelationship,
    GraphSearchRequest,
    KnowledgeExtractionRequest,
    NodeType,
    RelationshipType,
)
from qdrant_neo4j_crawl4ai_mcp.services.graph_service import GraphService

logger = structlog.get_logger(__name__)


def register_graph_tools(mcp: FastMCP, graph_service: GraphService) -> None:
    """
    Register Neo4j graph tools with FastMCP application.

    Args:
        mcp: FastMCP application instance
        graph_service: Graph service instance
    """

    @mcp.tool()
    async def create_graph_node(
        name: str,
        node_type: str,
        description: str | None = None,
        properties: dict[str, Any] | None = None,
        tags: list[str] | None = None,
        emotional_valence: float | None = None,
        abstraction_level: int | None = None,
        confidence_score: float = 0.5,
        source: str | None = None,
    ) -> dict[str, Any]:
        """
        Create a new node in the knowledge graph.

        Args:
            name: Node name or title
            node_type: Type of node (Entity, Concept, Person, etc.)
            description: Optional node description
            properties: Additional node properties
            tags: Classification tags
            emotional_valence: Emotional sentiment (-1 to 1)
            abstraction_level: Abstraction level (1-10)
            confidence_score: Confidence in node data (0-1)
            source: Data source or origin

        Returns:
            Created node information
        """
        try:
            node = GraphNode(
                name=name,
                node_type=NodeType(node_type),
                description=description,
                properties=properties or {},
                tags=tags or [],
                emotional_valence=emotional_valence,
                abstraction_level=abstraction_level,
                confidence_score=confidence_score,
                source=source,
            )

            result = await graph_service.create_node(node)

            logger.info(
                "Graph node created", node_id=result.id, node_type=node_type, name=name
            )

            return {
                "success": True,
                "node_id": result.id,
                "name": result.name,
                "node_type": result.node_type.value,
                "created_at": result.created_at.isoformat(),
            }

        except Exception as e:
            logger.exception("Failed to create graph node", error=str(e))
            return {"success": False, "error": str(e), "error_type": type(e).__name__}

    @mcp.tool()
    async def create_graph_relationship(
        source_id: str,
        target_id: str,
        relationship_type: str,
        properties: dict[str, Any] | None = None,
        weight: float = 1.0,
        confidence: float = 0.5,
        evidence: list[str] | None = None,
    ) -> dict[str, Any]:
        """
        Create a relationship between two nodes in the knowledge graph.

        Args:
            source_id: Source node ID
            target_id: Target node ID
            relationship_type: Type of relationship
            properties: Relationship properties
            weight: Relationship strength/weight (0-1)
            confidence: Confidence in relationship (0-1)
            evidence: Evidence supporting relationship

        Returns:
            Created relationship information
        """
        try:
            relationship = GraphRelationship(
                source_id=source_id,
                target_id=target_id,
                relationship_type=RelationshipType(relationship_type),
                properties=properties or {},
                weight=weight,
                confidence=confidence,
                evidence=evidence or [],
            )

            result = await graph_service.create_relationship(relationship)

            logger.info(
                "Graph relationship created",
                relationship_id=result.id,
                relationship_type=relationship_type,
                source_id=source_id,
                target_id=target_id,
            )

            return {
                "success": True,
                "relationship_id": result.id,
                "relationship_type": result.relationship_type.value,
                "source_id": result.source_id,
                "target_id": result.target_id,
                "weight": result.weight,
                "confidence": result.confidence,
                "created_at": result.created_at.isoformat(),
            }

        except Exception as e:
            logger.exception("Failed to create graph relationship", error=str(e))
            return {"success": False, "error": str(e), "error_type": type(e).__name__}

    @mcp.tool()
    async def search_graph(
        query: str,
        node_types: list[str] | None = None,
        relationship_types: list[str] | None = None,
        max_depth: int = 2,
        limit: int = 10,
        confidence_threshold: float = 0.0,
        use_embeddings: bool = False,
        embedding_similarity_threshold: float = 0.7,
    ) -> dict[str, Any]:
        """
        Search the knowledge graph for nodes and relationships.

        Args:
            query: Search query
            node_types: Node types to search
            relationship_types: Relationship types to include
            max_depth: Maximum traversal depth
            limit: Maximum results
            confidence_threshold: Minimum confidence threshold
            use_embeddings: Use vector embeddings for search
            embedding_similarity_threshold: Embedding similarity threshold

        Returns:
            Search results with nodes, relationships, and paths
        """
        try:
            search_request = GraphSearchRequest(
                query=query,
                node_types=[NodeType(nt) for nt in (node_types or [])],
                relationship_types=[
                    RelationshipType(rt) for rt in (relationship_types or [])
                ],
                max_depth=max_depth,
                limit=limit,
                confidence_threshold=confidence_threshold,
                use_embeddings=use_embeddings,
                embedding_similarity_threshold=embedding_similarity_threshold,
            )

            result = await graph_service.search_graph(search_request)

            logger.info(
                "Graph search completed",
                query=query,
                results_count=result.total_results,
                search_time_ms=result.search_time_ms,
            )

            return {
                "success": True,
                "total_results": result.total_results,
                "search_time_ms": result.search_time_ms,
                "query_type": result.query_type,
                "nodes": [
                    {
                        "id": node.id,
                        "name": node.name,
                        "node_type": node.node_type.value,
                        "description": node.description,
                        "confidence_score": node.confidence_score,
                        "tags": node.tags,
                    }
                    for node in result.nodes
                ],
                "relationships": [
                    {
                        "id": rel.id,
                        "source_id": rel.source_id,
                        "target_id": rel.target_id,
                        "relationship_type": rel.relationship_type.value,
                        "weight": rel.weight,
                        "confidence": rel.confidence,
                    }
                    for rel in result.relationships
                ],
                "paths": result.paths,
                "confidence_scores": result.confidence_scores,
                "filters_applied": result.filters_applied,
            }

        except Exception as e:
            logger.exception("Graph search failed", error=str(e))
            return {"success": False, "error": str(e), "error_type": type(e).__name__}

    @mcp.tool()
    async def extract_knowledge_from_text(
        text: str,
        extract_entities: bool = True,
        extract_relationships: bool = True,
        extract_concepts: bool = True,
        merge_similar_entities: bool = True,
        confidence_threshold: float = 0.5,
        max_entities: int = 50,
        source_url: str | None = None,
        source_type: str | None = None,
        document_id: str | None = None,
    ) -> dict[str, Any]:
        """
        Extract knowledge from text using AI-powered analysis.

        Args:
            text: Text to extract knowledge from
            extract_entities: Extract entities
            extract_relationships: Extract relationships
            extract_concepts: Extract concepts
            merge_similar_entities: Merge similar entities
            confidence_threshold: Extraction confidence threshold
            max_entities: Maximum entities to extract
            source_url: Source URL
            source_type: Source type
            document_id: Document identifier

        Returns:
            Extracted knowledge with nodes and relationships
        """
        try:
            extraction_request = KnowledgeExtractionRequest(
                text=text,
                extract_entities=extract_entities,
                extract_relationships=extract_relationships,
                extract_concepts=extract_concepts,
                merge_similar_entities=merge_similar_entities,
                confidence_threshold=confidence_threshold,
                max_entities=max_entities,
                source_url=source_url,
                source_type=source_type,
                document_id=document_id,
            )

            result = await graph_service.extract_knowledge_from_text(extraction_request)

            logger.info(
                "Knowledge extraction completed",
                total_entities=result.total_entities,
                total_relationships=result.total_relationships,
                processing_time_ms=result.processing_time_ms,
                average_confidence=result.average_confidence,
            )

            return {
                "success": True,
                "total_entities": result.total_entities,
                "total_relationships": result.total_relationships,
                "processing_time_ms": result.processing_time_ms,
                "average_confidence": result.average_confidence,
                "low_confidence_items": result.low_confidence_items,
                "extracted_nodes": [
                    {
                        "id": node.id,
                        "name": node.name,
                        "node_type": node.node_type.value,
                        "description": node.description,
                        "confidence_score": node.confidence_score,
                        "emotional_valence": node.emotional_valence,
                        "abstraction_level": node.abstraction_level,
                        "tags": node.tags,
                        "source": node.source,
                    }
                    for node in result.extracted_nodes
                ],
                "extracted_relationships": [
                    {
                        "id": rel.id,
                        "source_id": rel.source_id,
                        "target_id": rel.target_id,
                        "relationship_type": rel.relationship_type.value,
                        "weight": rel.weight,
                        "confidence": rel.confidence,
                        "evidence": rel.evidence,
                    }
                    for rel in result.extracted_relationships
                ],
                "source_metadata": result.source_metadata,
            }

        except Exception as e:
            logger.exception("Knowledge extraction failed", error=str(e))
            return {"success": False, "error": str(e), "error_type": type(e).__name__}

    @mcp.tool()
    async def create_memory_node(
        name: str,
        memory_type: str = "general",
        observations: list[str] | None = None,
        context: str | None = None,
        psychological_profile: str | None = None,
        values: list[str] | None = None,
    ) -> dict[str, Any]:
        """
        Create a memory node for AI assistant memory systems.

        Args:
            name: Memory subject name
            memory_type: Type of memory (general, person, concept, etc.)
            observations: Observed attributes
            context: Memory context
            psychological_profile: Psychological characteristics
            values: Core values

        Returns:
            Created memory node information
        """
        try:
            result = await graph_service.create_memory_node(
                name=name,
                memory_type=memory_type,
                observations=observations or [],
                context=context,
            )

            # Update additional memory attributes if provided
            if psychological_profile or values:
                result.psychological_profile = psychological_profile
                result.values = values or []
                # Update in database would happen here

            logger.info(
                "Memory node created",
                memory_id=result.id,
                name=name,
                memory_type=memory_type,
            )

            return {
                "success": True,
                "memory_id": result.id,
                "name": result.name,
                "memory_type": result.memory_type,
                "observations": result.observations,
                "insights": result.insights,
                "context": result.context,
                "psychological_profile": result.psychological_profile,
                "values": result.values,
                "created_at": result.created_at.isoformat(),
                "access_count": result.access_count,
            }

        except Exception as e:
            logger.exception("Failed to create memory node", error=str(e))
            return {"success": False, "error": str(e), "error_type": type(e).__name__}

    @mcp.tool()
    async def execute_cypher_query(
        query: str,
        parameters: dict[str, Any] | None = None,
        read_only: bool = True,
        timeout: int | None = None,
        limit: int | None = None,
        include_stats: bool = False,
    ) -> dict[str, Any]:
        """
        Execute a raw Cypher query against the Neo4j database.

        Args:
            query: Cypher query string
            parameters: Query parameters
            read_only: Read-only query flag
            timeout: Query timeout in seconds
            limit: Result limit
            include_stats: Include execution statistics

        Returns:
            Query execution results
        """
        try:
            cypher_query = CypherQuery(
                query=query,
                parameters=parameters or {},
                read_only=read_only,
                timeout=timeout,
                limit=limit,
                include_stats=include_stats,
            )

            result = await graph_service.execute_cypher_query(cypher_query)

            logger.info(
                "Cypher query executed",
                success=result.success,
                execution_time_ms=result.execution_time_ms,
                records_count=result.records_available,
                read_only=read_only,
            )

            return {
                "success": result.success,
                "records": result.records,
                "execution_time_ms": result.execution_time_ms,
                "records_available": result.records_available,
                "stats": result.stats,
                "error": result.error,
                "error_code": result.error_code,
            }

        except Exception as e:
            logger.exception("Cypher query execution failed", error=str(e))
            return {
                "success": False,
                "error": str(e),
                "error_type": type(e).__name__,
                "records": [],
                "execution_time_ms": 0,
                "records_available": 0,
            }

    @mcp.tool()
    async def analyze_graph_structure(
        focus_node_id: str | None = None,
        analysis_type: str = "centrality",
        depth: int = 3,
        include_metrics: bool = True,
        include_communities: bool = False,
        include_paths: bool = False,
        node_types: list[str] | None = None,
        relationship_types: list[str] | None = None,
    ) -> dict[str, Any]:
        """
        Analyze graph structure and compute network metrics.

        Args:
            focus_node_id: Node to focus analysis on
            analysis_type: Type of analysis (centrality, community, paths)
            depth: Analysis depth
            include_metrics: Include graph metrics
            include_communities: Include community detection
            include_paths: Include shortest paths
            node_types: Node types to include
            relationship_types: Relationship types to include

        Returns:
            Graph analysis results with metrics and insights
        """
        try:
            analysis_request = GraphAnalysisRequest(
                focus_node_id=focus_node_id,
                analysis_type=analysis_type,
                depth=depth,
                include_metrics=include_metrics,
                include_communities=include_communities,
                include_paths=include_paths,
                node_types=[NodeType(nt) for nt in (node_types or [])],
                relationship_types=[
                    RelationshipType(rt) for rt in (relationship_types or [])
                ],
            )

            result = await graph_service.analyze_graph_structure(analysis_request)

            logger.info(
                "Graph analysis completed",
                analysis_type=result.analysis_type,
                node_count=result.node_count,
                relationship_count=result.relationship_count,
                analysis_time_ms=result.analysis_time_ms,
            )

            return {
                "success": True,
                "analysis_type": result.analysis_type,
                "focus_node": {
                    "id": result.focus_node.id,
                    "name": result.focus_node.name,
                    "node_type": result.focus_node.node_type.value,
                }
                if result.focus_node
                else None,
                "node_count": result.node_count,
                "relationship_count": result.relationship_count,
                "density": result.density,
                "average_clustering": result.average_clustering,
                "centrality_measures": result.centrality_measures,
                "influential_nodes": result.influential_nodes,
                "communities": result.communities,
                "modularity": result.modularity,
                "shortest_paths": result.shortest_paths,
                "temporal_patterns": result.temporal_patterns,
                "analysis_time_ms": result.analysis_time_ms,
                "confidence": result.confidence,
            }

        except Exception as e:
            logger.exception("Graph analysis failed", error=str(e))
            return {"success": False, "error": str(e), "error_type": type(e).__name__}

    @mcp.tool()
    async def get_graph_health() -> dict[str, Any]:
        """
        Get Neo4j graph service health status and statistics.

        Returns:
            Health check results with database statistics
        """
        try:
            result = await graph_service.health_check()

            logger.info(
                "Graph health check completed",
                status=result.status,
                response_time_ms=result.response_time_ms,
                total_nodes=result.total_nodes,
                total_relationships=result.total_relationships,
            )

            return {
                "success": True,
                "status": result.status,
                "database_connected": result.database_connected,
                "response_time_ms": result.response_time_ms,
                "total_nodes": result.total_nodes,
                "total_relationships": result.total_relationships,
                "node_types_count": result.node_types_count,
                "relationship_types_count": result.relationship_types_count,
                "memory_usage_mb": result.memory_usage_mb,
                "disk_usage_mb": result.disk_usage_mb,
                "average_query_time_ms": result.average_query_time_ms,
                "neo4j_version": result.neo4j_version,
                "driver_version": result.driver_version,
                "errors": result.errors,
                "warnings": result.warnings,
                "timestamp": result.timestamp.isoformat(),
            }

        except Exception as e:
            logger.exception("Graph health check failed", error=str(e))
            return {
                "success": False,
                "status": "error",
                "error": str(e),
                "error_type": type(e).__name__,
                "timestamp": datetime.utcnow().isoformat(),
            }

    @mcp.tool()
    async def get_node_by_id(node_id: str) -> dict[str, Any]:
        """
        Retrieve a specific node by its ID.

        Args:
            node_id: Node identifier

        Returns:
            Node information or error
        """
        try:
            result = await graph_service.get_node_by_id(node_id)

            if result:
                logger.info(
                    "Node retrieved", node_id=node_id, node_type=result.node_type.value
                )
                return {
                    "success": True,
                    "node": {
                        "id": result.id,
                        "name": result.name,
                        "node_type": result.node_type.value,
                        "description": result.description,
                        "properties": result.properties,
                        "tags": result.tags,
                        "emotional_valence": result.emotional_valence,
                        "abstraction_level": result.abstraction_level,
                        "confidence_score": result.confidence_score,
                        "created_at": result.created_at.isoformat(),
                        "updated_at": result.updated_at.isoformat(),
                        "source": result.source,
                        "sources": result.sources,
                    },
                }
            return {"success": False, "error": f"Node with ID {node_id} not found"}

        except Exception as e:
            logger.exception("Failed to retrieve node", node_id=node_id, error=str(e))
            return {"success": False, "error": str(e), "error_type": type(e).__name__}

    @mcp.tool()
    async def update_node_properties(
        node_id: str, properties: dict[str, Any], merge_mode: bool = True
    ) -> dict[str, Any]:
        """
        Update properties of an existing node.

        Args:
            node_id: Node identifier
            properties: Properties to update
            merge_mode: If True, merge with existing properties; if False, replace

        Returns:
            Update result
        """
        try:
            await graph_service.update_node_properties(
                node_id=node_id, properties=properties, merge_mode=merge_mode
            )

            logger.info(
                "Node properties updated",
                node_id=node_id,
                properties_count=len(properties),
                merge_mode=merge_mode,
            )

            return {
                "success": True,
                "node_id": node_id,
                "updated_properties": list(properties.keys()),
                "merge_mode": merge_mode,
                "timestamp": datetime.utcnow().isoformat(),
            }

        except Exception as e:
            logger.exception(
                "Failed to update node properties", node_id=node_id, error=str(e)
            )
            return {"success": False, "error": str(e), "error_type": type(e).__name__}

    @mcp.tool()
    async def delete_node(
        node_id: str, delete_relationships: bool = True
    ) -> dict[str, Any]:
        """
        Delete a node from the graph.

        Args:
            node_id: Node identifier
            delete_relationships: Whether to delete connected relationships

        Returns:
            Deletion result
        """
        try:
            await graph_service.delete_node(
                node_id=node_id, delete_relationships=delete_relationships
            )

            logger.info(
                "Node deleted",
                node_id=node_id,
                delete_relationships=delete_relationships,
            )

            return {
                "success": True,
                "node_id": node_id,
                "deleted_relationships": delete_relationships,
                "timestamp": datetime.utcnow().isoformat(),
            }

        except Exception as e:
            logger.exception("Failed to delete node", node_id=node_id, error=str(e))
            return {"success": False, "error": str(e), "error_type": type(e).__name__}

    logger.info("Neo4j graph tools registered with FastMCP")
