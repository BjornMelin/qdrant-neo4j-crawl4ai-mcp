"""
Authentication and authorization middleware for the Unified MCP Server.

Provides JWT-based authentication, API key validation, and role-based access
control with comprehensive security logging and audit trails.
"""

from datetime import UTC, datetime, timedelta
import time
from typing import Annotated, Any

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt
from passlib.context import CryptContext
from pydantic import BaseModel, Field
import structlog

from qdrant_neo4j_crawl4ai_mcp.config import Settings, get_settings

# Set up structured logging
logger = structlog.get_logger(__name__)

# Password hashing context
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# HTTP Bearer token security
security = HTTPBearer(auto_error=False)


class TokenData(BaseModel):
    """JWT token payload data."""

    username: str | None = None
    user_id: str | None = None
    scopes: list[str] = Field(default_factory=list)
    expires_at: datetime | None = None


class User(BaseModel):
    """User model with permissions and metadata."""

    id: str
    username: str
    email: str | None = None
    full_name: str | None = None
    is_active: bool = True
    is_admin: bool = False
    scopes: list[str] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    last_login: datetime | None = None


class AuthService:
    """Authentication service for JWT and API key management."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.algorithm = settings.jwt_algorithm
        self.secret_key = settings.jwt_secret_key.get_secret_value()
        self.expire_minutes = settings.jwt_expire_minutes

    def verify_password(self, plain_password: str, hashed_password: str) -> bool:
        """Verify a plain password against a hashed password."""
        return pwd_context.verify(plain_password, hashed_password)

    def get_password_hash(self, password: str) -> str:
        """Generate a hash for a password."""
        return pwd_context.hash(password)

    def create_access_token(
        self, data: dict[str, Any], expires_delta: timedelta | None = None
    ) -> str:
        """
        Create a JWT access token.

        Args:
            data: Token payload data
            expires_delta: Optional expiration time delta

        Returns:
            Encoded JWT token string
        """
        to_encode = data.copy()

        if expires_delta:
            expire = datetime.now(UTC) + expires_delta
        else:
            expire = datetime.now(UTC) + timedelta(minutes=self.expire_minutes)

        to_encode.update(
            {"exp": expire, "iat": datetime.now(UTC), "type": "access_token"}
        )

        encoded_jwt = jwt.encode(to_encode, self.secret_key, algorithm=self.algorithm)

        logger.info(
            "Access token created",
            username=data.get("sub"),
            expires_at=expire.isoformat(),
            scopes=data.get("scopes", []),
        )

        return encoded_jwt

    def verify_token(self, token: str) -> TokenData:
        """
        Verify and decode a JWT token.

        Args:
            token: JWT token string

        Returns:
            TokenData with decoded payload

        Raises:
            HTTPException: If token is invalid or expired
        """
        credentials_exception = HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Could not validate credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )

        try:
            payload = jwt.decode(token, self.secret_key, algorithms=[self.algorithm])

            # Verify token type
            if payload.get("type") != "access_token":
                logger.warning("Invalid token type", token_type=payload.get("type"))
                raise credentials_exception

            # Extract token data
            username: str = payload.get("sub")
            user_id: str = payload.get("user_id")
            scopes: list[str] = payload.get("scopes", [])
            expires_at = datetime.fromtimestamp(payload.get("exp", 0), tz=UTC)

            if username is None:
                logger.warning("Token missing subject")
                raise credentials_exception

            token_data = TokenData(
                username=username, user_id=user_id, scopes=scopes, expires_at=expires_at
            )

            logger.debug(
                "Token verified successfully",
                username=username,
                user_id=user_id,
                scopes=scopes,
            )

            return token_data

        except JWTError as e:
            logger.warning("JWT verification failed", error=str(e))
            raise credentials_exception from e

    def verify_api_key(self, api_key: str) -> bool:
        """
        Verify an API key.

        Args:
            api_key: API key to verify

        Returns:
            True if API key is valid
        """
        admin_key = self.settings.admin_api_key.get_secret_value()

        # Use constant-time comparison to prevent timing attacks
        import hmac

        return hmac.compare_digest(api_key, admin_key)


# Global auth service instance
auth_service: AuthService | None = None


def get_auth_service(
    settings: Annotated[Settings, Depends(get_settings)],
) -> AuthService:
    """Get the authentication service instance."""
    global auth_service
    if auth_service is None:
        auth_service = AuthService(settings)
    return auth_service


async def get_current_user(
    request: Request,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(security)],
    auth: Annotated[AuthService, Depends(get_auth_service)],
) -> User:
    """
    Get the current authenticated user.

    Supports both JWT Bearer tokens and API key authentication.

    Args:
        request: FastAPI request object
        credentials: HTTP authorization credentials
        auth: Authentication service

    Returns:
        Authenticated user object

    Raises:
        HTTPException: If authentication fails
    """
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )

    # Log authentication attempt
    client_ip = request.client.host if request.client else "unknown"
    user_agent = request.headers.get("user-agent", "unknown")

    logger.info(
        "Authentication attempt",
        client_ip=client_ip,
        user_agent=user_agent,
        has_credentials=credentials is not None,
    )

    # Check for API key in headers first
    api_key = request.headers.get("X-API-Key")
    if api_key:
        if auth.verify_api_key(api_key):
            admin_user = User(
                id="admin",
                username="admin",
                email="admin@example.com",
                full_name="Admin User",
                is_admin=True,
                scopes=["admin", "read", "write", "delete"],
                last_login=datetime.now(UTC),
            )

            logger.info(
                "API key authentication successful",
                username="admin",
                client_ip=client_ip,
            )

            return admin_user
        logger.warning("Invalid API key provided", client_ip=client_ip)
        raise credentials_exception

    # Check for JWT Bearer token
    if not credentials:
        logger.warning("No authentication credentials provided", client_ip=client_ip)
        raise credentials_exception

    try:
        token_data = auth.verify_token(credentials.credentials)

        # For demo purposes, create a user from token data
        # In production, this would fetch from a database
        user = User(
            id=token_data.user_id or token_data.username or "unknown",
            username=token_data.username or "unknown",
            email=f"{token_data.username}@example.com",
            scopes=token_data.scopes,
            last_login=datetime.now(UTC),
        )

        logger.info(
            "JWT authentication successful",
            username=user.username,
            user_id=user.id,
            client_ip=client_ip,
            scopes=user.scopes,
        )

        return user

    except HTTPException:
        logger.warning("JWT authentication failed", client_ip=client_ip)
        raise


async def get_current_active_user(
    current_user: Annotated[User, Depends(get_current_user)],
) -> User:
    """
    Get the current active user.

    Args:
        current_user: Current authenticated user

    Returns:
        Active user object

    Raises:
        HTTPException: If user is inactive
    """
    if not current_user.is_active:
        logger.warning(
            "Inactive user attempted access",
            username=current_user.username,
            user_id=current_user.id,
        )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Inactive user"
        )
    return current_user


class RequireScopes:
    """Dependency class for scope-based authorization."""

    def __init__(self, *required_scopes: str) -> None:
        self.required_scopes = required_scopes

    def __call__(
        self, current_user: Annotated[User, Depends(get_current_active_user)]
    ) -> User:
        """
        Check if user has required scopes.

        Args:
            current_user: Current authenticated user

        Returns:
            User if authorized

        Raises:
            HTTPException: If user lacks required scopes
        """
        if not self.required_scopes:
            return current_user

        # Admin users have all scopes
        if current_user.is_admin:
            return current_user

        # Check if user has any of the required scopes
        user_scopes = set(current_user.scopes)
        required_scopes = set(self.required_scopes)

        if not required_scopes.intersection(user_scopes):
            logger.warning(
                "Authorization failed - insufficient scopes",
                username=current_user.username,
                user_id=current_user.id,
                user_scopes=current_user.scopes,
                required_scopes=list(self.required_scopes),
            )
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Operation requires one of: {', '.join(self.required_scopes)}",
            )

        logger.debug(
            "Authorization successful",
            username=current_user.username,
            user_id=current_user.id,
            matched_scopes=list(required_scopes.intersection(user_scopes)),
        )

        return current_user


# Common scope dependencies
require_read = RequireScopes("read", "admin")
require_write = RequireScopes("write", "admin")
require_admin = RequireScopes("admin")


def create_demo_token(
    username: str = "demo_user",
    scopes: list[str] | None = None,
    settings: Settings | None = None,
) -> str:
    """
    Create a demo JWT token for testing.

    Args:
        username: Username for the token
        scopes: List of scopes to include
        settings: Settings instance (optional)

    Returns:
        JWT token string
    """
    if settings is None:
        settings = get_settings()

    if scopes is None:
        scopes = ["read", "write"]

    auth = AuthService(settings)

    token_data = {
        "sub": username,
        "user_id": f"user_{int(time.time())}",
        "scopes": scopes,
    }

    return auth.create_access_token(token_data)


# Rate limiting tracking
class RateLimitTracker:
    """Simple in-memory rate limiting tracker."""

    def __init__(self) -> None:
        self._requests: dict[str, list[float]] = {}

    def is_allowed(self, identifier: str, limit: int, window_seconds: int = 60) -> bool:
        """
        Check if request is allowed under rate limit.

        Args:
            identifier: Client identifier (IP, user ID, etc.)
            limit: Maximum requests per window
            window_seconds: Time window in seconds

        Returns:
            True if request is allowed
        """
        now = time.time()
        window_start = now - window_seconds

        # Clean old requests
        if identifier not in self._requests:
            self._requests[identifier] = []

        # Remove requests outside the window
        self._requests[identifier] = [
            req_time
            for req_time in self._requests[identifier]
            if req_time > window_start
        ]

        # Check if under limit
        if len(self._requests[identifier]) >= limit:
            return False

        # Record this request
        self._requests[identifier].append(now)
        return True


# Global rate limiter instance
rate_limiter = RateLimitTracker()
