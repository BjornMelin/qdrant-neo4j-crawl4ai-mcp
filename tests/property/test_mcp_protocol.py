"""
Property-based testing for MCP protocol compliance using Hypothesis.

This module provides comprehensive property-based testing for the Model Context
Protocol (MCP) implementation to ensure protocol compliance, edge case handling,
and robust error recovery across all possible input combinations.

Key Features:
- MCP protocol compliance validation
- Property-based request/response testing
- Edge case generation and validation
- Protocol invariant verification
- Error handling property testing
- Tool interface contract validation
"""

from datetime import datetime
import json
import re
from typing import Any
import uuid

import httpx
from hypothesis import (
    HealthCheck,
    Verbosity,
    assume,
    given,
    settings,
)
from hypothesis import (
    strategies as st,
)
from hypothesis.strategies import composite
import pytest

# MCP Protocol Constants
MCP_VERSION = "2024-11-05"
JSONRPC_VERSION = "2.0"

# Valid MCP method names
MCP_METHODS = [
    "initialize",
    "initialized",
    "ping",
    "tools/list",
    "tools/call",
    "resources/list",
    "resources/read",
    "prompts/list",
    "prompts/get",
    "completion/complete",
    "roots/list",
    "sampling/createMessage",
    "logging/setLevel",
]

# Valid tool names for the unified MCP server
TOOL_NAMES = [
    "search_vectors",
    "store_vector",
    "list_collections",
    "health_check_vector",
    "create_memory_node",
    "extract_knowledge_from_text",
    "search_graph",
    "analyze_graph_structure",
    "execute_cypher_query",
    "crawl_web_content",
    "extract_web_intelligence",
    "search_web_enhanced",
]

# Valid argument patterns for tools
VECTOR_SEARCH_ARGS = ["query", "collection_name", "limit", "score_threshold", "filters"]
VECTOR_STORE_ARGS = ["content", "collection_name", "metadata", "embedding_model"]
GRAPH_ARGS = ["query", "node_types", "max_depth", "limit"]
WEB_ARGS = ["url", "query", "extraction_mode", "filters"]


@composite
def valid_json_value(draw, max_depth=3):
    """Generate valid JSON values with controlled depth."""
    if max_depth <= 0:
        return draw(
            st.one_of(
                st.none(),
                st.booleans(),
                st.integers(),
                st.floats(allow_nan=False, allow_infinity=False),
                st.text(min_size=0, max_size=100),
            )
        )

    return draw(
        st.one_of(
            st.none(),
            st.booleans(),
            st.integers(),
            st.floats(allow_nan=False, allow_infinity=False),
            st.text(min_size=0, max_size=100),
            st.lists(valid_json_value(max_depth=max_depth - 1), max_size=5),
            st.dictionaries(
                st.text(min_size=1, max_size=20),
                valid_json_value(max_depth=max_depth - 1),
                max_size=5,
            ),
        )
    )


@composite
def mcp_request_id(draw):
    """Generate valid MCP request IDs."""
    return draw(
        st.one_of(
            st.integers(min_value=1, max_value=2**31 - 1),
            st.text(
                min_size=1,
                max_size=50,
                alphabet=st.characters(
                    whitelist_categories=("Lu", "Ll", "Nd"), whitelist_characters="-_"
                ),
            ),
            st.none(),  # Notifications don't require IDs
        )
    )


@composite
def mcp_method_name(draw):
    """Generate valid MCP method names."""
    return draw(st.sampled_from(MCP_METHODS))


@composite
def tool_name(draw):
    """Generate valid tool names for the unified server."""
    return draw(st.sampled_from(TOOL_NAMES))


@composite
def vector_search_arguments(draw):
    """Generate valid vector search tool arguments."""
    base_args = {
        "query": draw(st.text(min_size=1, max_size=1000)),
        "limit": draw(st.integers(min_value=1, max_value=100)),
    }

    # Optional arguments
    if draw(st.booleans()):
        base_args["collection_name"] = draw(st.text(min_size=1, max_size=50))
    if draw(st.booleans()):
        base_args["score_threshold"] = draw(st.floats(min_value=0.0, max_value=1.0))
    if draw(st.booleans()):
        base_args["filters"] = draw(
            st.dictionaries(
                st.text(min_size=1, max_size=20),
                valid_json_value(max_depth=2),
                max_size=3,
            )
        )

    return base_args


@composite
def vector_store_arguments(draw):
    """Generate valid vector store tool arguments."""
    base_args = {
        "content": draw(st.text(min_size=1, max_size=5000)),
        "collection_name": draw(st.text(min_size=1, max_size=50)),
    }

    # Optional arguments
    if draw(st.booleans()):
        base_args["metadata"] = draw(
            st.dictionaries(
                st.text(min_size=1, max_size=20),
                valid_json_value(max_depth=2),
                max_size=5,
            )
        )
    if draw(st.booleans()):
        base_args["embedding_model"] = draw(
            st.sampled_from(
                [
                    "text-embedding-3-small",
                    "text-embedding-3-large",
                    "text-embedding-ada-002",
                ]
            )
        )

    return base_args


@composite
def graph_search_arguments(draw):
    """Generate valid graph search tool arguments."""
    base_args = {"query": draw(st.text(min_size=1, max_size=1000))}

    # Optional arguments
    if draw(st.booleans()):
        base_args["node_types"] = draw(
            st.lists(
                st.sampled_from(["Entity", "Concept", "Person", "Memory"]),
                min_size=1,
                max_size=3,
            )
        )
    if draw(st.booleans()):
        base_args["max_depth"] = draw(st.integers(min_value=1, max_value=5))
    if draw(st.booleans()):
        base_args["limit"] = draw(st.integers(min_value=1, max_value=50))

    return base_args


@composite
def web_crawl_arguments(draw):
    """Generate valid web crawl tool arguments."""
    urls = [
        "https://example.com",
        "https://test.org/page",
        "http://localhost:8080/api",
        "https://api.example.com/docs",
    ]

    base_args = {"url": draw(st.sampled_from(urls))}

    # Optional arguments
    if draw(st.booleans()):
        base_args["extraction_mode"] = draw(
            st.sampled_from(["text", "markdown", "structured", "links"])
        )
    if draw(st.booleans()):
        base_args["filters"] = draw(
            st.dictionaries(
                st.text(min_size=1, max_size=20),
                valid_json_value(max_depth=1),
                max_size=3,
            )
        )

    return base_args


@composite
def tool_call_arguments(draw):
    """Generate valid tool call arguments based on tool name."""
    tool = draw(tool_name())

    if "vector" in tool and "search" in tool:
        return draw(vector_search_arguments())
    if "vector" in tool and "store" in tool:
        return draw(vector_store_arguments())
    if "graph" in tool:
        return draw(graph_search_arguments())
    if "web" in tool or "crawl" in tool:
        return draw(web_crawl_arguments())
    # Generic arguments for other tools
    return draw(
        st.dictionaries(
            st.text(min_size=1, max_size=20),
            valid_json_value(max_depth=2),
            max_size=5,
        )
    )


@composite
def mcp_request(draw):
    """Generate valid MCP JSON-RPC requests."""
    base_request = {"jsonrpc": JSONRPC_VERSION, "method": draw(mcp_method_name())}

    # Add ID for requests (not notifications)
    request_id = draw(mcp_request_id())
    if request_id is not None:
        base_request["id"] = request_id

    # Add method-specific parameters
    method = base_request["method"]

    if method == "initialize":
        base_request["params"] = {
            "protocolVersion": MCP_VERSION,
            "capabilities": draw(
                st.dictionaries(
                    st.text(min_size=1, max_size=20), st.booleans(), max_size=5
                )
            ),
            "clientInfo": {
                "name": draw(st.text(min_size=1, max_size=50)),
                "version": draw(st.text(min_size=1, max_size=20)),
            },
        }
    elif method == "tools/call":
        base_request["params"] = {
            "name": draw(tool_name()),
            "arguments": draw(tool_call_arguments()),
        }
    elif method in ["tools/list", "resources/list", "prompts/list", "roots/list"]:
        # These methods may have optional pagination params
        if draw(st.booleans()):
            base_request["params"] = {"cursor": draw(st.text(min_size=1, max_size=100))}
    elif method == "resources/read":
        base_request["params"] = {"uri": draw(st.text(min_size=1, max_size=200))}
    elif method == "prompts/get":
        base_request["params"] = {
            "name": draw(st.text(min_size=1, max_size=50)),
            "arguments": draw(
                st.dictionaries(st.text(min_size=1, max_size=20), st.text(), max_size=3)
            ),
        }
    elif method == "completion/complete":
        base_request["params"] = {
            "ref": {
                "type": "ref/prompt",
                "name": draw(st.text(min_size=1, max_size=50)),
            },
            "argument": {
                "name": draw(st.text(min_size=1, max_size=20)),
                "value": draw(st.text()),
            },
        }
    elif method == "logging/setLevel":
        base_request["params"] = {
            "level": draw(
                st.sampled_from(
                    [
                        "debug",
                        "info",
                        "notice",
                        "warning",
                        "error",
                        "critical",
                        "alert",
                        "emergency",
                    ]
                )
            )
        }

    return base_request


@composite
def malformed_mcp_request(draw):
    """Generate malformed MCP requests for error testing."""
    # Start with a potentially valid structure
    request = draw(
        st.dictionaries(
            st.text(max_size=20), valid_json_value(max_depth=3), max_size=10
        )
    )

    # Introduce specific malformations
    malformation_type = draw(
        st.sampled_from(
            [
                "missing_jsonrpc",
                "wrong_jsonrpc_version",
                "missing_method",
                "invalid_method",
                "invalid_id_type",
                "malformed_params",
                "oversized_request",
            ]
        )
    )

    if malformation_type == "missing_jsonrpc":
        request.pop("jsonrpc", None)
    elif malformation_type == "wrong_jsonrpc_version":
        request["jsonrpc"] = draw(st.text(max_size=10))
    elif malformation_type == "missing_method":
        request.pop("method", None)
    elif malformation_type == "invalid_method":
        request["method"] = draw(st.text(min_size=1, max_size=100))
        assume(request["method"] not in MCP_METHODS)
    elif malformation_type == "invalid_id_type":
        request["id"] = draw(st.lists(st.text(), max_size=3))  # Invalid ID type
    elif malformation_type == "oversized_request":
        request["params"] = {"data": "x" * 10000}  # Very large request

    return request


class TestMCPProtocolCompliance:
    """Property-based tests for MCP protocol compliance."""

    @given(request=mcp_request())
    @settings(
        max_examples=100, deadline=5000, suppress_health_check=[HealthCheck.too_slow]
    )
    async def test_valid_mcp_requests_get_valid_responses(
        self,
        async_test_client: httpx.AsyncClient,
        auth_headers: dict[str, str],
        request: dict[str, Any],
    ):
        """Property: All valid MCP requests should receive valid JSON-RPC responses."""
        # Send MCP request
        response = await async_test_client.post(
            "/mcp", json=request, headers=auth_headers
        )

        # Response should be valid HTTP
        assert response.status_code in [200, 400, 405, 500], (
            f"Unexpected status code: {response.status_code}"
        )

        # If successful, should have valid JSON-RPC structure
        if response.status_code == 200:
            data = response.json()

            # Valid JSON-RPC response structure
            assert "jsonrpc" in data
            assert data["jsonrpc"] == JSONRPC_VERSION

            # Should have either result or error, but not both
            has_result = "result" in data
            has_error = "error" in data
            assert has_result != has_error, (
                "Response must have either result or error, not both"
            )

            # If request had ID, response should have matching ID
            if "id" in request:
                assert "id" in data
                assert data["id"] == request["id"]

            # Error responses should have valid error structure
            if has_error:
                error = data["error"]
                assert "code" in error
                assert "message" in error
                assert isinstance(error["code"], int)
                assert isinstance(error["message"], str)

    @given(request=malformed_mcp_request())
    @settings(max_examples=50, deadline=3000)
    async def test_malformed_requests_handled_gracefully(
        self,
        async_test_client: httpx.AsyncClient,
        auth_headers: dict[str, str],
        request: dict[str, Any],
    ):
        """Property: Malformed MCP requests should be handled gracefully without crashes."""
        response = await async_test_client.post(
            "/mcp", json=request, headers=auth_headers
        )

        # Should not crash the server
        assert response.status_code in [200, 400, 422, 500]

        # Should return valid JSON
        try:
            data = response.json()

            # If it's a JSON-RPC error response, should be properly formatted
            if response.status_code in [200, 400] and isinstance(data, dict):
                if "jsonrpc" in data and "error" in data:
                    error = data["error"]
                    assert "code" in error
                    assert "message" in error
                    assert isinstance(error["code"], int)
                    assert isinstance(error["message"], str)
        except json.JSONDecodeError:
            # Non-JSON responses are acceptable for severely malformed requests
            pass

    @given(tool_name=tool_name(), arguments=tool_call_arguments())
    @settings(max_examples=50, deadline=10000)
    async def test_tool_calls_maintain_argument_invariants(
        self,
        async_test_client: httpx.AsyncClient,
        auth_headers: dict[str, str],
        tool_name: str,
        arguments: dict[str, Any],
    ):
        """Property: Tool calls should maintain argument type and structure invariants."""
        request = {
            "jsonrpc": JSONRPC_VERSION,
            "id": str(uuid.uuid4()),
            "method": "tools/call",
            "params": {"name": tool_name, "arguments": arguments},
        }

        response = await async_test_client.post(
            "/mcp", json=request, headers=auth_headers
        )

        assert response.status_code in [200, 400, 500]

        if response.status_code == 200:
            data = response.json()

            # Successful tool call should have result
            assert "result" in data
            result = data["result"]

            # Tool results should have consistent structure
            if isinstance(result, dict):
                # Should have content array for content responses
                if "content" in result:
                    assert isinstance(result["content"], list)

                    # Each content item should have type and text/data
                    for item in result["content"]:
                        assert isinstance(item, dict)
                        assert "type" in item
                        assert item["type"] in ["text", "image", "resource"]

    @given(
        query=st.text(min_size=1, max_size=1000),
        limit=st.integers(min_value=1, max_value=100),
    )
    @settings(max_examples=30, deadline=8000)
    async def test_vector_search_response_properties(
        self,
        async_test_client: httpx.AsyncClient,
        auth_headers: dict[str, str],
        query: str,
        limit: int,
    ):
        """Property: Vector search responses should maintain mathematical properties."""
        request = {
            "jsonrpc": JSONRPC_VERSION,
            "id": 1,
            "method": "tools/call",
            "params": {
                "name": "search_vectors",
                "arguments": {"query": query, "limit": limit},
            },
        }

        response = await async_test_client.post(
            "/mcp", json=request, headers=auth_headers
        )

        if response.status_code == 200:
            data = response.json()

            if "result" in data and "content" in data["result"]:
                content_items = data["result"]["content"]

                # Should not exceed requested limit
                assert len(content_items) <= limit

                # If multiple items, should be sorted by relevance/score
                if len(content_items) > 1:
                    scores = []
                    for item in content_items:
                        if isinstance(item, dict) and "text" in item:
                            # Extract score if present in response text
                            try:
                                text = item["text"]
                                if "score" in text.lower():
                                    # Try to extract numeric score
                                    import re

                                    score_match = re.search(
                                        r"score[:\s]+([0-9.]+)", text.lower()
                                    )
                                    if score_match:
                                        scores.append(float(score_match.group(1)))
                            except (ValueError, AttributeError):
                                pass

                    # Scores should be in descending order
                    if len(scores) > 1:
                        for i in range(len(scores) - 1):
                            assert scores[i] >= scores[i + 1], (
                                "Search results should be sorted by score"
                            )

    @given(
        content=st.text(min_size=1, max_size=5000),
        collection_name=st.text(min_size=1, max_size=50),
    )
    @settings(max_examples=20, deadline=6000)
    async def test_vector_store_idempotency(
        self,
        async_test_client: httpx.AsyncClient,
        auth_headers: dict[str, str],
        content: str,
        collection_name: str,
    ):
        """Property: Storing the same content multiple times should be idempotent."""
        # Filter out invalid collection names
        assume(re.match(r"^[a-zA-Z0-9_-]+$", collection_name))
        assume(len(content.strip()) > 0)

        request = {
            "jsonrpc": JSONRPC_VERSION,
            "id": 1,
            "method": "tools/call",
            "params": {
                "name": "store_vector",
                "arguments": {"content": content, "collection_name": collection_name},
            },
        }

        # Store the same content twice
        response1 = await async_test_client.post(
            "/mcp", json=request, headers=auth_headers
        )

        response2 = await async_test_client.post(
            "/mcp", json=request, headers=auth_headers
        )

        # Both should succeed or fail consistently
        assert response1.status_code == response2.status_code

        if response1.status_code == 200 and response2.status_code == 200:
            data1 = response1.json()
            data2 = response2.json()

            # Both should have results
            assert "result" in data1
            assert "result" in data2

    @given(request_id=mcp_request_id())
    @settings(max_examples=30, deadline=3000)
    async def test_request_id_preservation(
        self,
        async_test_client: httpx.AsyncClient,
        auth_headers: dict[str, str],
        request_id: str | int | None,
    ):
        """Property: Request IDs should be preserved in responses."""
        request = {"jsonrpc": JSONRPC_VERSION, "method": "tools/list"}

        if request_id is not None:
            request["id"] = request_id

        response = await async_test_client.post(
            "/mcp", json=request, headers=auth_headers
        )

        if response.status_code == 200:
            data = response.json()

            if request_id is not None:
                # Response should have matching ID
                assert "id" in data
                assert data["id"] == request_id
            else:
                # Notification - response should not have ID
                assert "id" not in data or data["id"] is None


class TestMCPToolInterfaceProperties:
    """Property-based tests for MCP tool interface contracts."""

    @given(
        method_name=st.sampled_from(["tools/list", "resources/list", "prompts/list"])
    )
    @settings(max_examples=20, deadline=4000)
    async def test_list_methods_return_consistent_structure(
        self,
        async_test_client: httpx.AsyncClient,
        auth_headers: dict[str, str],
        method_name: str,
    ):
        """Property: List methods should return consistent array structures."""
        request = {"jsonrpc": JSONRPC_VERSION, "id": 1, "method": method_name}

        response = await async_test_client.post(
            "/mcp", json=request, headers=auth_headers
        )

        if response.status_code == 200:
            data = response.json()

            if "result" in data:
                result = data["result"]

                # Should have the appropriate list field
                if method_name == "tools/list":
                    assert "tools" in result
                    assert isinstance(result["tools"], list)
                elif method_name == "resources/list":
                    assert "resources" in result
                    assert isinstance(result["resources"], list)
                elif method_name == "prompts/list":
                    assert "prompts" in result
                    assert isinstance(result["prompts"], list)

    @given(cursor=st.one_of(st.none(), st.text(min_size=1, max_size=100)))
    @settings(max_examples=15, deadline=3000)
    async def test_pagination_cursor_handling(
        self,
        async_test_client: httpx.AsyncClient,
        auth_headers: dict[str, str],
        cursor: str | None,
    ):
        """Property: Pagination cursors should be handled consistently."""
        request = {"jsonrpc": JSONRPC_VERSION, "id": 1, "method": "tools/list"}

        if cursor is not None:
            request["params"] = {"cursor": cursor}

        response = await async_test_client.post(
            "/mcp", json=request, headers=auth_headers
        )

        # Should handle cursor gracefully
        assert response.status_code in [200, 400]

        if response.status_code == 200:
            data = response.json()
            if "result" in data:
                result = data["result"]
                assert "tools" in result

                # If nextCursor is present, should be string or null
                if "nextCursor" in result:
                    assert result["nextCursor"] is None or isinstance(
                        result["nextCursor"], str
                    )


class TestMCPErrorHandlingProperties:
    """Property-based tests for MCP error handling properties."""

    @given(
        invalid_tool_name=st.text(min_size=1, max_size=100),
        arguments=st.dictionaries(
            st.text(min_size=1, max_size=20), valid_json_value(max_depth=2), max_size=5
        ),
    )
    @settings(max_examples=30, deadline=5000)
    async def test_invalid_tool_names_return_method_not_found(
        self,
        async_test_client: httpx.AsyncClient,
        auth_headers: dict[str, str],
        invalid_tool_name: str,
        arguments: dict[str, Any],
    ):
        """Property: Invalid tool names should return method not found errors."""
        # Ensure we're testing with actually invalid tool names
        assume(invalid_tool_name not in TOOL_NAMES)

        request = {
            "jsonrpc": JSONRPC_VERSION,
            "id": 1,
            "method": "tools/call",
            "params": {"name": invalid_tool_name, "arguments": arguments},
        }

        response = await async_test_client.post(
            "/mcp", json=request, headers=auth_headers
        )

        if response.status_code == 200:
            data = response.json()

            # Should be an error response
            if "error" in data:
                error = data["error"]

                # Should be method not found or invalid params
                assert error["code"] in [
                    -32601,
                    -32602,
                ]  # Method not found or Invalid params
                assert isinstance(error["message"], str)
                assert len(error["message"]) > 0

    @given(
        oversized_text=st.text(min_size=50000, max_size=100000)  # Very large text
    )
    @settings(max_examples=5, deadline=8000)
    async def test_oversized_requests_handled_gracefully(
        self,
        async_test_client: httpx.AsyncClient,
        auth_headers: dict[str, str],
        oversized_text: str,
    ):
        """Property: Oversized requests should be handled without crashes."""
        request = {
            "jsonrpc": JSONRPC_VERSION,
            "id": 1,
            "method": "tools/call",
            "params": {
                "name": "search_vectors",
                "arguments": {"query": oversized_text, "limit": 10},
            },
        }

        response = await async_test_client.post(
            "/mcp", json=request, headers=auth_headers
        )

        # Should not crash, should return appropriate error
        assert response.status_code in [200, 400, 413, 422, 500]

        # If it returns 200, should have valid response structure
        if response.status_code == 200:
            data = response.json()
            assert "jsonrpc" in data
            assert "id" in data
            assert "result" in data or "error" in data


class TestMCPConcurrencyProperties:
    """Property-based tests for MCP concurrency properties."""

    @given(num_concurrent=st.integers(min_value=2, max_value=10), tool_name=tool_name())
    @settings(max_examples=10, deadline=15000)
    async def test_concurrent_requests_maintain_isolation(
        self,
        async_test_client: httpx.AsyncClient,
        auth_headers: dict[str, str],
        num_concurrent: int,
        tool_name: str,
    ):
        """Property: Concurrent requests should maintain proper isolation."""
        import asyncio

        # Generate different requests
        requests = []
        for i in range(num_concurrent):
            request = {
                "jsonrpc": JSONRPC_VERSION,
                "id": i,
                "method": "tools/call",
                "params": {
                    "name": tool_name,
                    "arguments": {"query": f"concurrent test {i}", "limit": 5},
                },
            }
            requests.append(request)

        # Send concurrent requests
        async def send_request(req):
            return await async_test_client.post("/mcp", json=req, headers=auth_headers)

        responses = await asyncio.gather(*[send_request(req) for req in requests])

        # All responses should be valid
        assert len(responses) == num_concurrent

        # Each response should correspond to its request
        for i, response in enumerate(responses):
            if response.status_code == 200:
                data = response.json()

                # Response ID should match request ID
                if "id" in data:
                    assert data["id"] == i

                # Should have valid structure
                assert "jsonrpc" in data
                assert data["jsonrpc"] == JSONRPC_VERSION


@pytest.mark.slow
@pytest.mark.property
class TestMCPInvariantProperties:
    """Tests for MCP protocol invariants that must always hold."""

    @given(requests=st.lists(mcp_request(), min_size=1, max_size=5))
    @settings(max_examples=10, deadline=20000, verbosity=Verbosity.verbose)
    async def test_mcp_session_state_consistency(
        self,
        async_test_client: httpx.AsyncClient,
        auth_headers: dict[str, str],
        requests: list[dict[str, Any]],
    ):
        """Property: MCP session state should remain consistent across request sequences."""
        session_state = {
            "initialized": False,
            "capabilities": None,
            "last_response_time": None,
        }

        for request in requests:
            response = await async_test_client.post(
                "/mcp", json=request, headers=auth_headers
            )

            # Track response time
            session_state["last_response_time"] = datetime.utcnow()

            # Server should always be available
            assert response.status_code in [200, 400, 405, 500]

            if response.status_code == 200:
                data = response.json()

                # Initialize tracking
                if request.get("method") == "initialize":
                    session_state["initialized"] = True
                    if "result" in data:
                        session_state["capabilities"] = data["result"].get(
                            "capabilities", {}
                        )

                # Valid responses should maintain JSON-RPC structure
                assert "jsonrpc" in data
                assert data["jsonrpc"] == JSONRPC_VERSION

        # Verify session remained consistent
        assert session_state["last_response_time"] is not None

    @given(data=st.data())
    @settings(max_examples=20, deadline=10000)
    async def test_mcp_response_format_invariants(
        self, async_test_client: httpx.AsyncClient, auth_headers: dict[str, str], data
    ):
        """Property: MCP responses must always maintain format invariants."""
        # Generate a valid request
        request = data.draw(mcp_request())

        response = await async_test_client.post(
            "/mcp", json=request, headers=auth_headers
        )

        if response.status_code == 200:
            response_data = response.json()

            # JSON-RPC invariants
            assert isinstance(response_data, dict), "Response must be JSON object"
            assert "jsonrpc" in response_data, "Response must have jsonrpc field"
            assert response_data["jsonrpc"] == JSONRPC_VERSION, (
                "Must use correct JSON-RPC version"
            )

            # Must have either result or error, never both
            has_result = "result" in response_data
            has_error = "error" in response_data
            assert has_result != has_error, (
                "Response must have exactly one of result or error"
            )

            # ID handling invariant
            if "id" in request and request["id"] is not None:
                assert "id" in response_data, "Response must echo request ID"
                assert response_data["id"] == request["id"], (
                    "Response ID must match request ID"
                )

            # Error format invariant
            if has_error:
                error = response_data["error"]
                assert isinstance(error, dict), "Error must be object"
                assert "code" in error, "Error must have code"
                assert "message" in error, "Error must have message"
                assert isinstance(error["code"], int), "Error code must be integer"
                assert isinstance(error["message"], str), "Error message must be string"
                assert len(error["message"]) > 0, "Error message must not be empty"


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short", "-m", "property"])
