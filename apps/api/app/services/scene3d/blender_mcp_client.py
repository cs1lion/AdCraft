"""Blender MCP client for the white-model design mode.

Model Context Protocol (stdio JSON-RPC 2.0) client that lets the agent drive
a Blender MCP server for geometry operations beyond the SceneScript primitive
vocabulary (bevel/subdivide/boolean/...). SceneScript stays the canonical
state: every MCP call is an extension op the caller maps back onto the script
(see docs/plans/blender-mcp-white-model-mode-and-audio-collaboration.md §1).

Safety boundary — the client enforces a tool whitelist. Arbitrary code
execution through Blender's Python is the obvious footgun of "let the agent
drive Blender"; only named geometry/preview tools may cross the wire.
Anything else fails locally with ``mcp_tool_not_allowed`` and is never sent.

Transport is a Protocol (stdio subprocess by default) so the protocol logic
is unit-testable without spawning a real server.
"""

from __future__ import annotations

import json
import os
import subprocess
from dataclasses import dataclass
from typing import Any, Protocol

from app.core.config import Settings


class BlenderMcpError(RuntimeError):
    """Raised when an MCP interaction fails (spawn/init/call/timeout)."""

    def __init__(self, code: str, message: str, *, metadata: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.metadata = metadata or {}


class McpTransport(Protocol):
    """The wire: request/response JSON-RPC over some channel."""

    def request(self, payload: dict[str, Any]) -> dict[str, Any]: ...

    def notify(self, payload: dict[str, Any]) -> None: ...

    def close(self) -> None: ...


# The whitelisted modeling vocabulary. Read-only probes plus the geometry ops
# the white-model mode needs; render_video is deliberately NOT here (the
# canonical path stays the Blender headless renderer via SceneScript).
BLENDER_MCP_TOOL_WHITELIST: tuple[str, ...] = (
    "scene_info",
    "list_objects",
    "add_primitive",
    "transform_object",
    "set_camera",
    "add_keyframe",
    "remove_keyframe",
    "bevel",
    "subdivide",
    "boolean_union",
    "boolean_difference",
    "render_preview",
)

# Bounds enforced client-side for transform ops: |x, y| <= 50 m, 0 <= z <= 30 m.
BBOX_HALF_EXTENT = 50.0
BBOX_MAX_HEIGHT = 30.0


@dataclass(frozen=True)
class BlenderMcpCapability:
    """Availability fingerprint for the white-model design mode."""

    state: str  # ready | degraded | unsupported
    server_name: str | None = None
    server_version: str | None = None
    available_tools: tuple[str, ...] = ()
    missing_tools: tuple[str, ...] = ()
    error: str | None = None

    @property
    def ready(self) -> bool:
        return self.state == "ready"


class StdioMcpTransport:
    """MCP over a child process's stdin/stdout (newline-delimited JSON)."""

    def __init__(self, command: list[str], timeout_seconds: float = 30.0) -> None:
        try:
            self._process = subprocess.Popen(
                command,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                text=True,
                encoding="utf-8",
                errors="replace",
            )
        except (OSError, ValueError) as exc:
            raise BlenderMcpError(
                "mcp_server_spawn_failed",
                f"Could not start the Blender MCP server ({' '.join(command)}): {exc}",
            ) from exc
        self._timeout = timeout_seconds

    def request(self, payload: dict[str, Any]) -> dict[str, Any]:
        if self._process.stdin is None or self._process.stdout is None:
            raise BlenderMcpError("mcp_transport_closed", "The MCP transport is closed.")
        line = json.dumps(payload, ensure_ascii=False)
        try:
            self._process.stdin.write(line + "\n")
            self._process.stdin.flush()
            response_line = self._process.stdout.readline()
        except (OSError, ValueError) as exc:
            raise BlenderMcpError(
                "mcp_transport_error", f"MCP transport failed: {exc}"
            ) from exc
        if not response_line:
            raise BlenderMcpError(
                "mcp_server_closed_stream",
                "The Blender MCP server closed its stdout without a response.",
            )
        try:
            return json.loads(response_line)
        except json.JSONDecodeError as exc:
            raise BlenderMcpError(
                "mcp_protocol_invalid",
                f"The MCP server returned non-JSON output: {response_line[:200]}",
            ) from exc

    def notify(self, payload: dict[str, Any]) -> None:
        if self._process.stdin is None:
            return
        try:
            self._process.stdin.write(json.dumps(payload, ensure_ascii=False) + "\n")
            self._process.stdin.flush()
        except (OSError, ValueError):
            # A failed notification must not kill an in-flight request.
            pass

    def close(self) -> None:
        process = getattr(self, "_process", None)
        if process is None:
            return
        try:
            if process.stdin is not None:
                process.stdin.close()
        except OSError:
            pass
        try:
            process.terminate()
            process.wait(timeout=self._timeout)
        except (OSError, subprocess.TimeoutExpired):
            try:
                process.kill()
            except OSError:
                pass


class BlenderMcpClient:
    """Drives a Blender MCP server through the whitelisted tool vocabulary."""

    def __init__(
        self,
        settings: Settings,
        *,
        transport: McpTransport | None = None,
        command: list[str] | None = None,
    ) -> None:
        self._settings = settings
        self._owns_transport = transport is None
        self._transport = transport or StdioMcpTransport(
            command or self._command_from_settings(),
            timeout_seconds=settings.blender_mcp_timeout_seconds,
        )
        self._initialized = False
        self._request_id = 0
        self._server_info: dict[str, Any] = {}
        self._tools: tuple[str, ...] = ()

    # -- lifecycle ------------------------------------------------------------

    def _command_from_settings(self) -> list[str]:
        raw = str(settings_command(self._settings) or "blender-mcp").strip()
        # A simple shell-ish split is enough: the command is deployment
        # configuration, not user input.
        return raw.split()

    def initialize(self) -> dict[str, Any]:
        """MCP handshake. Idempotent; returns the server info."""

        if self._initialized:
            return self._server_info
        response = self._request(
            "initialize",
            {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "adcraft-scene3d", "version": "1.0.0"},
            },
        )
        result = response.get("result") or {}
        self._server_info = result.get("serverInfo") or {}
        self._transport.notify({"jsonrpc": "2.0", "method": "notifications/initialized"})
        # Discover tools for the capability fingerprint.
        try:
            listed = self._request("tools/list", {})
            tools = (listed.get("result") or {}).get("tools") or []
            self._tools = tuple(
                str(tool.get("name"))
                for tool in tools
                if isinstance(tool, dict) and tool.get("name")
            )
        except BlenderMcpError:
            # A server without tools/list still answers calls; the capability
            # fingerprint reports the gap instead of failing the handshake.
            self._tools = ()
        self._initialized = True
        return self._server_info

    def close(self) -> None:
        if self._owns_transport:
            self._transport.close()

    def __enter__(self) -> "BlenderMcpClient":
        return self

    def __exit__(self, *_exc_info: object) -> None:
        self.close()

    # -- capability -----------------------------------------------------------

    def capability(self) -> BlenderMcpCapability:
        """Probe the server and fingerprint the whitelisted vocabulary.

        ``ready`` — server up and every whitelisted tool present.
        ``degraded`` — server up but part of the vocabulary is missing (the
        caller may still use the available subset; reported, never silent).
        ``unsupported`` — spawn/init failed.
        """

        try:
            info = self.initialize()
        except BlenderMcpError as exc:
            return BlenderMcpCapability(state="unsupported", error=str(exc))
        available = tuple(tool for tool in self._tools if tool in BLENDER_MCP_TOOL_WHITELIST)
        missing = tuple(tool for tool in BLENDER_MCP_TOOL_WHITELIST if tool not in self._tools)
        if self._tools and not missing:
            state = "ready"
        elif available:
            state = "degraded"
        else:
            state = "degraded" if self._tools else "unsupported"
        return BlenderMcpCapability(
            state=state,
            server_name=str(info.get("name")) if info.get("name") else None,
            server_version=str(info.get("version")) if info.get("version") else None,
            available_tools=available,
            missing_tools=missing,
        )

    # -- calls ----------------------------------------------------------------

    def call_tool(self, name: str, arguments: dict[str, Any] | None = None) -> dict[str, Any]:
        """Call a whitelisted tool.

        The whitelist is enforced HERE, before the wire: a non-whitelisted
        name (or one this server does not expose) fails locally.
        """

        if name not in BLENDER_MCP_TOOL_WHITELIST:
            raise BlenderMcpError(
                "mcp_tool_not_allowed",
                f"Tool '{name}' is not in the Blender MCP whitelist "
                f"({', '.join(BLENDER_MCP_TOOL_WHITELIST)}).",
            )
        self.initialize()
        if self._tools and name not in self._tools:
            raise BlenderMcpError(
                "mcp_tool_unavailable",
                f"The Blender MCP server does not expose '{name}'.",
            )
        _enforce_transform_bounds(name, arguments or {})
        response = self._request("tools/call", {"name": name, "arguments": arguments or {}})
        result = response.get("result") or {}
        if result.get("isError"):
            content = result.get("content") or []
            message = content[0].get("text", "unknown MCP tool error") if content else "unknown MCP tool error"
            raise BlenderMcpError("mcp_tool_error", str(message))
        return result

    # -- wire -----------------------------------------------------------------

    def _request(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        self._request_id += 1
        payload = {
            "jsonrpc": "2.0",
            "id": self._request_id,
            "method": method,
            "params": params,
        }
        response = self._transport.request(payload)
        if "error" in response:
            error = response.get("error") or {}
            raise BlenderMcpError(
                "mcp_protocol_error",
                f"MCP server rejected {method}: {error.get('message', response)}",
                metadata={"code": error.get("code")},
            )
        if "result" not in response:
            raise BlenderMcpError(
                "mcp_protocol_invalid",
                f"MCP server response to {method} carried no result.",
            )
        return response


def settings_command(settings: Settings) -> str:
    return str(getattr(settings, "blender_mcp_command", "") or "")


def _enforce_transform_bounds(name: str, arguments: dict[str, Any]) -> None:
    """Client-side bbox for transform ops: a runaway agent must not move
    geometry 10 km away (or below the floor)."""

    if name not in {"transform_object", "set_camera", "add_primitive"}:
        return
    location = arguments.get("location") or arguments.get("position")
    if not isinstance(location, (list, tuple)) or len(location) != 3:
        return
    try:
        x, y, z = (float(value) for value in location)
    except (TypeError, ValueError):
        return
    if abs(x) > BBOX_HALF_EXTENT or abs(y) > BBOX_HALF_EXTENT or not 0 <= z <= BBOX_MAX_HEIGHT:
        raise BlenderMcpError(
            "mcp_transform_out_of_bounds",
            f"MCP transform location {[x, y, z]} is outside the allowed scene bounds "
            f"(|x,y| <= {BBOX_HALF_EXTENT}m, 0 <= z <= {BBOX_MAX_HEIGHT}m).",
        )


def resolve_blender_mcp_command() -> list[str]:
    """The default server command: env override, else ``blender-mcp`` on PATH."""

    raw = os.environ.get("BLENDER_MCP_COMMAND", "").strip() or "blender-mcp"
    return raw.split()
