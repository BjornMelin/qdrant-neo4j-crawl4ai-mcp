"""
Configuration management for the Qdrant Neo4j Web MCP Server.

Provides secure, environment-based configuration using Pydantic v2 with
comprehensive validation and secret handling for production deployments.
"""

from functools import lru_cache
import secrets
from typing import Literal

from pydantic import Field, SecretStr, validator
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """
    Application settings with secure defaults and environment variable support.

    All sensitive values use SecretStr to prevent accidental logging of secrets.
    Configuration is loaded from environment variables with fallback defaults.
    """

    # Application Configuration
    app_name: str = Field(
        default="Qdrant Neo4j Web MCP Server",
        description="Application name for logging and monitoring",
    )
    app_version: str = Field(default="1.0.0", description="Application version")
    environment: Literal["development", "staging", "production"] = Field(
        default="development", env="ENVIRONMENT", description="Deployment environment"
    )
    debug: bool = Field(
        default=False,
        env="DEBUG",
        description="Enable debug mode (only for development)",
    )

    # Server Configuration
    host: str = Field(default="0.0.0.0", env="HOST", description="Server bind address")
    port: int = Field(
        default=8000, env="PORT", ge=1, le=65535, description="Server port"
    )
    workers: int = Field(
        default=1, env="WORKERS", ge=1, le=8, description="Number of worker processes"
    )

    # Security Configuration
    jwt_secret_key: SecretStr = Field(
        default_factory=lambda: SecretStr(secrets.token_urlsafe(32)),
        env="JWT_SECRET_KEY",
        description="JWT signing secret key",
    )
    jwt_algorithm: str = Field(
        default="HS256", env="JWT_ALGORITHM", description="JWT signing algorithm"
    )
    jwt_expire_minutes: int = Field(
        default=30,
        env="JWT_EXPIRE_MINUTES",
        ge=5,
        le=1440,
        description="JWT token expiration time in minutes",
    )

    # API Keys and Authentication
    api_key_header: str = Field(
        default="X-API-Key", env="API_KEY_HEADER", description="API key header name"
    )
    admin_api_key: SecretStr = Field(
        default_factory=lambda: SecretStr(secrets.token_urlsafe(32)),
        env="ADMIN_API_KEY",
        description="Admin API key for administrative operations",
    )

    # Rate Limiting Configuration
    rate_limit_per_minute: int = Field(
        default=100,
        env="RATE_LIMIT_PER_MINUTE",
        ge=1,
        le=10000,
        description="Rate limit per minute per IP",
    )
    rate_limit_burst: int = Field(
        default=20,
        env="RATE_LIMIT_BURST",
        ge=1,
        le=1000,
        description="Rate limit burst allowance",
    )

    # CORS Configuration
    allowed_origins: list[str] = Field(
        default=["http://localhost:3000", "http://localhost:8080"],
        env="ALLOWED_ORIGINS",
        description="Allowed CORS origins",
    )
    allowed_methods: list[str] = Field(
        default=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
        env="ALLOWED_METHODS",
        description="Allowed HTTP methods",
    )
    allowed_headers: list[str] = Field(
        default=["Authorization", "Content-Type", "X-API-Key"],
        env="ALLOWED_HEADERS",
        description="Allowed HTTP headers",
    )

    # Database Configuration
    database_url: SecretStr = Field(
        default=SecretStr("sqlite:///./qdrant_neo4j_crawl4ai_mcp.db"),
        env="DATABASE_URL",
        description="Database connection URL",
    )
    database_pool_size: int = Field(
        default=10,
        env="DATABASE_POOL_SIZE",
        ge=1,
        le=50,
        description="Database connection pool size",
    )

    # Redis Configuration (for caching and rate limiting)
    redis_url: str = Field(
        default="redis://localhost:6379/0",
        env="REDIS_URL",
        description="Redis connection URL",
    )
    redis_password: SecretStr | None = Field(
        default=None, env="REDIS_PASSWORD", description="Redis password (if required)"
    )

    # Service URLs
    qdrant_url: str = Field(
        default="http://localhost:6333",
        env="QDRANT_URL",
        description="Qdrant vector database URL",
    )
    qdrant_api_key: SecretStr | None = Field(
        default=None, env="QDRANT_API_KEY", description="Qdrant API key (if required)"
    )

    neo4j_uri: str = Field(
        default="bolt://localhost:7687",
        env="NEO4J_URI",
        description="Neo4j database URI",
    )
    neo4j_user: str = Field(
        default="neo4j", env="NEO4J_USER", description="Neo4j username"
    )
    neo4j_password: SecretStr = Field(
        default=SecretStr("password"),
        env="NEO4J_PASSWORD",
        description="Neo4j password",
    )

    # Neo4j Graph Configuration
    neo4j_database: str = Field(
        default="neo4j", env="NEO4J_DATABASE", description="Neo4j database name"
    )
    neo4j_max_pool_size: int = Field(
        default=50,
        env="NEO4J_MAX_POOL_SIZE",
        ge=1,
        le=200,
        description="Neo4j connection pool size",
    )
    neo4j_connection_timeout: int = Field(
        default=30,
        env="NEO4J_CONNECTION_TIMEOUT",
        ge=5,
        le=300,
        description="Neo4j connection timeout in seconds",
    )
    neo4j_enable_graphrag: bool = Field(
        default=True,
        env="NEO4J_ENABLE_GRAPHRAG",
        description="Enable GraphRAG integration",
    )
    openai_api_key: SecretStr | None = Field(
        default=None, env="OPENAI_API_KEY", description="OpenAI API key for GraphRAG"
    )
    openai_embedding_model: str = Field(
        default="text-embedding-3-large",
        env="OPENAI_EMBEDDING_MODEL",
        description="OpenAI embedding model for GraphRAG",
    )
    openai_llm_model: str = Field(
        default="gpt-4o",
        env="OPENAI_LLM_MODEL",
        description="OpenAI LLM model for GraphRAG",
    )

    # Crawl4AI Web Intelligence Configuration
    crawl4ai_max_concurrent: int = Field(
        default=5,
        env="CRAWL4AI_MAX_CONCURRENT",
        ge=1,
        le=20,
        description="Maximum concurrent crawl operations",
    )
    crawl4ai_request_timeout: int = Field(
        default=30,
        env="CRAWL4AI_REQUEST_TIMEOUT",
        ge=5,
        le=300,
        description="Crawl request timeout in seconds",
    )
    crawl4ai_user_agent: str = Field(
        default="QdrantNeo4jCrawl4AIMCP/1.0 (Crawl4AI; +https://github.com/qdrant-neo4j-crawl4ai-mcp)",
        env="CRAWL4AI_USER_AGENT",
        description="User agent string for web requests",
    )
    crawl4ai_check_robots_txt: bool = Field(
        default=True,
        env="CRAWL4AI_CHECK_ROBOTS_TXT",
        description="Respect robots.txt files",
    )
    crawl4ai_enable_stealth: bool = Field(
        default=False,
        env="CRAWL4AI_ENABLE_STEALTH",
        description="Enable stealth mode for bot detection avoidance",
    )
    crawl4ai_enable_caching: bool = Field(
        default=True,
        env="CRAWL4AI_ENABLE_CACHING",
        description="Enable response caching",
    )
    crawl4ai_cache_ttl: int = Field(
        default=3600, env="CRAWL4AI_CACHE_TTL", ge=0, description="Cache TTL in seconds"
    )
    crawl4ai_max_retries: int = Field(
        default=3,
        env="CRAWL4AI_MAX_RETRIES",
        ge=0,
        le=10,
        description="Maximum retry attempts",
    )
    crawl4ai_retry_delay: float = Field(
        default=1.0,
        env="CRAWL4AI_RETRY_DELAY",
        ge=0.1,
        le=60.0,
        description="Retry delay in seconds",
    )

    # Web Service Vector Configuration
    default_collection: str = Field(
        default="web_content",
        env="DEFAULT_COLLECTION",
        description="Default vector collection for web content",
    )
    default_embedding_model: str = Field(
        default="sentence-transformers/all-MiniLM-L6-v2",
        env="DEFAULT_EMBEDDING_MODEL",
        description="Default embedding model",
    )

    # Connection and Performance Configuration
    connection_timeout: int = Field(
        default=30,
        env="CONNECTION_TIMEOUT",
        ge=5,
        le=300,
        description="Connection timeout in seconds",
    )
    max_retries: int = Field(
        default=3, env="MAX_RETRIES", ge=0, le=10, description="Maximum retry attempts"
    )
    retry_delay: float = Field(
        default=1.0,
        env="RETRY_DELAY",
        ge=0.1,
        le=60.0,
        description="Retry delay in seconds",
    )
    enable_caching: bool = Field(
        default=True, env="ENABLE_CACHING", description="Enable service caching"
    )

    # Logging Configuration
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = Field(
        default="INFO", env="LOG_LEVEL", description="Logging level"
    )
    log_format: Literal["json", "text"] = Field(
        default="json", env="LOG_FORMAT", description="Log output format"
    )
    log_file: str | None = Field(
        default=None,
        env="LOG_FILE",
        description="Log file path (if file logging enabled)",
    )

    # Monitoring Configuration
    enable_metrics: bool = Field(
        default=True,
        env="ENABLE_METRICS",
        description="Enable Prometheus metrics collection",
    )
    metrics_port: int = Field(
        default=9090,
        env="METRICS_PORT",
        ge=1024,
        le=65535,
        description="Prometheus metrics server port",
    )

    # Health Check Configuration
    health_check_timeout: int = Field(
        default=5,
        env="HEALTH_CHECK_TIMEOUT",
        ge=1,
        le=30,
        description="Health check timeout in seconds",
    )

    # Security Headers
    hsts_max_age: int = Field(
        default=31536000,  # 1 year
        env="HSTS_MAX_AGE",
        ge=0,
        description="HSTS max age in seconds",
    )
    csp_policy: str = Field(
        default="default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'",
        env="CSP_POLICY",
        description="Content Security Policy",
    )

    # Feature Flags
    enable_swagger_ui: bool = Field(
        default=True,
        env="ENABLE_SWAGGER_UI",
        description="Enable Swagger UI documentation",
    )
    enable_redoc: bool = Field(
        default=True, env="ENABLE_REDOC", description="Enable ReDoc documentation"
    )

    @validator("allowed_origins", pre=True)
    def parse_cors_origins(self, v: str | list[str]) -> list[str]:
        """Parse CORS origins from string or list."""
        if isinstance(v, str):
            return [origin.strip() for origin in v.split(",") if origin.strip()]
        return v

    @validator("allowed_methods", pre=True)
    def parse_cors_methods(self, v: str | list[str]) -> list[str]:
        """Parse CORS methods from string or list."""
        if isinstance(v, str):
            return [method.strip().upper() for method in v.split(",") if method.strip()]
        return v

    @validator("allowed_headers", pre=True)
    def parse_cors_headers(self, v: str | list[str]) -> list[str]:
        """Parse CORS headers from string or list."""
        if isinstance(v, str):
            return [header.strip() for header in v.split(",") if header.strip()]
        return v

    @validator("debug")
    def validate_debug_mode(self, v: bool, values: dict) -> bool:
        """Ensure debug mode is disabled in production."""
        environment = values.get("environment", "development")
        if environment == "production" and v:
            raise ValueError("Debug mode must be disabled in production")
        return v

    @validator("enable_swagger_ui", "enable_redoc")
    def validate_docs_in_production(self, v: bool, values: dict) -> bool:
        """Disable API documentation in production by default."""
        environment = values.get("environment", "development")
        if environment == "production":
            return False
        return v

    @property
    def is_production(self) -> bool:
        """Check if running in production environment."""
        return self.environment == "production"

    @property
    def is_development(self) -> bool:
        """Check if running in development environment."""
        return self.environment == "development"

    @property
    def database_dsn(self) -> str:
        """Get database DSN string (without password for logging)."""
        return self.database_url.get_secret_value()

    class Config:
        """Pydantic configuration."""

        env_file = ".env"
        env_file_encoding = "utf-8"
        case_sensitive = False
        validate_assignment = True
        extra = "forbid"  # Prevent extra fields


@lru_cache
def get_settings() -> Settings:
    """
    Get cached application settings.

    Uses LRU cache to ensure settings are loaded once and reused
    throughout the application lifecycle.

    Returns:
        Settings instance with loaded configuration
    """
    return Settings()


# Global settings instance for easy access
settings = get_settings()
