"""
Neo4j graph service for knowledge graphs and memory systems.

Provides comprehensive graph operations, memory management, GraphRAG integration,
and hybrid reasoning capabilities for the Unified MCP Intelligence Server.
"""

from datetime import datetime
import json
import re
import time
from typing import Any
from uuid import uuid4

from openai import AsyncOpenAI
import structlog

from qdrant_neo4j_crawl4ai_mcp.models.graph_models import (
    CypherQuery,
    CypherResult,
    GraphAnalysisRequest,
    GraphAnalysisResult,
    GraphHealthCheck,
    GraphNode,
    GraphRelationship,
    GraphSearchRequest,
    GraphSearchResult,
    KnowledgeExtractionRequest,
    KnowledgeExtractionResult,
    MemoryNode,
    Neo4jServiceConfig,
    NodeType,
    RelationshipType,
)
from qdrant_neo4j_crawl4ai_mcp.services.neo4j_client import Neo4jClient

logger = structlog.get_logger(__name__)


class GraphService:
    """
    Comprehensive Neo4j graph service with memory systems and GraphRAG integration.

    Features:
    - Knowledge graph management with cognitive dimensions
    - Memory storage and retrieval for AI assistants
    - AI-powered knowledge extraction from text
    - Graph analysis and community detection
    - Hybrid reasoning with vector similarity
    - F-contraction merging for concept consolidation
    """

    def __init__(self, config: Neo4jServiceConfig) -> None:
        """
        Initialize graph service with configuration.

        Args:
            config: Neo4j service configuration
        """
        self.config = config
        self.client = Neo4jClient(config)
        self._openai_client: AsyncOpenAI | None = None
        self._memory_cache: dict[str, MemoryNode] = {}

        # Initialize OpenAI client for GraphRAG if enabled
        if config.enable_graphrag and config.openai_api_key:
            self._openai_client = AsyncOpenAI(api_key=config.openai_api_key)

        logger.info(
            "Graph service initialized",
            graphrag_enabled=config.enable_graphrag,
            database=config.database,
        )

    async def initialize(self) -> None:
        """Initialize the graph service and underlying client."""
        await self.client.initialize()
        logger.info("Graph service initialization completed")

    async def shutdown(self) -> None:
        """Shutdown the graph service."""
        await self.client.shutdown()
        self._memory_cache.clear()
        logger.info("Graph service shutdown completed")

    async def health_check(self) -> GraphHealthCheck:
        """Perform health check of the graph service."""
        return await self.client.health_check()

    # Memory Management Operations

    async def create_memory_node(
        self,
        name: str,
        memory_type: str = "general",
        observations: list[str] | None = None,
        context: str | None = None,
    ) -> MemoryNode:
        """
        Create a memory node for long-term storage.

        Args:
            name: Memory subject name
            memory_type: Type of memory
            observations: List of observations
            context: Memory context

        Returns:
            Created memory node
        """
        memory_id = str(uuid4())
        observations = observations or []

        memory_node = MemoryNode(
            id=memory_id,
            name=name,
            memory_type=memory_type,
            observations=observations,
            context=context,
        )

        # Store in Neo4j
        query = CypherQuery(
            query="""
            CREATE (m:Memory {
                id: $id,
                name: $name,
                memory_type: $memory_type,
                observations: $observations,
                context: $context,
                created_at: datetime(),
                updated_at: datetime(),
                access_count: 0
            })
            RETURN m
            """,
            parameters={
                "id": memory_id,
                "name": name,
                "memory_type": memory_type,
                "observations": observations,
                "context": context,
            },
            read_only=False,
        )

        result = await self.client.execute_query(query)

        if result.success:
            # Cache the memory node
            self._memory_cache[memory_id] = memory_node

            logger.info(
                "Memory node created",
                memory_id=memory_id,
                name=name,
                memory_type=memory_type,
            )

            return memory_node
        logger.error("Failed to create memory node", error=result.error)
        raise RuntimeError(f"Failed to create memory node: {result.error}")

    async def get_memory_node(self, memory_id: str) -> MemoryNode | None:
        """
        Retrieve a memory node by ID.

        Args:
            memory_id: Memory node ID

        Returns:
            Memory node if found
        """
        # Check cache first
        if memory_id in self._memory_cache:
            return self._memory_cache[memory_id]

        query = CypherQuery(
            query="""
            MATCH (m:Memory {id: $id})
            SET m.access_count = m.access_count + 1,
                m.last_accessed = datetime()
            RETURN m
            """,
            parameters={"id": memory_id},
            read_only=False,  # Updates access count
        )

        result = await self.client.execute_query(query)

        if result.success and result.records:
            record = result.records[0]["m"]

            memory_node = MemoryNode(
                id=record["id"],
                name=record["name"],
                memory_type=record.get("memory_type", "general"),
                observations=record.get("observations", []),
                context=record.get("context"),
                created_at=record.get("created_at"),
                updated_at=record.get("updated_at"),
                last_accessed=record.get("last_accessed"),
                access_count=record.get("access_count", 0),
            )

            # Update cache
            self._memory_cache[memory_id] = memory_node

            return memory_node

        return None

    async def search_memories(
        self, query: str, memory_type: str | None = None, limit: int = 10
    ) -> list[MemoryNode]:
        """
        Search memory nodes by content.

        Args:
            query: Search query
            memory_type: Optional memory type filter
            limit: Maximum results

        Returns:
            List of matching memory nodes
        """
        cypher_query = """
        MATCH (m:Memory)
        WHERE toLower(m.name) CONTAINS toLower($query)
        OR any(obs IN m.observations WHERE toLower(obs) CONTAINS toLower($query))
        """

        parameters = {"query": query}

        if memory_type:
            cypher_query += " AND m.memory_type = $memory_type"
            parameters["memory_type"] = memory_type

        cypher_query += """
        RETURN m
        ORDER BY m.access_count DESC, m.updated_at DESC
        LIMIT $limit
        """
        parameters["limit"] = limit

        query_obj = CypherQuery(
            query=cypher_query, parameters=parameters, read_only=True
        )

        result = await self.client.execute_query(query_obj)

        memories = []
        if result.success:
            for record in result.records:
                m = record["m"]
                memory_node = MemoryNode(
                    id=m["id"],
                    name=m["name"],
                    memory_type=m.get("memory_type", "general"),
                    observations=m.get("observations", []),
                    context=m.get("context"),
                    created_at=m.get("created_at"),
                    updated_at=m.get("updated_at"),
                    last_accessed=m.get("last_accessed"),
                    access_count=m.get("access_count", 0),
                )
                memories.append(memory_node)

        return memories

    async def update_memory_observations(
        self, memory_id: str, new_observations: list[str], append: bool = True
    ) -> bool:
        """
        Update memory node observations.

        Args:
            memory_id: Memory node ID
            new_observations: New observations to add or replace
            append: Whether to append or replace observations

        Returns:
            True if successful
        """
        if append:
            query = CypherQuery(
                query="""
                MATCH (m:Memory {id: $id})
                SET m.observations = m.observations + $new_observations,
                    m.updated_at = datetime()
                RETURN m
                """,
                parameters={"id": memory_id, "new_observations": new_observations},
                read_only=False,
            )
        else:
            query = CypherQuery(
                query="""
                MATCH (m:Memory {id: $id})
                SET m.observations = $new_observations,
                    m.updated_at = datetime()
                RETURN m
                """,
                parameters={"id": memory_id, "new_observations": new_observations},
                read_only=False,
            )

        result = await self.client.execute_query(query)

        if result.success:
            # Update cache
            if memory_id in self._memory_cache:
                if append:
                    self._memory_cache[memory_id].observations.extend(new_observations)
                else:
                    self._memory_cache[memory_id].observations = new_observations
                self._memory_cache[memory_id].updated_at = datetime.utcnow()

            logger.info(
                "Memory observations updated",
                memory_id=memory_id,
                append=append,
                new_count=len(new_observations),
            )
            return True

        return False

    # Knowledge Graph Operations

    async def create_entity_node(self, node: GraphNode) -> str:
        """
        Create an entity node in the knowledge graph.

        Args:
            node: Graph node to create

        Returns:
            Created node ID
        """
        query = CypherQuery(
            query=f"""
            CREATE (n:{node.node_type.value} {{
                id: $id,
                name: $name,
                description: $description,
                properties: $properties,
                tags: $tags,
                emotional_valence: $emotional_valence,
                abstraction_level: $abstraction_level,
                confidence_score: $confidence_score,
                source: $source,
                sources: $sources,
                embedding: $embedding,
                created_at: datetime(),
                updated_at: datetime()
            }})
            RETURN n.id as id
            """,
            parameters={
                "id": node.id,
                "name": node.name,
                "description": node.description,
                "properties": node.properties,
                "tags": node.tags,
                "emotional_valence": node.emotional_valence,
                "abstraction_level": node.abstraction_level,
                "confidence_score": node.confidence_score,
                "source": node.source,
                "sources": node.sources,
                "embedding": node.embedding,
            },
            read_only=False,
        )

        result = await self.client.execute_query(query)

        if result.success and result.records:
            created_id = result.records[0]["id"]
            logger.info(
                "Entity node created", node_id=created_id, node_type=node.node_type
            )
            return created_id
        logger.error("Failed to create entity node", error=result.error)
        raise RuntimeError(f"Failed to create entity node: {result.error}")

    async def create_relationship(self, relationship: GraphRelationship) -> str:
        """
        Create a relationship between two nodes.

        Args:
            relationship: Relationship to create

        Returns:
            Created relationship ID
        """
        query = CypherQuery(
            query=f"""
            MATCH (source) WHERE source.id = $source_id
            MATCH (target) WHERE target.id = $target_id
            CREATE (source)-[r:{relationship.relationship_type.value} {{
                id: $id,
                properties: $properties,
                weight: $weight,
                confidence: $confidence,
                source: $source,
                evidence: $evidence,
                created_at: datetime(),
                valid_from: $valid_from,
                valid_until: $valid_until
            }}]->(target)
            RETURN r.id as id
            """,
            parameters={
                "source_id": relationship.source_id,
                "target_id": relationship.target_id,
                "id": relationship.id,
                "properties": relationship.properties,
                "weight": relationship.weight,
                "confidence": relationship.confidence,
                "source": relationship.source,
                "evidence": relationship.evidence,
                "valid_from": relationship.valid_from,
                "valid_until": relationship.valid_until,
            },
            read_only=False,
        )

        result = await self.client.execute_query(query)

        if result.success and result.records:
            created_id = result.records[0]["id"]
            logger.info(
                "Relationship created",
                relationship_id=created_id,
                type=relationship.relationship_type,
                source=relationship.source_id,
                target=relationship.target_id,
            )
            return created_id
        logger.error("Failed to create relationship", error=result.error)
        raise RuntimeError(f"Failed to create relationship: {result.error}")

    async def search_graph(self, request: GraphSearchRequest) -> GraphSearchResult:
        """
        Perform comprehensive graph search with multiple modes.

        Args:
            request: Graph search request

        Returns:
            Search results with nodes, relationships, and paths
        """
        start_time = time.time()

        # Build dynamic Cypher query based on search parameters
        query_parts = []
        parameters = {"query": request.query, "limit": request.limit}

        # Node matching
        if request.node_types:
            type_labels = "|".join([nt.value for nt in request.node_types])
            query_parts.append(f"MATCH (n:{type_labels})")
        else:
            query_parts.append("MATCH (n)")

        # Search conditions
        search_conditions = []
        search_conditions.append("toLower(n.name) CONTAINS toLower($query)")

        if hasattr(request, "description") and request.query:
            search_conditions.append("toLower(n.description) CONTAINS toLower($query)")

        # Confidence filter
        if request.confidence_threshold > 0:
            search_conditions.append("n.confidence_score >= $confidence_threshold")
            parameters["confidence_threshold"] = request.confidence_threshold

        # Date filters
        if request.date_from:
            search_conditions.append("n.created_at >= $date_from")
            parameters["date_from"] = request.date_from

        if request.date_to:
            search_conditions.append("n.created_at <= $date_to")
            parameters["date_to"] = request.date_to

        if search_conditions:
            query_parts.append("WHERE " + " AND ".join(search_conditions))

        # Relationship traversal for deeper search
        if request.max_depth > 1:
            if request.relationship_types:
                rel_types = "|".join([rt.value for rt in request.relationship_types])
                query_parts.append(
                    f"OPTIONAL MATCH (n)-[r:{rel_types}*1..{request.max_depth}]-(connected)"
                )
            else:
                query_parts.append(
                    f"OPTIONAL MATCH (n)-[r*1..{request.max_depth}]-(connected)"
                )

        # Return clause
        if request.max_depth > 1:
            query_parts.append("""
            RETURN DISTINCT n,
                   collect(DISTINCT r) as relationships,
                   collect(DISTINCT connected) as connected_nodes
            ORDER BY n.confidence_score DESC, n.created_at DESC
            LIMIT $limit
            """)
        else:
            query_parts.append("""
            RETURN n
            ORDER BY n.confidence_score DESC, n.created_at DESC
            LIMIT $limit
            """)

        cypher_query = CypherQuery(
            query=" ".join(query_parts), parameters=parameters, read_only=True
        )

        result = await self.client.execute_query(cypher_query)

        nodes = []
        relationships = []
        paths = []
        confidence_scores = []

        if result.success:
            for record in result.records:
                # Process main nodes
                node_data = record["n"]
                node = GraphNode(
                    id=node_data["id"],
                    name=node_data["name"],
                    node_type=NodeType(node_data.get("labels", ["Entity"])[0]),
                    description=node_data.get("description"),
                    properties=node_data.get("properties", {}),
                    tags=node_data.get("tags", []),
                    emotional_valence=node_data.get("emotional_valence"),
                    abstraction_level=node_data.get("abstraction_level"),
                    confidence_score=node_data.get("confidence_score", 0.5),
                    source=node_data.get("source"),
                    sources=node_data.get("sources", []),
                    embedding=node_data.get("embedding"),
                    created_at=node_data.get("created_at"),
                    updated_at=node_data.get("updated_at"),
                )
                nodes.append(node)
                confidence_scores.append(node.confidence_score)

                # Process relationships if depth > 1
                if request.max_depth > 1 and "relationships" in record:
                    rel_data = record.get("relationships", [])
                    for rel in rel_data:
                        if rel:  # Skip None relationships
                            relationship = GraphRelationship(
                                id=rel.get("id", str(uuid4())),
                                source_id=rel.get("source_id", ""),
                                target_id=rel.get("target_id", ""),
                                relationship_type=RelationshipType(
                                    rel.get("type", "RELATES_TO")
                                ),
                                properties=rel.get("properties", {}),
                                weight=rel.get("weight", 1.0),
                                confidence=rel.get("confidence", 0.5),
                                source=rel.get("source"),
                                evidence=rel.get("evidence", []),
                            )
                            relationships.append(relationship)

        search_time_ms = (time.time() - start_time) * 1000

        return GraphSearchResult(
            nodes=nodes,
            relationships=relationships,
            paths=paths,
            total_results=len(nodes),
            search_time_ms=search_time_ms,
            confidence_scores=confidence_scores,
            query_type="graph_search",
            filters_applied={
                "node_types": [nt.value for nt in request.node_types],
                "relationship_types": [rt.value for rt in request.relationship_types],
                "max_depth": request.max_depth,
                "confidence_threshold": request.confidence_threshold,
            },
        )

    # GraphRAG Integration

    async def extract_knowledge_from_text(
        self, request: KnowledgeExtractionRequest
    ) -> KnowledgeExtractionResult:
        """
        Extract knowledge from text using AI-powered GraphRAG.

        Args:
            request: Knowledge extraction request

        Returns:
            Extracted knowledge as nodes and relationships
        """
        if not self._openai_client:
            raise RuntimeError("GraphRAG not enabled - OpenAI client not configured")

        start_time = time.time()

        # Prepare extraction prompt
        extraction_prompt = self._build_extraction_prompt(request)

        try:
            # Call OpenAI for knowledge extraction
            response = await self._openai_client.chat.completions.create(
                model=self.config.llm_model,
                messages=[
                    {
                        "role": "system",
                        "content": "You are an expert knowledge extraction system. Extract entities, relationships, and concepts from text and return them in the specified JSON format.",
                    },
                    {"role": "user", "content": extraction_prompt},
                ],
                response_format={"type": "json_object"},
                temperature=0,
                max_tokens=4000,
            )

            # Parse extraction results
            extracted_data = json.loads(response.choices[0].message.content)

            # Convert to graph objects
            nodes, relationships = await self._process_extracted_data(
                extracted_data, request
            )

            # Entity resolution and merging
            if request.merge_similar_entities:
                nodes = await self._merge_similar_entities(nodes)

            # Filter by confidence threshold
            filtered_nodes = [
                n for n in nodes if n.confidence_score >= request.confidence_threshold
            ]
            filtered_relationships = [
                r for r in relationships if r.confidence >= request.confidence_threshold
            ]

            processing_time_ms = (time.time() - start_time) * 1000

            # Calculate quality metrics
            avg_confidence = (
                sum(n.confidence_score for n in filtered_nodes) / len(filtered_nodes)
                if filtered_nodes
                else 0.0
            )
            low_confidence_items = len(
                [n for n in nodes if n.confidence_score < 0.7]
            ) + len([r for r in relationships if r.confidence < 0.7])

            logger.info(
                "Knowledge extraction completed",
                extracted_entities=len(filtered_nodes),
                extracted_relationships=len(filtered_relationships),
                processing_time_ms=processing_time_ms,
                average_confidence=avg_confidence,
            )

            return KnowledgeExtractionResult(
                extracted_nodes=filtered_nodes,
                extracted_relationships=filtered_relationships,
                total_entities=len(filtered_nodes),
                total_relationships=len(filtered_relationships),
                processing_time_ms=processing_time_ms,
                average_confidence=avg_confidence,
                low_confidence_items=low_confidence_items,
                source_metadata={
                    "source_url": request.source_url,
                    "source_type": request.source_type,
                    "document_id": request.document_id,
                    "text_length": len(request.text),
                    "extraction_model": self.config.llm_model,
                },
            )

        except Exception as e:
            logger.exception("Knowledge extraction failed", error=str(e))
            raise RuntimeError(f"Knowledge extraction failed: {e!s}")

    async def analyze_graph_structure(
        self, request: GraphAnalysisRequest
    ) -> GraphAnalysisResult:
        """
        Perform comprehensive graph analysis and metrics calculation.

        Args:
            request: Graph analysis request

        Returns:
            Graph analysis results with metrics and insights
        """
        start_time = time.time()

        # Build analysis queries based on request
        analysis_queries = []

        # Basic statistics
        analysis_queries.extend(
            [
                CypherQuery(
                    query="MATCH (n) RETURN count(n) as node_count", read_only=True
                ),
                CypherQuery(
                    query="MATCH ()-[r]->() RETURN count(r) as rel_count",
                    read_only=True,
                ),
            ]
        )

        # Density calculation
        analysis_queries.append(
            CypherQuery(
                query="""
            MATCH (n)
            WITH count(n) as node_count
            MATCH ()-[r]->()
            WITH node_count, count(r) as rel_count
            RETURN CASE
                WHEN node_count > 1
                THEN toFloat(rel_count) / (node_count * (node_count - 1))
                ELSE 0.0
            END as density
            """,
                read_only=True,
            )
        )

        # Focus node analysis
        focus_node = None
        if request.focus_node_id:
            focus_queries = [
                CypherQuery(
                    query="MATCH (n {id: $node_id}) RETURN n",
                    parameters={"node_id": request.focus_node_id},
                    read_only=True,
                ),
                CypherQuery(
                    query="""
                    MATCH (n {id: $node_id})-[r]-(connected)
                    RETURN count(DISTINCT connected) as degree,
                           count(r) as total_relationships
                    """,
                    parameters={"node_id": request.focus_node_id},
                    read_only=True,
                ),
            ]
            analysis_queries.extend(focus_queries)

        # Execute analysis queries
        results = await self.client.execute_batch_queries(analysis_queries)

        # Process results
        node_count = results[0].records[0]["node_count"] if results[0].success else 0
        relationship_count = (
            results[1].records[0]["rel_count"] if results[1].success else 0
        )
        density = results[2].records[0]["density"] if results[2].success else 0.0

        # Focus node details
        if request.focus_node_id and len(results) > 3:
            if results[3].success and results[3].records:
                focus_data = results[3].records[0]["n"]
                focus_node = GraphNode(
                    id=focus_data["id"],
                    name=focus_data["name"],
                    node_type=NodeType(focus_data.get("labels", ["Entity"])[0]),
                    description=focus_data.get("description"),
                    confidence_score=focus_data.get("confidence_score", 0.5),
                )

        # Centrality measures (simplified)
        centrality_measures = {}
        influential_nodes = []

        if request.include_metrics and node_count > 0:
            # Degree centrality
            degree_query = CypherQuery(
                query="""
                MATCH (n)
                OPTIONAL MATCH (n)-[r]-(connected)
                WITH n, count(DISTINCT connected) as degree
                RETURN n.id as node_id, n.name as name, degree
                ORDER BY degree DESC
                LIMIT 10
                """,
                read_only=True,
            )

            degree_result = await self.client.execute_query(degree_query)
            if degree_result.success:
                for record in degree_result.records:
                    node_id = record["node_id"]
                    degree = record["degree"]
                    centrality_measures[node_id] = {"degree": degree}

                    if len(influential_nodes) < 5:
                        influential_nodes.append(node_id)

        # Community detection (placeholder - would use Neo4j GDS in production)
        communities = []
        modularity = None

        if request.include_communities:
            # Simplified community detection using connected components
            community_query = CypherQuery(
                query="""
                MATCH (n)
                OPTIONAL MATCH path = (n)-[*1..3]-(connected)
                WITH n, collect(DISTINCT connected.id) as component
                RETURN n.id as node_id, component
                """,
                read_only=True,
            )

            community_result = await self.client.execute_query(community_query)
            if community_result.success:
                # Process connected components (simplified)
                node_communities = {}
                for record in community_result.records:
                    node_id = record["node_id"]
                    component = record["component"]

                    # Simple heuristic for community assignment
                    community_id = hash(tuple(sorted(component[:5]))) % 10
                    node_communities[node_id] = community_id

                # Group by community
                community_groups = {}
                for node_id, community_id in node_communities.items():
                    if community_id not in community_groups:
                        community_groups[community_id] = []
                    community_groups[community_id].append(node_id)

                communities = list(community_groups.values())

        # Shortest paths
        shortest_paths = {}
        if request.include_paths and request.focus_node_id:
            path_query = CypherQuery(
                query="""
                MATCH (start {id: $node_id}), (end)
                WHERE start <> end
                MATCH path = shortestPath((start)-[*1..4]-(end))
                RETURN end.id as target_id, [node in nodes(path) | node.id] as path
                LIMIT 10
                """,
                parameters={"node_id": request.focus_node_id},
                read_only=True,
            )

            path_result = await self.client.execute_query(path_query)
            if path_result.success:
                for record in path_result.records:
                    target_id = record["target_id"]
                    path = record["path"]
                    shortest_paths[target_id] = path

        analysis_time_ms = (time.time() - start_time) * 1000

        logger.info(
            "Graph analysis completed",
            node_count=node_count,
            relationship_count=relationship_count,
            density=density,
            analysis_time_ms=analysis_time_ms,
        )

        return GraphAnalysisResult(
            analysis_type=request.analysis_type,
            focus_node=focus_node,
            node_count=node_count,
            relationship_count=relationship_count,
            density=density,
            average_clustering=0.0,  # Would calculate with proper clustering algorithm
            centrality_measures=centrality_measures,
            influential_nodes=influential_nodes,
            communities=communities,
            modularity=modularity,
            shortest_paths=shortest_paths,
            temporal_patterns={},  # Would implement temporal analysis
            analysis_time_ms=analysis_time_ms,
            confidence=0.8,  # Confidence in analysis quality
        )

    # Custom Cypher Query Execution

    async def execute_cypher(self, query: CypherQuery) -> CypherResult:
        """
        Execute custom Cypher query with safety checks.

        Args:
            query: Cypher query to execute

        Returns:
            Query execution result
        """
        # Safety checks for destructive operations
        if not query.read_only:
            destructive_patterns = [
                r"\bDELETE\b",
                r"\bDETACH DELETE\b",
                r"\bDROP\b",
                r"\bCREATE CONSTRAINT\b",
                r"\bDROP CONSTRAINT\b",
            ]

            query_upper = query.query.upper()
            for pattern in destructive_patterns:
                if re.search(pattern, query_upper):
                    logger.warning(
                        "Potentially destructive query detected",
                        query=query.query[:100],
                        pattern=pattern,
                    )
                    # Could add additional authorization checks here
                    break

        return await self.client.execute_query(query)

    # Helper Methods

    def _build_extraction_prompt(self, request: KnowledgeExtractionRequest) -> str:
        """Build prompt for knowledge extraction."""
        allowed_node_types = (
            [nt.value for nt in request.allowed_node_types]
            if request.allowed_node_types
            else [nt.value for nt in NodeType]
        )
        allowed_rel_types = (
            [rt.value for rt in request.allowed_relationship_types]
            if request.allowed_relationship_types
            else [rt.value for rt in RelationshipType]
        )

        return f"""
        Extract knowledge from the following text and return it as a JSON object with 'entities' and 'relationships' arrays.

        Text to analyze:
        {request.text}

        Extraction Guidelines:
        - Extract entities of types: {", ".join(allowed_node_types)}
        - Extract relationships of types: {", ".join(allowed_rel_types)}
        - Include confidence scores (0.0 to 1.0) for each extraction
        - Extract emotional valence (-1.0 to 1.0) for entities when applicable
        - Assign abstraction levels (1-10) for concepts
        - Maximum entities: {request.max_entities}

        JSON format:
        {{
            "entities": [
                {{
                    "name": "entity name",
                    "type": "Entity|Person|Organization|...",
                    "description": "description",
                    "confidence": 0.8,
                    "emotional_valence": 0.2,
                    "abstraction_level": 3,
                    "properties": {{"key": "value"}},
                    "tags": ["tag1", "tag2"]
                }}
            ],
            "relationships": [
                {{
                    "source": "source entity name",
                    "target": "target entity name",
                    "type": "KNOWS|WORKS_FOR|RELATES_TO|...",
                    "confidence": 0.7,
                    "properties": {{"key": "value"}},
                    "evidence": "text evidence for relationship"
                }}
            ]
        }}
        """

    async def _process_extracted_data(
        self, extracted_data: dict[str, Any], request: KnowledgeExtractionRequest
    ) -> tuple[list[GraphNode], list[GraphRelationship]]:
        """Process extracted data into graph objects."""
        nodes = []
        relationships = []

        # Create node lookup for relationship processing
        node_lookup = {}

        # Process entities
        for entity_data in extracted_data.get("entities", []):
            try:
                node_type = NodeType(entity_data.get("type", "Entity"))

                node = GraphNode(
                    name=entity_data["name"],
                    node_type=node_type,
                    description=entity_data.get("description"),
                    properties=entity_data.get("properties", {}),
                    tags=entity_data.get("tags", []),
                    emotional_valence=entity_data.get("emotional_valence"),
                    abstraction_level=entity_data.get("abstraction_level"),
                    confidence_score=entity_data.get("confidence", 0.5),
                    source=request.source_url or "text_extraction",
                    sources=[request.source_url] if request.source_url else [],
                )

                nodes.append(node)
                node_lookup[node.name.lower()] = node.id

            except (ValueError, KeyError) as e:
                logger.warning("Invalid entity data", entity=entity_data, error=str(e))
                continue

        # Process relationships
        for rel_data in extracted_data.get("relationships", []):
            try:
                source_name = rel_data["source"].lower()
                target_name = rel_data["target"].lower()

                if source_name in node_lookup and target_name in node_lookup:
                    rel_type = RelationshipType(rel_data.get("type", "RELATES_TO"))

                    relationship = GraphRelationship(
                        source_id=node_lookup[source_name],
                        target_id=node_lookup[target_name],
                        relationship_type=rel_type,
                        properties=rel_data.get("properties", {}),
                        confidence=rel_data.get("confidence", 0.5),
                        source=request.source_url or "text_extraction",
                        evidence=[rel_data.get("evidence", "")],
                    )

                    relationships.append(relationship)

            except (ValueError, KeyError) as e:
                logger.warning(
                    "Invalid relationship data", relationship=rel_data, error=str(e)
                )
                continue

        return nodes, relationships

    async def _merge_similar_entities(self, nodes: list[GraphNode]) -> list[GraphNode]:
        """
        Merge similar entities using F-contraction approach.

        Args:
            nodes: List of nodes to process

        Returns:
            List of merged nodes
        """
        if not self._openai_client or len(nodes) < 2:
            return nodes

        # Simple similarity-based merging
        merged_nodes = []
        processed_names = set()

        for node in nodes:
            if node.name.lower() in processed_names:
                continue

            # Find similar nodes
            similar_nodes = [node]
            for other_node in nodes:
                if (
                    other_node.name.lower() != node.name.lower()
                    and other_node.name.lower() not in processed_names
                    and self._calculate_name_similarity(node.name, other_node.name)
                    > 0.8
                ):
                    similar_nodes.append(other_node)
                    processed_names.add(other_node.name.lower())

            if len(similar_nodes) > 1:
                # Merge similar nodes
                merged_node = self._merge_node_group(similar_nodes)
                merged_nodes.append(merged_node)
            else:
                merged_nodes.append(node)

            processed_names.add(node.name.lower())

        logger.info(
            "Entity merging completed",
            original_count=len(nodes),
            merged_count=len(merged_nodes),
        )

        return merged_nodes

    def _calculate_name_similarity(self, name1: str, name2: str) -> float:
        """Calculate simple name similarity."""
        from difflib import SequenceMatcher

        return SequenceMatcher(None, name1.lower(), name2.lower()).ratio()

    def _merge_node_group(self, nodes: list[GraphNode]) -> GraphNode:
        """Merge a group of similar nodes using F-contraction principles."""
        if not nodes:
            return None

        # Use the node with highest confidence as base
        base_node = max(nodes, key=lambda n: n.confidence_score)

        # Merge properties
        merged_properties = base_node.properties.copy()
        merged_tags = set(base_node.tags)
        merged_sources = set(base_node.sources)

        for node in nodes:
            if node.id != base_node.id:
                merged_properties.update(node.properties)
                merged_tags.update(node.tags)
                merged_sources.update(node.sources)

        # Calculate merged confidence (average weighted by individual confidence)
        total_confidence = sum(n.confidence_score for n in nodes)
        avg_confidence = total_confidence / len(nodes)

        # Create merged node
        return GraphNode(
            id=base_node.id,  # Keep base node ID
            name=base_node.name,  # Keep base node name
            node_type=base_node.node_type,
            description=base_node.description,
            properties=merged_properties,
            tags=list(merged_tags),
            emotional_valence=base_node.emotional_valence,
            abstraction_level=base_node.abstraction_level,
            confidence_score=min(avg_confidence * 1.1, 1.0),  # Slight boost for merging
            source=base_node.source,
            sources=list(merged_sources),
            embedding=base_node.embedding,
            created_at=base_node.created_at,
            updated_at=datetime.utcnow(),
        )
