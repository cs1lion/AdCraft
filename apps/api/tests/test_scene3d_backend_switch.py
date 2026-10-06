"""The backend switch must actually change which renderer is used.

This is the wiring test for `scene3d_renderer_backend`. It is deliberately not a
real render: what is under test is that the setting reaches the seam and that the
capability probe is switched WITH it (the naive wiring leaves the three.js path
being rejected by `blender --version`, which reads as "Blender broken").
"""

from __future__ import annotations

from app.core.config import Settings
from app.services.scene3d import threejs_renderer
from app.services.scene3d.blender_renderer import (
    get_blender_capability,
    render_scene_script,
)


def _settings(backend: str) -> Settings:
    return Settings(scene3d_renderer_backend=backend)


class TestBackendSwitch:
    def test_default_is_blender(self):
        renderer = threejs_renderer.resolve_scene3d_renderer(_settings("blender"))
        assert renderer is render_scene_script

    def test_threejs_is_selectable(self):
        # NOT a conditional test. When the capability is not ready the renderer
        # legitimately falls back to Blender, but the REASON must be a real one.
        # An earlier version of this test returned early on a non-ready
        # capability — which is how a wrong driver path survived: the fallback
        # fired, the test skipped, and the whole three.js path was silently dead
        # while 26 other assertions stayed green.
        capability = threejs_renderer.threejs_render_capability()
        renderer = threejs_renderer.resolve_scene3d_renderer(_settings("threejs"))
        if capability.state != "ready":
            assert renderer is render_scene_script
            # Whatever blocked it must be an environment fact, never a typo in
            # the path resolution itself. These assertions are the teeth.
            driver = threejs_renderer.RENDER_DRIVER
            assert driver.name == "render-frames.mjs"
            assert "web" in driver.parts and "scripts" in driver.parts, (
                f"driver path resolved outside apps/web/scripts: {driver}"
            )
            assert driver.exists(), f"driver path does not exist: {driver}"
            assert (threejs_renderer.WEB_ROOT / "dist").exists(), (
                f"frontend root has no dist: {threejs_renderer.WEB_ROOT}"
            )
        else:
            assert renderer is threejs_renderer.render_scene_script_threejs
            assert renderer is not render_scene_script

    def test_unknown_backend_fails_loudly(self):
        # Silently resolving a typo to the default means an operator asking for
        # three.js gets Blender and never knows.
        try:
            threejs_renderer.resolve_scene3d_renderer(_settings("threeJS"))
        except ValueError as error:
            assert "threeJS" in str(error)
        else:
            raise AssertionError("an unknown backend must not resolve silently")

    def test_capability_probe_follows_the_renderer(self):
        # The two must agree, or the three.js path is rejected by
        # `blender --version` once Blender is gone.
        assert (
            threejs_renderer.resolve_scene3d_capability_probe(_settings("blender"))
            is get_blender_capability
        )
        assert (
            threejs_renderer.resolve_scene3d_capability_probe(_settings("threejs"))
            is threejs_renderer.threejs_render_capability
        )
