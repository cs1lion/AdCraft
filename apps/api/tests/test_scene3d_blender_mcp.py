"""Unit tests for the Blender MCP client.

A scripted fake transport stands in for the stdio server, so the protocol
logic (handshake, tools/list discovery, whitelist enforcement, bbox bounds,
error mapping, capability fingerprinting) is locked without spawning Blender.
The mutation check flips the whitelist expectation and fails, proving it
binds.
"""

from __future__ import annotations

import pytest

from app.core.config import Settings
from app.services.scene3d.blender_mcp_client import (
    BLENDER_MCP_TOOL_WHITELIST,
    BlenderMcpClient,
    BlenderMcpError,
    BlenderMcpCapability,
)


class _FakeTransport:
    """Scripted request/notify transport returning canned JSON-RPC replies."""

    def __init__(self, *, tools: list[str] | None = None, fail_method: str | None = None) -> None:
        self.requests: list[dict] = []
        self.notifications: list[dict] = []
        self._tools = tools if tools is not None else list(BLENDER_MCP_TOOL_WHITELIST)
        self._fail_method = fail_method
        self.closed = False

    def request(self, payload: dict) -> dict:
        self.requests.append(payload)
        method = payload.get("method")
        if self._fail_method == method:
            raise BlenderMcpError("mcp_transport_error", "wire died")
        if method == "initialize":
            return {
                "jsonrpc": "2.0",
                "id": payload["id"],
                "result": {
                    "protocolVersion": "2024-11-05",
                    "serverInfo": {"name": "blender-mcp", "version": "1.2.3"},
                },
            }
        if method == "tools/list":
            return {
                "jsonrpc": "2.0",
                "id": payload["id"],
                "result": {"tools": [{"name": name} for name in self._tools]},
            }
        if method == "tools/call":
            return {
                "jsonrpc": "2.0",
                "id": payload["id"],
                "result": {"content": [{"type": "text", "text": "ok"}], "isError": False},
            }
        return {
            "jsonrpc": "2.0",
            "id": payload["id"],
            "error": {"code": -32601, "message": f"unknown method {method}"},
        }

    def notify(self, payload: dict) -> None:
        self.notifications.append(payload)

    def close(self) -> None:
        self.closed = True


def _client(transport: _FakeTransport) -> BlenderMcpClient:
    return BlenderMcpClient(Settings(agent_runtime_mode="fake"), transport=transport)


def test_handshake_sends_initialize_then_initialized_notification() -> None:
    transport = _FakeTransport()
    client = _client(transport)

    info = client.initialize()

    assert info == {"name": "blender-mcp", "version": "1.2.3"}
    methods = [request["method"] for request in transport.requests]
    assert methods == ["initialize", "tools/list"]
    assert transport.notifications == [
        {"jsonrpc": "2.0", "method": "notifications/initialized"}
    ]


def test_initialize_is_idempotent() -> None:
    transport = _FakeTransport()
    client = _client(transport)
    client.initialize()
    client.initialize()
    assert len([r for r in transport.requests if r["method"] == "initialize"]) == 1


def test_capability_ready_when_full_vocabulary_present() -> None:
    client = _client(_FakeTransport())
    capability = client.capability()
    assert isinstance(capability, BlenderMcpCapability)
    assert capability.state == "ready"
    assert capability.server_name == "blender-mcp"
    assert capability.server_version == "1.2.3"
    assert capability.missing_tools == ()
    assert set(capability.available_tools) == set(BLENDER_MCP_TOOL_WHITELIST)


def test_capability_degraded_reports_missing_tools_never_silently() -> None:
    client = _client(_FakeTransport(tools=["scene_info", "add_primitive", "bevel"]))
    capability = client.capability()
    assert capability.state == "degraded"
    assert "subdivide" in capability.missing_tools
    assert "bevel" in capability.available_tools


def test_capability_unsupported_when_the_wire_dies() -> None:
    transport = _FakeTransport(fail_method="initialize")
    client = _client(transport)
    capability = client.capability()
    assert capability.state == "unsupported"
    assert "wire died" in (capability.error or "")


def test_call_tool_round_trips_a_whitelisted_tool() -> None:
    transport = _FakeTransport()
    client = _client(transport)

    result = client.call_tool("bevel", {"target": "door_1", "width": 0.05})

    assert result["isError"] is False
    call = transport.requests[-1]
    assert call["method"] == "tools/call"
    assert call["params"]["name"] == "bevel"
    assert call["params"]["arguments"] == {"target": "door_1", "width": 0.05}


def test_call_tool_rejects_non_whitelisted_names_before_the_wire() -> None:
    # Mutation-locked: an "execute_python" style tool must never cross.
    transport = _FakeTransport()
    client = _client(transport)

    with pytest.raises(BlenderMcpError) as exc:
        client.call_tool("execute_python", {"code": "import os"})

    assert exc.value.code == "mcp_tool_not_allowed"
    assert not any(request["method"] == "tools/call" for request in transport.requests)


def test_call_tool_rejects_names_the_server_does_not_expose() -> None:
    client = _client(_FakeTransport(tools=["scene_info"]))
    with pytest.raises(BlenderMcpError) as exc:
        client.call_tool("subdivide", {"target": "wall_1"})
    assert exc.value.code == "mcp_tool_unavailable"


def test_call_tool_maps_server_side_tool_errors() -> None:
    class _ErroringTransport(_FakeTransport):
        def request(self, payload: dict) -> dict:
            response = super().request(payload)
            if payload.get("method") == "tools/call":
                response = {
                    "jsonrpc": "2.0",
                    "id": payload["id"],
                    "result": {
                        "content": [{"type": "text", "text": "object 'door_1' not found"}],
                        "isError": True,
                    },
                }
            return response

    client = _client(_ErroringTransport())
    with pytest.raises(BlenderMcpError) as exc:
        client.call_tool("bevel", {"target": "door_1"})
    assert exc.value.code == "mcp_tool_error"
    assert "not found" in str(exc.value)


def test_transform_bounds_enforce_the_scene_bbox() -> None:
    client = _client(_FakeTransport())

    with pytest.raises(BlenderMcpError) as exc:
        client.call_tool("transform_object", {"target": "wall_1", "location": [500, 0, 0]})
    assert exc.value.code == "mcp_transform_out_of_bounds"

    with pytest.raises(BlenderMcpError) as exc:
        client.call_tool("transform_object", {"target": "wall_1", "location": [0, 0, -5]})
    assert exc.value.code == "mcp_transform_out_of_bounds"

    # Within bounds: passes through.
    client.call_tool("transform_object", {"target": "wall_1", "location": [3, 4, 1.5]})


def test_protocol_error_maps_to_coded_failure() -> None:
    class _RejectingTransport(_FakeTransport):
        def request(self, payload: dict) -> dict:
            if payload.get("method") == "tools/call":
                return {
                    "jsonrpc": "2.0",
                    "id": payload["id"],
                    "error": {"code": -32602, "message": "invalid params"},
                }
            return super().request(payload)

    client = _client(_RejectingTransport())
    with pytest.raises(BlenderMcpError) as exc:
        client.call_tool("add_primitive", {"type": "box"})
    assert exc.value.code == "mcp_protocol_error"


def test_close_is_a_noop_for_injected_transports() -> None:
    transport = _FakeTransport()
    client = _client(transport)
    client.close()
    # The client only closes transports it owns (spawned itself).
    assert transport.closed is False
