"""Asset geometry coverage and visible degradation (ADR 0005 §4).

The 2026-09-19 E2E run exposed that ``PropType`` and ``EnvironmentType``
declare many more kinds than ``_ASSET_BUILDERS`` implements, and
``_build_asset`` replaced every unimplemented one with a grey placeholder box
*without a trace*. ADR 0005 requires previs control level to be queryable and
never silent, so:

* every declared enum member must have a builder (guarded by a full-set
  assertion so a new enum member cannot silently ship unimplemented);
* an unregistered type must still report degradation through both the generated
  script marker and ``RenderResult.degraded_assets``.
"""

from __future__ import annotations

import ast
import inspect
import os
import re
from pathlib import Path
from typing import Any, get_args

import pytest

from app.schemas.scene_script import (
    EnvironmentType,
    PropType,
    SceneScriptRoot,
)
from app.services.scene3d.blender_converter import (
    _ASSET_BUILDERS,
    _ASSET_COLORS,
    _DEGRADED_ASSET_COLOR,
    _PART_COLOR_OVERRIDES,
    _build_asset,
    _build_lowpoly_human,
    asset_color,
    degraded_asset_ids,
    scene_script_to_blender,
)
from app.services.scene3d.blender_renderer import render_scene_script


ALL_PROP_TYPES: tuple[str, ...] = get_args(PropType)
ALL_ENVIRONMENT_TYPES: tuple[str, ...] = get_args(EnvironmentType)


def _primitive_location(source: str, part: str) -> tuple[float, float, float]:
    """The ``location=(...)`` passed to the primitive_add that becomes `part`.

    Read out of the generated script rather than recomputed from the builder's
    own constants, because the point of these tests is what the script actually
    does -- a builder can hold correct numbers and still emit them into the wrong
    operator or the wrong axis.
    """
    rename = source.find(f'.name = "{part}"')
    assert rename != -1, f"no object named {part!r}"
    before = source[:rename]
    matches = list(re.finditer(r"location=\(([-\d.]+), ([-\d.]+), ([-\d.]+)\)", before))
    assert matches, f"no primitive location precedes part {part!r}"
    return tuple(float(g) for g in matches[-1].groups())  # type: ignore[return-value]


def _part_scale(source: str, part: str) -> tuple[float, float, float]:
    """The (x, y, z) ``.scale`` assigned to a named part.

    Searched forward from the part's rename because the scale is set after the
    object is named, and the next ``.scale`` in the file belongs to it.
    """
    rename = source.find(f'.name = "{part}"')
    assert rename != -1, f"no object named {part!r}"
    after = source[rename:]
    match = re.search(r"\.scale = \(([-\d.]+), ([-\d.]+), ([-\d.]+)\)", after)
    assert match, f"no scale assigned to part {part!r}"
    return tuple(float(g) for g in match.groups())  # type: ignore[return-value]


class TestEveryDeclaredTypeHasGeometry:
    @pytest.mark.parametrize("prop_type", ALL_PROP_TYPES)
    def test_every_prop_type_has_a_builder(self, prop_type: str) -> None:
        assert prop_type in _ASSET_BUILDERS, (
            f"PropType member {prop_type!r} has no geometry and would silently "
            "render as a grey placeholder box"
        )

    @pytest.mark.parametrize("env_type", ALL_ENVIRONMENT_TYPES)
    def test_every_environment_type_has_a_builder(self, env_type: str) -> None:
        assert env_type in _ASSET_BUILDERS, (
            f"EnvironmentType member {env_type!r} has no geometry and would "
            "silently render as a grey placeholder box"
        )

    def test_no_orphan_builder_keys(self) -> None:
        # A builder for a type the schema no longer declares is dead code that
        # hides which kinds are actually reachable.
        declared = set(ALL_PROP_TYPES) | set(ALL_ENVIRONMENT_TYPES) | {"lowpoly_human"}
        assert set(_ASSET_BUILDERS) - declared <= set()


# Blender's own operator contract, read out of the installed 5.2.1 LTS by
# dumping ``op.get_rna_type().properties``. Only the subset the converter can
# legitimately call is listed. A builder that passes a keyword outside this set
# does not fail at script-generation time -- bpy raises
# "Converting py args to operator properties:: keyword X unrecognized" when the
# script RUNS, which is what took out the 2026-09-19 E2E shots that contained a
# vase or a cup.
BLENDER_PRIMITIVE_KEYWORDS: dict[str, frozenset[str]] = {
    "primitive_cylinder_add": frozenset({
        "align", "calc_uvs", "depth", "end_fill_type", "enter_editmode",
        "location", "radius", "rotation", "scale", "vertices",
    }),
    "primitive_cone_add": frozenset({
        "align", "calc_uvs", "depth", "end_fill_type", "enter_editmode",
        "location", "radius1", "radius2", "rotation", "scale", "vertices",
    }),
    "primitive_cube_add": frozenset({
        "align", "calc_uvs", "enter_editmode", "location", "rotation", "scale", "size",
    }),
    "primitive_uv_sphere_add": frozenset({
        "align", "calc_uvs", "enter_editmode", "location", "radius", "ring_count",
        "rotation", "scale", "segments",
    }),
    "primitive_ico_sphere_add": frozenset({
        "align", "calc_uvs", "enter_editmode", "location", "radius", "rotation",
        "scale", "subdivisions",
    }),
    "primitive_plane_add": frozenset({
        "align", "calc_uvs", "enter_editmode", "location", "rotation", "scale", "size",
    }),
    "primitive_torus_add": frozenset({
        "abso_major_rad", "abso_minor_rad", "align", "generate_uvs", "location",
        "major_radius", "major_segments", "minor_radius", "minor_segments", "mode",
        "rotation",
    }),
}

_BLENDER_CALL = re.compile(r"bpy\.ops\.mesh\.(?P<op>primitive_\w+_add)\((?P<args>[^)]*)\)")


def _primitive_calls(source: str) -> list[tuple[str, set[str]]]:
    calls = []
    for match in _BLENDER_CALL.finditer(source):
        keywords = set(re.findall(r"(\w+)=", match.group("args")))
        calls.append((match.group("op"), keywords))
    return calls


def _call_builder(asset_type: str) -> str:
    """Render one builder's snippet, tolerating the non-uniform signatures.

    ``_build_lowpoly_human`` also takes an explicit ``height``; the rest take
    only ``(obj_id, scale)``. Inspecting the signature keeps this test from
    breaking every time a builder needs an extra parameter.
    """
    builder = _ASSET_BUILDERS[asset_type]
    parameters = inspect.signature(builder).parameters
    kwargs: dict[str, Any] = {"scale": 1.0}
    if "height" in parameters:
        kwargs["height"] = 1.7
    if "color" in parameters:
        kwargs["color"] = "#888888"
    positional = [f"{asset_type}_probe"]
    # Be explicit about what each builder needs rather than silently skipping
    # the one whose signature differs, so the contract check still covers it.
    # obj_id is the positional first argument, already supplied above.
    required = [
        name for name, parameter in parameters.items()
        if parameter.default is inspect.Parameter.empty and name not in kwargs
        and name != "obj_id"
    ]
    assert not required, (
        f"{asset_type!r} needs unexpected builder parameters {required}; give them "
        "values here so the Blender-keyword check covers this builder too"
    )
    return builder(*positional, **kwargs)


class TestBuildersOnlyCallRealBlenderKeywords:
    @pytest.mark.parametrize("asset_type", sorted(_ASSET_BUILDERS))
    def test_builder_uses_only_valid_operator_keywords(self, asset_type: str) -> None:
        snippet = _call_builder(asset_type)
        calls = _primitive_calls(snippet)
        assert calls, f"{asset_type!r} builder emits no mesh primitive"
        for operator, keywords in calls:
            assert operator in BLENDER_PRIMITIVE_KEYWORDS, (
                f"{asset_type!r} calls bpy.ops.mesh.{operator}, which is not in the "
                "known-operator table -- extend the table deliberately"
            )
            unknown = keywords - BLENDER_PRIMITIVE_KEYWORDS[operator]
            assert unknown <= set(), (
                f"{asset_type!r} passes {sorted(unknown)} to bpy.ops.mesh.{operator}. "
                "That keyword does not exist on this operator, so the generated "
                "script raises 'keyword unrecognized' when Blender runs it."
            )

    def test_tapered_shapes_use_the_cone_operator(self) -> None:
        # radius1/radius2 belong to primitive_cone_add; a builder meaning a
        # tapered solid must use the cone operator, never the cylinder one.
        for asset_type in sorted(_ASSET_BUILDERS):
            for operator, keywords in _primitive_calls(_call_builder(asset_type)):
                if {"radius1", "radius2"} & keywords:
                    assert operator == "primitive_cone_add", (
                        f"{asset_type!r} passes radius1/radius2 to "
                        f"bpy.ops.mesh.{operator}; a cylinder has one radius, so the "
                        "tapered shape needs primitive_cone_add"
                    )


class TestGeneratedScriptIsExecutablePython:
    """Static guard: the snippet for every type parses as a Python statement.

    A builder that emits ``def _b_...(obj_id):`` with a mismatched continuation
    line or an unbalanced quote only fails when Blender runs it, which is the
    most expensive possible place to find out. Parsing catches the class of bug
    for free, without Blender.
    """

    def test_every_builder_snippet_parses(self) -> None:
        for asset_type in sorted(_ASSET_BUILDERS):
            snippet = _call_builder(asset_type)
            try:
                ast.parse(snippet, mode="exec")
            except SyntaxError as error:
                pytest.fail(
                    f"{asset_type!r} builder emitted non-parsable Blender source: "
                    f"{error.msg} at line {error.lineno}\n{snippet}"
                )

    def test_every_builder_snippet_survives_the_splicing_wrapper(self) -> None:
        """Each snippet must survive ``_build_asset``'s f-string, module-level.

        ``_build_asset`` interpolates the snippet into an unindented f-string
        that becomes part of the generated script, so a snippet carrying a
        triple quote would terminate that f-string, and one whose statements sit
        at a different indentation would silently swallow the parenting loop
        that follows it. Both parse fine in isolation, so this checks the real
        wrapper rather than the bare snippet.
        """

        for asset_type in sorted(_ASSET_BUILDERS):
            try:
                block = _build_asset(f"{asset_type}_probe", asset_type, [0.0, 0.0, 0.0], 0.0)
            except TypeError as error:
                pytest.fail(
                    f"_build_asset cannot place {asset_type!r}: {error}. The "
                    "builder's signature drifted from what the converter calls."
                )
            try:
                ast.parse(block)
            except SyntaxError as error:
                pytest.fail(
                    f"{asset_type!r} corrupts the generated script when spliced "
                    f"into _build_asset: {error.msg} at line {error.lineno}\n{block}"
                )
            assert f'wrapper.name = "{asset_type}_probe"' in block
            assert "_part.parent = wrapper" in block, (
                f"{asset_type!r} snippet closes a block early, so the parenting "
                "loop the converter appends would run outside the asset"
            )
            assert "# PREVIS_DEGRADED_ASSET" not in block, (
                f"{asset_type!r} is registered yet still rendered as a placeholder"
            )

    def test_a_generated_script_of_every_type_parses(self) -> None:
        """The assembled script for every declared kind is valid Python.

        Runs without Blender, so a syntax slip in a newly added builder is
        caught in the ordinary suite rather than only under ``-m integration``.
        The keyword table above is hand-maintained; this is the cheap always-on
        backstop behind it.
        """

        script = scene_script_to_blender(_all_asset_types_scene(), r"C:\tmp\probe")
        try:
            ast.parse(script)
        except SyntaxError as error:
            pytest.fail(
                f"generated script does not parse: {error.msg} at line "
                f"{error.lineno}: {error.text}"
            )
        # Every asset really made it into the script rather than being dropped
        # by an id collision inside the wrapper.
        for index in range(len(get_args(PropType))):
            assert f"prop_{index}" in script
        for index in range(len(get_args(EnvironmentType))):
            assert f"env_{index}" in script
        # Nothing degraded, so no trace marker may appear either.
        assert "# PREVIS_DEGRADED_ASSET" not in script


class TestTheHumanIsAPerson:
    """A mannequin is not a character reference.

    ``_build_lowpoly_human`` used to emit a cube and a sphere.  That is enough
    geometry to occupy space in a shot and nowhere near enough to read a
    silhouette from, and every character-facing artifact in the product is built
    on it: the 人物三视图, the 场景九宫格 that contains the figure, and the
    `storyboard` reference every video segment is submitted with.  Binding a
    three-view of a cube-and-sphere into a video prompt would instruct the model
    that the character *is* a magenta box.

    So the parts are asserted here rather than eyeballed in a render, which is
    how the cube survived: it always rendered fine, it just rendered nothing
    useful.
    """

    REQUIRED_PARTS = ("Body", "Head", "ArmL", "ArmR", "LegL", "LegR")

    @staticmethod
    def _snippet(height: float = 1.7) -> str:
        return _build_lowpoly_human("her", "#B03060", height, 1.0)

    def test_the_figure_has_the_parts_a_silhouette_is_read_from(self) -> None:
        snippet = self._snippet()
        for part in self.REQUIRED_PARTS:
            assert f'her_{part}' in snippet, (
                f"the low-poly human has no {part} part, so it renders as a box "
                "with a head and cannot serve as a character reference"
            )

    def test_the_limbs_are_beside_the_body_not_inside_it(self) -> None:
        # Arms stacked straight down at x=0 would pass the parts check above and
        # still read as one slab.
        snippet = self._snippet()
        arm_x = _primitive_location(snippet, "her_ArmL")[0]
        arm_r = _primitive_location(snippet, "her_ArmR")[0]
        assert arm_x < 0 < arm_r, (
            f"both arms are on the same side of the body (L x={arm_x}, R x={arm_r})"
        )

    def test_a_taller_character_is_taller_where_it_counts(self) -> None:
        # The torso's height is the dimension that has to track `height`; a
        # builder with hard-coded proportions would tie.
        assert _part_scale(self._snippet(1.5), "her_Body")[2] < _part_scale(
            self._snippet(1.9), "her_Body"
        )[2]

    def test_the_head_stays_clearly_above_the_torso(self) -> None:
        snippet = self._snippet()
        head_z = _primitive_location(snippet, "her_Head")[2]
        body_z = _primitive_location(snippet, "her_Body")[2]
        assert head_z > body_z + 0.2, (
            f"head at z={head_z} is not clearly above the torso at z={body_z}"
        )

    def test_the_legs_reach_the_ground(self) -> None:
        # Feet above z=0 is a floating figure.  This converter already shipped
        # that once ("characters rendered as floating heads" -- see the comment
        # on the part-parenting loop in `_build_asset`), so it is asserted rather
        # than assumed: the centre must be exactly half the box height above 0.
        snippet = self._snippet()
        leg_z = _primitive_location(snippet, "her_LegL")[2]
        leg_height = _part_scale(snippet, "her_LegL")[2]
        assert abs(leg_z - leg_height / 2) < 1e-6, (
            f"legs are centred at z={leg_z} with half-height {leg_height / 2}, "
            "so they do not start at the floor"
        )

    def test_the_figure_stands_as_tall_as_it_claims(self) -> None:
        # The head's crown must land on `height`.  A figure that comes out 20%
        # short is a proportion bug that no part-count check catches, and it makes
        # every `height` in a scene script a suggestion.
        height = 1.65
        snippet = self._snippet(height)
        head_z = _primitive_location(snippet, "her_Head")[2]
        match = re.search(r"primitive_uv_sphere_add\(radius=([\d.]+)", snippet)
        assert match, "no head radius in the snippet"
        crown = head_z + float(match.group(1))
        assert abs(crown - height) < 0.06 * height, (
            f"figure stands {crown:.3f} m tall but the script claims {height:.3f} m"
        )


class TestEveryAssetHasAColour:
    """Geometry without a material is a grey frame.

    Measured on an all-types render before the colour pass: 0 chromatic pixels
    out of 518400. Blender's default grey is also exactly what a degraded
    placeholder looks like, so the missing material defeated ADR 0005's "never
    silent" in practice even though the trace comment was already there.
    """

    @pytest.mark.parametrize("asset_type", sorted(_ASSET_BUILDERS))
    def test_every_registered_type_has_a_colour(self, asset_type: str) -> None:
        assert asset_color(asset_type) != _DEGRADED_ASSET_COLOR
        assert re.fullmatch(r"#[0-9A-Fa-f]{6}", asset_color(asset_type)), (
            f"{asset_type!r} has no usable colour: {asset_color(asset_type)!r}"
        )

    def test_a_new_builder_cannot_silently_ship_grey(self) -> None:
        # ``asset_color`` falls back to the box colour, so "a colour exists" is
        # not the same as "someone chose one". Requiring an explicit entry means
        # a builder added without one fails here instead of rendering grey.
        for asset_type in sorted(_ASSET_BUILDERS):
            if asset_type == "lowpoly_human":
                # The one builder that assigns its own body/head materials.
                continue
            assert asset_type in _ASSET_COLORS, (
                f"{asset_type!r} has geometry but no _ASSET_COLORS entry, so it "
                "would render in the fallback colour rather than a chosen one"
            )
        # And the palette must not keep entries for kinds that no longer exist.
        assert set(_ASSET_COLORS) - set(_ASSET_BUILDERS) <= set()

    def test_the_degraded_colour_differs_from_every_real_colour(self) -> None:
        # The whole point of the placeholder colour: nothing real may look like
        # it, or a reviewer reads a missing asset as geometry.
        used = {asset_color(t) for t in _ASSET_BUILDERS}
        assert _DEGRADED_ASSET_COLOR not in used

    def test_the_degraded_colour_is_assigned_when_degrading(self) -> None:
        assert asset_color("chandelier", degraded=True) == _DEGRADED_ASSET_COLOR

    def test_every_part_override_names_a_real_part_suffix(self) -> None:
        # An override keyed on a suffix no builder assigns would silently never
        # apply, leaving that part in the base colour.
        snippets = "".join(_call_builder(t) for t in _ASSET_BUILDERS)
        for suffix in _PART_COLOR_OVERRIDES:
            assert suffix in snippets, (
                f"part colour override {suffix!r} matches no builder part name"
            )

    def test_a_generated_script_assigns_a_material_to_every_asset(self) -> None:
        script = scene_script_to_blender(_all_asset_types_scene(), r"C:\tmp\probe")
        assert script.count("_part.data.materials.append(_mat)") == len(
            get_args(PropType)
        ) + len(get_args(EnvironmentType))
        assert "Principled BSDF" in script
        # One shared material per distinct colour per asset, not one per part:
        # a 4-post fence must not create four identical materials.
        assert "_part_materials.get(_rgb)" in script
        assert "_part_materials[_rgb] = _mat" in script

    def test_the_degraded_marker_names_the_missing_type_and_the_colour(self) -> None:
        scene = SceneScriptRoot.model_validate(SCENE)
        scene.props[0].type = "chandelier"  # type: ignore[misc]
        script = scene_script_to_blender(scene, r"C:\tmp\probe")
        assert "# PREVIS_DEGRADED_ASSET: crate_1 (chandelier)" in script
        assert "no geometry for this type" in script


# ---------------------------------------------------------------------------
# Every builder actually runs
# ---------------------------------------------------------------------------

BLENDER_EXE = os.environ.get("BLENDER_EXECUTABLE", r"D:\Blender\blender.exe")


def _all_asset_types_scene() -> SceneScriptRoot:
    """A scene placing one of every declared prop and environment kind.

    This is the only way to prove a builder works: the keyword table above is a
    hand-maintained list of Blender 5.2.1's operator properties, and a list can
    be wrong (or incomplete in a way that happens to let a bad call through) in
    exactly the way ``radius1`` did. Running Blender over every kind converts
    that possibility into a fact.
    """

    spread = 3.0
    props = [
        {
            "id": f"prop_{index}",
            "type": prop_type,
            "position": [-spread + (index % 4) * spread, -spread, 0.0],
            "scale": 1.0,
            "rotation_y": 0.0,
        }
        for index, prop_type in enumerate(get_args(PropType))
    ]
    environment = [
        {
            "id": f"env_{index}",
            "type": env_type,
            "position": [-spread + (index % 4) * spread, spread, 0.0],
            "scale": 1.0,
            "rotation_y": 0.0,
        }
        for index, env_type in enumerate(get_args(EnvironmentType))
    ]
    return SceneScriptRoot.model_validate(
        {
            "scene": {
                "name": "all-asset-types",
                "environment": "outdoor",
                "lighting": "neutral",
                "duration": 1.0,
                "frame_rate": 24,
            },
            "characters": [],
            "props": props,
            "environment": environment,
            "cameras": [
                {
                    "id": "cam1",
                    "shot_type": "wide",
                    "keyframes": [
                        {"frame": 0, "position": [0, -12, 8], "look_at": [0, 0, 1]},
                        {"frame": 23, "position": [2, -10, 6], "look_at": [0, 0, 1]},
                    ],
                }
            ],
            "shots": [
                {"id": "shot1", "camera": "cam1", "start_frame": 0, "end_frame": 24}
            ],
        }
    )


@pytest.mark.integration
@pytest.mark.skipif(
    not os.path.exists(BLENDER_EXE),
    reason=f"Blender not available at {BLENDER_EXE}",
)
class TestEveryBuilderActuallyRuns:
    """The self-test the queue asked for: execute all of them, for real.

    ``radius1`` reached a cylinder operator and blew up at render time, so
    "a builder is registered" is not evidence that it works. This renders one
    scene containing every declared kind at one frame and asserts Blender came
    back clean.
    """

    def test_all_asset_types_render_without_error(self, tmp_path: Path) -> None:
        scene = _all_asset_types_scene()
        assert len(scene.props) == len(get_args(PropType))
        assert len(scene.environment) == len(get_args(EnvironmentType))

        # Nothing may degrade: every kind has a builder, so a grey box here
        # means a builder raised and the converter fell back.
        assert degraded_asset_ids(scene) == ()

        result = render_scene_script(
            scene,
            str(tmp_path / "frames"),
            executable=BLENDER_EXE,
            timeout_seconds=600,
            keyframes_only=True,
        )

        # A builder that raises kills the script before any frame is written, so
        # the renderer reports failure. A builder that raises *after* the color
        # pass would leave frames behind but set ``error`` -- both are failures
        # for this test.
        assert result.success, f"Blender failed: {result.error}"
        assert result.error is None, (
            "Blender produced frames but reported a post-render failure; a "
            f"builder likely raised: {result.error}"
        )
        assert result.frame_count > 0
        assert result.degraded_assets == ()

    def test_a_degraded_asset_is_visibly_unmistakable(self, tmp_path: Path) -> None:
        """A placeholder is magenta on screen, not merely named in a comment.

        ADR 0005 §4 asks for a control level that is queryable and never silent.
        Before the colour pass a placeholder was the same default grey as every
        real part, so a reviewer could not tell a faithful render from a missing
        one without opening the generated script -- the trace existed but nobody
        would see it.
        """

        pytest.importorskip("PIL", reason="Pillow is needed to inspect rendered pixels")
        from PIL import Image

        scene = _all_asset_types_scene()
        # A type the schema allows but no builder implements, exactly as a new
        # enum member without geometry behaves in production.
        scene.props[0].type = "chandelier"  # type: ignore[misc]

        result = render_scene_script(
            scene,
            str(tmp_path / "frames"),
            executable=BLENDER_EXE,
            timeout_seconds=600,
            keyframes_only=True,
        )
        assert result.success, f"Blender failed: {result.error}"
        assert result.degraded_assets == ("prop_0:chandelier",)

        frames = sorted((tmp_path / "frames").glob("frame_*.png"))
        assert frames, "the degraded scene produced no frames"
        with Image.open(frames[0]) as image:
            raw = image.convert("RGB").tobytes()
        # Shading shifts absolute values, so test the hue relationship rather
        # than an exact colour: magenta keeps red and blue high and green low
        # under any plausible light.
        magenta = sum(
            1
            for index in range(0, len(raw), 3)
            if raw[index] > 120 and raw[index + 2] > 100 and raw[index + 1] < raw[index] * 0.5
        )
        assert magenta > 0, (
            "the degraded placeholder rendered in the same grey as real geometry; "
            "a reviewer cannot tell a missing asset from a faithful render"
        )



SCENE: dict[str, Any] = {
    "scene": {
        "name": "teahouse",
        "environment": "indoor",
        "lighting": "warm",
        "duration": 4.0,
        "frame_rate": 30,
    },
    "environment": [
        {"id": "wall_1", "type": "wall", "position": [-3, 0, -3], "rotation_y": 0, "scale": 1.0}
    ],
    "characters": [],
    "props": [
        {"id": "crate_1", "type": "crate", "position": [1, 0, 1], "rotation_y": 0, "scale": 1.0}
    ],
    "cameras": [
        {
            "id": "cam1",
            "shot_type": "wide",
            "keyframes": [
                {"frame": 0, "position": [8, -10, 5], "look_at": [0, 0, 1]},
                {"frame": 60, "position": [7, -9, 5], "look_at": [0, 0, 1]},
            ],
        }
    ],
    "shots": [
        {
            "id": "shot1",
            "camera": "cam1",
            "start_frame": 0,
            "end_frame": 60,
            "description": "wide establishing",
        }
    ],
}


class TestDegradationIsVisible:
    def test_implemented_types_do_not_degrade(self) -> None:
        script = SceneScriptRoot.model_validate(SCENE)
        assert degraded_asset_ids(script) == ()

    def test_unregistered_type_is_reported(self) -> None:
        # Simulate a kind the schema allows but the converter does not
        # implement. The type must survive model validation yet still be
        # reported as degraded rather than silently swapped.
        scene = SceneScriptRoot.model_validate(
            {**SCENE, "props": [{"id": "alien_1", "type": "crate",
                                 "position": [0, 0, 0], "rotation_y": 0, "scale": 1.0}]}
        )
        # Forces the fallback path by registering a type with no builder.
        scene.props[0].type = "chandelier"  # type: ignore[misc]
        degraded = degraded_asset_ids(scene)
        assert degraded == ("alien_1:chandelier",)

    def test_marker_is_written_into_generated_script(self, tmp_path: Any) -> None:
        # The generated Blender source must carry the trace, so the degradation
        # is inspectable without running the render.
        import app.services.scene3d.blender_converter as converter

        scene = SceneScriptRoot.model_validate(SCENE)
        scene.props[0].type = "chandelier"  # type: ignore[misc]
        script_text = converter.scene_script_to_blender(scene, str(tmp_path))
        assert "# PREVIS_DEGRADED_ASSET: crate_1 (chandelier)" in script_text
