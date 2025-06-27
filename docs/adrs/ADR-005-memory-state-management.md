# ADR-005: Memory and State Management

## Status

**Accepted** - Date: 2025-06-27

## Context

### Problem Statement

Our agentic RAG system requires persistent memory and state management to enable multi-turn conversations, context accumulation, and learning from research patterns. We must select an approach that balances memory efficiency, consistency, and maintainability while leveraging our existing Qdrant + Memgraph hybrid architecture.

### Constraints and Requirements

- **Hybrid Architecture**: Must leverage existing Qdrant (vector) + Memgraph (graph) infrastructure
- **Solo Developer**: Simple implementation and debugging, minimal operational overhead
- **Performance**: Memory access <50ms, state persistence <100ms
- **Scalability**: Support 1000+ concurrent user sessions
- **Context Windows**: Handle 32K+ token conversations with efficient retrieval
- **State Consistency**: Reliable state management across distributed components

### Research Findings Summary

#### Memory Management Approaches Analyzed

1. **GraphRAG with Hybrid Storage**: Leverage existing vector + graph infrastructure
2. **In-Memory State Management**: Fast access, session-scoped storage
3. **External State Store**: Redis/PostgreSQL for persistence
4. **Hybrid Memory Architecture**: Combine multiple approaches for optimization

#### GraphRAG Integration Benefits

Based on research of existing Memgraph + Qdrant patterns:

- **Existing Infrastructure**: Leverage current vector + graph investments
- **Relationship Memory**: Store conversation context as graph relationships
- **Semantic Clustering**: Group related memories by vector similarity
- **Memory Consolidation**: F-contraction merging for concept aggregation

### Alternative Approaches Considered

1. **GraphRAG Hybrid Memory**: Graph relationships + vector embeddings
2. **Session-Based In-Memory**: Redis with session-scoped storage  
3. **Persistent Database Storage**: PostgreSQL with structured conversation logs
4. **Multi-Tier Memory**: Hot/warm/cold memory hierarchy

## Decision

### **Selected: GraphRAG Hybrid Memory with Multi-Tier Caching**

### Technical Justification

#### Core Architecture

```python
# Memory Architecture Components
class HybridMemoryManager:
    def __init__(self):
        self.vector_memory = QdrantMemoryStore()    # Semantic similarity
        self.graph_memory = MemgraphMemoryStore()   # Relationships & context
        self.session_cache = InMemoryCache()        # Hot data (TTL: 1h)
        self.consolidator = MemoryConsolidator()    # Background processing
```

#### Memory Storage Strategy

1. **Hot Memory (In-Memory)**: Active conversation context, <1s access
2. **Warm Memory (Vector)**: Semantic clusters of related concepts, <50ms
3. **Cold Memory (Graph)**: Long-term relationships and patterns, <100ms
4. **Archive Memory (Disk)**: Historical data with async access

### Key Advantages

#### vs Pure In-Memory Approach

- **Persistence**: Survives system restarts and failures
- **Scalability**: Not limited by RAM constraints
- **Relationship Modeling**: Complex context relationships preserved

#### vs External State Store Only

- **Performance**: Hybrid hot/warm cache reduces external calls
- **Infrastructure Reuse**: Leverages existing Qdrant + Memgraph investment
- **Semantic Search**: Vector similarity for memory retrieval

#### vs Flat Database Storage

- **Rich Context**: Graph relationships capture conversation flow
- **Semantic Clustering**: Automatic grouping of related memories
- **Efficient Retrieval**: Multi-modal search (semantic + relationship)

### Memory Model Design

#### Conversation Memory Schema

```python
class ConversationMemory(BaseModel):
    session_id: str
    message_id: str
    timestamp: datetime
    content: str
    embeddings: List[float]
    entities: List[str]
    relationships: List[Relationship]
    metadata: Dict[str, Any]

class MemoryConsolidation(BaseModel):
    cluster_id: str
    consolidated_concepts: List[str]
    relationship_strength: float
    access_frequency: int
    last_updated: datetime
```

#### Graph Memory Relationships

```cypher
// Memory relationship patterns in Memgraph
CREATE (m:Memory {id: $message_id, content: $content, timestamp: $timestamp})
CREATE (s:Session {id: $session_id})
CREATE (c:Concept {name: $concept, strength: $strength})

// Relationships
CREATE (m)-[:BELONGS_TO]->(s)
CREATE (m)-[:CONTAINS]->(c)
CREATE (m)-[:FOLLOWS {delay: $time_diff}]->(prev_m)
CREATE (c)-[:RELATED_TO {strength: $similarity}]->(other_c)
```

## Consequences

### Positive Outcomes

1. **Infrastructure Leverage**: 90% reuse of existing vector + graph components
2. **Performance Optimization**: Multi-tier caching reduces latency
3. **Rich Context**: Graph relationships enable complex conversation understanding
4. **Semantic Discovery**: Vector similarity finds related memories automatically
5. **Scalable Architecture**: Distributed storage supports high concurrency
6. **Memory Consolidation**: Automatic concept clustering reduces noise

### Architecture Implementation

#### Memory Access Patterns

```python
class MemoryRetrieval:
    async def get_relevant_context(self, query: str, session_id: str) -> ContextResult:
        # 1. Check hot cache first (fastest)
        hot_context = await self.session_cache.get(session_id)
        if hot_context and self._is_relevant(hot_context, query):
            return hot_context
        
        # 2. Semantic search in vector store (warm)
        semantic_memories = await self.vector_memory.similarity_search(
            query_embedding=await self.embed_query(query),
            limit=10,
            filter={"session_id": session_id}
        )
        
        # 3. Graph traversal for relationships (cold)
        related_concepts = await self.graph_memory.traverse_relationships(
            start_concepts=self._extract_concepts(query),
            max_depth=3,
            relationship_types=["RELATED_TO", "FOLLOWS", "IMPLIES"]
        )
        
        # 4. Fuse and rank results
        return await self._fuse_memory_results(
            semantic_memories, related_concepts, query
        )
```

#### Memory Consolidation Strategy

```python
class MemoryConsolidator:
    async def consolidate_session_memories(self, session_id: str):
        """Background task for memory optimization"""
        
        # 1. Identify concept clusters
        clusters = await self._cluster_by_similarity(session_id)
        
        # 2. Merge related concepts using F-contraction
        for cluster in clusters:
            consolidated = await self._merge_concepts(cluster)
            await self._update_graph_relationships(consolidated)
        
        # 3. Update vector embeddings for new concepts
        await self._refresh_vector_embeddings(session_id)
        
        # 4. Prune low-value memories
        await self._prune_irrelevant_memories(session_id)
```

### Performance Characteristics

#### Memory Access Latency

- **Hot Cache**: <1ms (in-memory lookup)
- **Vector Search**: <50ms (semantic similarity)
- **Graph Traversal**: <100ms (relationship queries)
- **Full Context Assembly**: <150ms (combined retrieval)

#### Storage Efficiency

- **Session Cache**: 10MB per active session (1000 sessions = 10GB)
- **Vector Storage**: 1KB per memory embedding
- **Graph Storage**: 500B per relationship edge
- **Compression**: 60% reduction through consolidation

### Implementation Strategy

#### Phase 1: Basic Memory (Week 1)

```python
# Simple session-scoped memory
class BasicMemory:
    def __init__(self):
        self.sessions = {}  # session_id -> conversation_history
    
    async def add_memory(self, session_id: str, message: str):
        if session_id not in self.sessions:
            self.sessions[session_id] = []
        self.sessions[session_id].append({
            'content': message,
            'timestamp': datetime.now(),
            'embedding': await self.embed(message)
        })
```

#### Phase 2: Vector Integration (Week 2)

```python
# Add Qdrant for semantic search
async def store_in_vector_db(self, session_id: str, memory: Memory):
    await self.qdrant_client.upsert(
        collection_name="conversation_memories",
        points=[{
            'id': memory.id,
            'vector': memory.embedding,
            'payload': {
                'session_id': session_id,
                'content': memory.content,
                'timestamp': memory.timestamp.isoformat(),
                'entities': memory.entities
            }
        }]
    )
```

#### Phase 3: Graph Relationships (Week 3)

```python
# Add Memgraph for relationship modeling
async def store_relationships(self, memory: Memory, session_id: str):
    # Create memory node
    await self.memgraph_client.execute("""
        CREATE (m:Memory {
            id: $id, 
            content: $content, 
            timestamp: $timestamp
        })
    """, memory.dict())
    
    # Link to previous messages
    if memory.previous_id:
        await self.memgraph_client.execute("""
            MATCH (prev:Memory {id: $prev_id})
            MATCH (curr:Memory {id: $curr_id})
            CREATE (prev)-[:FOLLOWED_BY {delay: $delay}]->(curr)
        """, {
            'prev_id': memory.previous_id,
            'curr_id': memory.id,
            'delay': memory.delay_seconds
        })
```

### Negative Consequences/Risks

1. **Complexity Increase**: Multi-tier memory adds architectural complexity
2. **Storage Overhead**: Redundant storage across vector + graph + cache
3. **Consistency Challenges**: Keeping multiple stores synchronized
4. **Memory Growth**: Unbounded growth without proper pruning
5. **Cold Start**: New sessions lack historical context

### Risk Mitigation

1. **Incremental Implementation**: Start simple, add tiers gradually
2. **Storage Limits**: Configurable memory retention policies
3. **Consistency Monitoring**: Health checks for store synchronization
4. **Background Cleanup**: Automated pruning of old/irrelevant memories
5. **Graceful Degradation**: Fall back to simpler memory when components fail

### Monitoring and Observability

#### Key Metrics

- **Memory Access Latency**: P95 latency per tier
- **Storage Growth Rate**: Memory accumulation over time
- **Cache Hit Ratios**: Effectiveness of multi-tier caching
- **Consolidation Effectiveness**: Before/after memory compression
- **Context Relevance**: Quality of retrieved memories

#### Health Checks

```python
async def memory_health_check():
    checks = {
        'session_cache_available': await self.session_cache.ping(),
        'vector_store_responsive': await self.vector_memory.health(),
        'graph_store_responsive': await self.graph_memory.health(),
        'memory_growth_rate': await self._check_growth_rate(),
        'consolidation_lag': await self._check_consolidation_lag()
    }
    return checks
```

### Success Criteria

- **Access Performance**: <150ms for full context retrieval
- **Memory Efficiency**: >60% storage reduction through consolidation
- **Context Quality**: >80% relevance in retrieved memories
- **Scalability**: Support 1000+ concurrent sessions
- **Reliability**: >99.9% memory persistence success rate

This hybrid memory architecture leverages our existing infrastructure investments while providing the rich context modeling needed for sophisticated agentic conversations.
