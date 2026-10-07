"""Server-side three.js previs renderer.

The plan (`docs/plans/threejs-renderer-replacement.md`) replaces the Blender
renderer with a headless-Chrome render of the SAME `SceneScript3DPreview` the
author edits in, so there is one scene implementation instead of two.

This module is the seam. ``agent_canvas_node_execution`` injects a renderer and
calls it as::

    result = renderer(scene_script, frames_dir, timeout_seconds=..., keyframes_only=...)

and then reads ``success`` / ``frame_count`` / ``error`` / ``rendered_frames`` /
``degraded_assets`` off the result. This function has that exact shape and
returns the same ``RenderResult`` type the Blender renderer returns, so wiring
it in changes the injection and nothing else.

What it actually does is spawn one Node subprocess
(``apps/web/scripts/render-frames.mjs``) which serves the built frontend, drives
headless Chrome, and writes ``frame_<NNNN>.png`` — the same filenames and
directory layout Blender produced, which is why the encoder, keyframe
extraction, clip publisher and timeline handoff need no changes at all. That was
verified end to end: 120 frames in 10.5s, then ``encode_png_sequence``
unmodified produced a valid h264 MP4.

Two measured facts worth keeping in mind before editing this file:

- The DEFAULT Chromium GL config is the fast one (ANGLE over D3D11 on the host
  GPU). Forcing OpenGL with ``--use-angle=gl`` measured ~5.8x SLOWER, so this
  module passes no GL flags.
- Capture uses Playwright's element screenshot rather than in-page
  ``canvas.toDataURL()``. With ``preserveDrawingBuffer`` confirmed true and a
  single canvas, the in-page read still returned one frozen frame while the
  screenshot of the same canvas differed every frame. The driver encodes that
  reasoning and fails loudly on a frozen canvas.
"""

from __future__ import annotations

import json
import os
import subprocess
import tempfile
from pathlib import Path

from app.core.config import Settings
from app.schemas.scene_script import SceneScriptRoot

from .blender_converter import keyframe_render_frames
from .blender_renderer import BlenderCapability, RenderResult, degraded_asset_ids

#: Where the render driver and the built frontend live.
#: Resolved by walking UP from this file to the repository root — the directory
#: that contains ``apps/`` — rather than counting parents. Counting broke twice:
#: first ``parents[3] / "web"`` (which is apps/api/web, missing one level), then
#: ``parents[4] / "apps" / "web"`` (which is apps/apps/web, one too many). The
#: capability check surfaced both as "unsupported", and the resolver's silent
#: Blender fallback turned them into a dead three.js path that looked fine.
_HERE = Path(__file__).resolve()
_MARKER = "apps"
_WEB_ROOT: Path | None = None
for _candidate in [_HERE, *_HERE.parents]:
    if _candidate.name == _MARKER and (_candidate / "api" / "app").is_dir():
        _WEB_ROOT = _candidate / "web"
        break
if _WEB_ROOT is None:  # pragma: no cover - only if the package is relocated
    raise RuntimeError("cannot locate the apps/web frontend from " + str(_HERE))

RENDER_DRIVER = _WEB_ROOT / "scripts" / "render-frames.mjs"
WEB_ROOT = _WEB_ROOT

#: The driver's exit codes. 2 is its own coded failure; anything else is an
#: unexpected crash and is reported with the exit code attached.
_DRIVER_FAILURE = 2


def _settings() -> Settings:
    from app.core.config import get_settings

    return get_settings()


def _keyframe_frames(scene_script: SceneScriptRoot) -> list[int]:
    """The instants a keyframes-only pass renders.

    Delegates to the repository's own ``keyframe_render_frames`` — the same
    function the Blender renderer uses, and the same frames the node publishes
    as ``scene3d_keyframe_frames``. Re-deriving the rule here would let the
    5-still clip and its metadata drift apart, which is exactly the silent
    disagreement this pipeline is built to prevent.
    """

    return keyframe_render_frames(scene_script)


def render_scene_script_threejs(
    scene_script: SceneScriptRoot,
    output_dir: str,
    *,
    timeout_seconds: int,
    keyframes_only: bool = False,
    include_control_passes: bool = False,
    width: int | None = None,
    height: int | None = None,
) -> RenderResult:
    """Render ``scene_script`` to ``frame_<NNNN>.png`` files in ``output_dir``.

    Drop-in for ``render_scene_script``: same arguments, same result type. See
    the module docstring for why it spawns Node rather than replacing the
    orchestration.
    """

    import time

    started = time.time()
    rendered_frames = "keyframes" if keyframes_only else "animation"
    degraded = degraded_asset_ids(scene_script)

    os.makedirs(output_dir, exist_ok=True)

    # The script rides to the driver as a temp file rather than a command-line
    # argument: a real scene is tens of kilobytes and Windows caps the command
    # line well below that.
    script_file = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", delete=False, encoding="utf-8"
        ) as handle:
            json.dump(scene_script.model_dump(mode="json"), handle, ensure_ascii=False)
            script_file = handle.name

        command = [
            "node",
            str(RENDER_DRIVER),
            "--script",
            script_file,
            "--out",
            os.path.abspath(output_dir),
            # The driver's --root used to default to a hardcoded path in ONE
            # checkout. Omitting it therefore did not fall back to "the
            # nearest frontend" — it silently rendered whatever frontend that
            # literal points at, which on any other machine is the wrong code
            # (or nothing at all). Always pass the root this module resolved.
            "--root",
            str(WEB_ROOT),
        ]
        if keyframes_only:
            frames = _keyframe_frames(scene_script)
            if not frames:
                return RenderResult(
                    success=False,
                    error="scene3d_no_keyframe_frames: the scene declares no keyframe frames.",
                    duration_seconds=time.time() - started,
                    degraded_assets=degraded,
                    rendered_frames=rendered_frames,
                )
            command.extend(["--frames", ",".join(str(frame) for frame in frames)])
        command.extend(["--width", str(width or 1280), "--height", str(height or 540)])

        try:
            proc = subprocess.run(
                command,
                capture_output=True,
                text=True,
                # The driver is a single subprocess that finishes the whole
                # sequence, so its budget IS this render's budget plus a small
                # margin for browser startup and the static server.
                timeout=timeout_seconds + 120,
                cwd=str(WEB_ROOT),
            )
        except subprocess.TimeoutExpired:
            written = len(list(Path(output_dir).glob("frame_*.png")))
            return RenderResult(
                success=False,
                error=(
                    f"three.js render timed out after {timeout_seconds}s "
                    f"with {written} frame(s) written."
                ),
                duration_seconds=time.time() - started,
                degraded_assets=degraded,
                rendered_frames=rendered_frames,
            )

        frames_written = len(list(Path(output_dir).glob("frame_*.png")))

        if proc.returncode != 0:
            # The driver reports its own coded failures on stderr with a
            # code prefix; pass those through verbatim so a frozen canvas or a
            # black frame is diagnosable from the node error alone.
            detail = (proc.stderr or proc.stdout or "").strip()[-500:]
            return RenderResult(
                success=False,
                error=f"three.js renderer failed: {detail}",
                duration_seconds=time.time() - started,
                degraded_assets=degraded,
                rendered_frames=rendered_frames,
            )

        if frames_written == 0:
            return RenderResult(
                success=False,
                error="three.js renderer wrote no frames.",
                duration_seconds=time.time() - started,
                degraded_assets=degraded,
                rendered_frames=rendered_frames,
            )

        return RenderResult(
            success=True,
            frame_count=frames_written,
            output_dir=os.path.abspath(output_dir),
            duration_seconds=time.time() - started,
            # No Blender version to report. The node stores this verbatim, so
            # it has to be null rather than a fabricated string.
            blender_version=None,
            degraded_assets=degraded,
            rendered_frames=rendered_frames,
        )
    finally:
        if script_file:
            try:
                os.unlink(script_file)
            except OSError:
                pass


def threejs_render_capability() -> BlenderCapability:
    """Whether the three.js render path can run at all.

    Checked instead of assumed: it needs Node, the built frontend, and a
    Chromium the Playwright in ``apps/web`` can drive. Any of those missing is a
    queryable state, never a surprise at render time.
    """

    if not RENDER_DRIVER.exists():
        return BlenderCapability(
            state="unsupported",
            error=f"render driver missing: {RENDER_DRIVER}",
        )
    if not (WEB_ROOT / "dist" / "render.html").exists():
        return BlenderCapability(
            state="unsupported",
            error="frontend render entry not built: run `npm run build` in apps/web",
        )
    for executable in ("node",):
        if subprocess.run(["where" if os.name == "nt" else "which", executable],
                          capture_output=True).returncode != 0:
            return BlenderCapability(state="unsupported", error=f"{executable} not found")
    return BlenderCapability(state="ready", executable="node")


def resolve_scene3d_renderer(settings):
    """Pick the previs renderer from settings.

    The seam is ``Scene3DNodeExecutor``'s ``renderer`` injection, so switching
    backends changes nothing in the orchestration: both candidates have the same
    signature and return the same ``RenderResult``.

    An unready three.js backend falls back to Blender rather than failing the
    node, because the three.js path depends on a built frontend and a drivable
    Chromium — optional infrastructure. An UNKNOWN backend value, by contrast,
    fails loudly: an operator who wrote ``threejs`` and got Blender anyway would
    be measuring the wrong thing without ever knowing.
    """

    from .blender_renderer import render_scene_script

    backend = getattr(settings, "scene3d_renderer_backend", "blender")
    if backend == "blender":
        return render_scene_script
    if backend == "threejs":
        if threejs_render_capability().state != "ready":
            return render_scene_script
        return render_scene_script_threejs
    raise ValueError(
        f"scene3d_renderer_backend must be 'blender' or 'threejs', got {backend!r}"
    )


def resolve_scene3d_capability_probe(settings):
    """The capability check that matches the configured backend.

    Coupled to the renderer on purpose: the three.js path must not be rejected
    by ``blender --version`` — exactly the failure a naive wiring produces once
    Blender is uninstalled, and one that would read as "Blender broken" rather
    than "wrong renderer configured".
    """

    from .blender_renderer import get_blender_capability

    if getattr(settings, "scene3d_renderer_backend", "blender") == "threejs":
        return threejs_render_capability
    return get_blender_capability


