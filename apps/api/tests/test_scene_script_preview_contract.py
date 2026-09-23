"""The checked-in frontend preview contract must match its generator.

The browser preview and the Blender converter each need the same two facts:
which asset kinds exist, and what colour each one renders in. They used to be
written down twice, in Python and in TypeScript, and the copy drifted -- the
frontend had geometry for 7 of the 25 kinds the schema declares and rendered the
other 18 as the same ``#888888`` box Blender uses for an unimplemented asset.

So the frontend file is generated from the Python schema, and this test pins the
two together: if someone edits the generated file by hand, or adds a kind to the
schema without regenerating, the suite fails here instead of the browser quietly
falling back to a grey box.

The test deliberately reads the file as *text* rather than executing it. It is
TypeScript, so the only thing worth checking is that it is the generator's
output verbatim.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.cli.generate_scene_script_preview_contract import (
    DEFAULT_OUTPUT,
    render_typescript,
)
from app.schemas.scene_script import EnvironmentType, PropType
from app.services.scene3d.blender_converter import (
    _ASSET_BUILDERS,
    _ASSET_COLORS,
    _DEGRADED_ASSET_COLOR,
)
from typing import get_args

# This file is <repo>/apps/api/tests/<name>.py, so parents[3] is <repo>.
_REPO_ROOT = Path(__file__).resolve().parents[3]


def test_the_checked_in_file_is_exactly_the_generators_output() -> None:
    # ``read_text``/``write_text`` round-trip newlines on Windows, so comparing
    # text (not bytes) is what keeps this test green on every platform.
    assert DEFAULT_OUTPUT.exists(), (
        f"{DEFAULT_OUTPUT} is missing -- run "
        "`python -m app.cli.generate_scene_script_preview_contract`"
    )
    assert DEFAULT_OUTPUT.read_text(encoding="utf-8") == render_typescript()


def test_the_generator_writes_inside_the_web_app_not_the_api_app() -> None:
    # The default output path used to be relative, so running the CLI from
    # ``apps/api`` created ``apps/api/apps/web/...`` -- a second copy that
    # nothing imports and that looks checked in. Anchor it to the file instead.
    assert DEFAULT_OUTPUT == _REPO_ROOT / "apps" / "web" / "src" / "types" / (
        "scene-script.generated.ts"
    ), DEFAULT_OUTPUT
    assert not (_REPO_ROOT / "apps" / "api" / "apps").exists()


def test_the_contract_declares_every_schema_kind() -> None:
    rendered = render_typescript()
    for prop_type in get_args(PropType):
        assert f'"{prop_type}"' in rendered, (
            f"{prop_type!r} is in PropType but not in the frontend contract"
        )
    for environment_type in get_args(EnvironmentType):
        assert f'"{environment_type}"' in rendered, (
            f"{environment_type!r} is in EnvironmentType but not in the frontend contract"
        )


def test_the_contract_carries_a_colour_for_every_kind_that_has_geometry() -> None:
    rendered = render_typescript()
    for asset_type in sorted(set(_ASSET_BUILDERS) - {"lowpoly_human"}):
        assert f"{asset_type}: " in rendered, (
            f"{asset_type!r} has a builder but no colour in the frontend contract"
        )


def test_the_placeholder_is_not_a_colour_any_real_kind_uses() -> None:
    # The one property the whole scheme rests on: a viewer must be able to tell
    # "no geometry for this kind" from "this is what the kind looks like".
    rendered = render_typescript()
    assert f'export const PLACEHOLDER_ASSET_COLOR = "{_DEGRADED_ASSET_COLOR}";' in rendered
    for asset_type, colour in _ASSET_COLORS.items():
        assert f"{asset_type}: \"{colour}\"," in rendered
        assert colour != _DEGRADED_ASSET_COLOR


@pytest.mark.parametrize(
    ("declared", "converter_key"),
    [
        *[(t, t) for t in get_args(PropType)],
        *[(t, t) for t in get_args(EnvironmentType)],
    ],
)
def test_the_palette_key_matches_the_converter_key(
    declared: str, converter_key: str
) -> None:
    """The frontend colours must be looked up by the converter's own names.

    ``_ASSET_COLORS`` is keyed by the converter's builder names, which happen to
    equal the schema enum members for every kind except ``lowpoly_human`` (the
    one builder the schema never names). If those two naming schemes ever
    diverge, every colour would silently resolve to the fallback brown and this
    test would be the only thing standing between the browser and a monochrome
    preview.
    """

    assert converter_key in _ASSET_BUILDERS, (
        f"{declared!r} is declared in the schema but has no builder, so the "
        "converter would degrade it"
    )
    assert converter_key in _ASSET_COLORS
