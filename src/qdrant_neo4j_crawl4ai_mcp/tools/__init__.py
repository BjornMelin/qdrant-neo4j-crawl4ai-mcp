"""
MCP tools for the Unified MCP Intelligence Server.

This package contains FastMCP tools that provide MCP-compatible interfaces
to the underlying services for external systems integration.
"""

from .vector_tools import register_vector_tools

__all__ = [
    "register_vector_tools",
]
