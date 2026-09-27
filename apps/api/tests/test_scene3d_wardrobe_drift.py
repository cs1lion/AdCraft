"""Tests for cross-node character drift (V0.2 §5 服装维度 / plan §5.3).

The identity binding is the Dramagic lock: when two scene-3d nodes bind the
same character asset but render different appearances, the lock is lying. These
tests lock the two computable disagreements (appearance drift, binding conflict)
and the deliberate silences (unbound characters, single-node workflows).
"""

from __future__ import annotations


from app.schemas.scene_script import SceneScriptRoot
from app.services.scene3d.wardrobe_drift import check_cross_node_character_drift


def _script(
    *,
    character_id: str = "girl",
    asset_id: str | None = "asset-girl",
    color: str = "#E74C3C",
    palette: list[str] | None = None,
    name: str = "lab",
) -> SceneScriptRoot:
    appearance: dict[str, object] = {"color": color}
    if palette is not None:
        appearance["palette"] = palette
    return SceneScriptRoot.model_validate(
        {
            "scene": {
                "name": name,
                "environment": "indoor",
                "lighting": "cool",
                "duration": 3.0,
                "frame_rate": 30,
            },
            "characters": [
                {
                    "id": character_id,
                    "type": "lowpoly_human",
                    "character_asset_id": asset_id,
                    "appearance": appearance,
                    "keyframes": [
                        {"frame": 0, "position": [0, 0, 0], "rotation_y": 0, "action": "stand"}
                    ],
                }
            ],
            "props": [],
            "environment": [],
            "cameras": [
                {
                    "id": "cam1",
                    "shot_type": "wide",
                    "keyframes": [{"frame": 0, "position": [3, -4, 2], "look_at": [0, 0, 1]}],
                }
            ],
            "shots": [{"id": "s1", "camera": "cam1", "start_frame": 0, "end_frame": 89}],
            "speech_bindings": [],
        }
    )


class TestAppearanceDrift:
    def test_one_asset_two_appearances_is_a_finding(self) -> None:
        findings = check_cross_node_character_drift(
            {
                "node-corridor": _script(name="corridor", color="#E74C3C"),
                "node-street": _script(name="street", color="#3498DB"),
            }
        )
        assert [finding.code for finding in findings] == ["character_appearance_drift"]
        finding = findings[0]
        assert finding.subject == "asset-girl"
        # Both nodes are named, so the author knows where to fix it.
        assert "node-corridor" in finding.message and "node-street" in finding.message
        assert "#e74c3c" in finding.message and "#3498db" in finding.message

    def test_the_same_appearance_in_two_nodes_is_silent(self) -> None:
        findings = check_cross_node_character_drift(
            {
                "node-a": _script(name="a"),
                "node-b": _script(name="b"),
            }
        )
        assert findings == []

    def test_color_comparison_ignores_case(self) -> None:
        findings = check_cross_node_character_drift(
            {
                "node-a": _script(name="a", color="#e74c3c"),
                "node-b": _script(name="b", color="#E74C3C"),
            }
        )
        assert findings == []

    def test_unbound_characters_are_the_per_node_gates_business(self) -> None:
        # Nobody claimed an asset: there is no cross-node identity to violate
        # (the per-script gate flags unbound characters on its own).
        findings = check_cross_node_character_drift(
            {
                "node-a": _script(name="a", asset_id=None, color="#E74C3C"),
                "node-b": _script(name="b", asset_id=None, color="#3498DB"),
            }
        )
        assert findings == []

    def test_a_single_node_has_nothing_to_compare(self) -> None:
        assert check_cross_node_character_drift({"node-a": _script()}) == []

    def test_an_empty_workflow_is_silent(self) -> None:
        assert check_cross_node_character_drift({}) == []


class TestBindingConflict:
    def test_one_character_id_two_assets_is_a_finding(self) -> None:
        findings = check_cross_node_character_drift(
            {
                "node-a": _script(name="a", asset_id="asset-girl-red"),
                "node-b": _script(name="b", asset_id="asset-girl-blue"),
            }
        )
        codes = [finding.code for finding in findings]
        assert "character_binding_conflict" in codes
        conflict = next(f for f in findings if f.code == "character_binding_conflict")
        assert conflict.subject == "girl"
        assert "asset-girl-red" in conflict.message and "asset-girl-blue" in conflict.message

    def test_distinct_character_ids_never_collide(self) -> None:
        findings = check_cross_node_character_drift(
            {
                "node-a": _script(character_id="girl", asset_id="asset-1"),
                "node-b": _script(character_id="boy", asset_id="asset-2"),
            }
        )
        assert findings == []


# ---------------------------------------------------------------------------
# Executor wiring: the check runs on the workflow's scripts and is published
# ---------------------------------------------------------------------------


def _stub_executor(siblings: dict[str, SceneScriptRoot] | None) -> object:
    from app.api.v1.endpoints.scene_3d import _validate_scene_script  # noqa: F401

    from app.core.config import Settings
    from app.services.agent_canvas_node_execution import Scene3DNodeExecutor

    return Scene3DNodeExecutor(
        Settings(agent_runtime_mode="fake"),
        capability_probe=lambda: type("Cap", (), {"state": "ready", "error": None})(),
        renderer=lambda script, frames_dir, **kwargs: None,
        encoder=lambda input_dir, output_path, fps=30: None,
        sibling_scripts=lambda workflow_id: siblings,
    )


class TestExecutorReport:
    def test_the_report_carries_the_findings(self) -> None:
        executor = _stub_executor(
            {
                "node-a": _script(name="a", color="#E74C3C"),
                "node-b": _script(name="b", color="#3498DB"),
            }
        )
        report = executor._wardrobe_drift_report(  # type: ignore[attr-defined]
            _script(name="self", color="#E74C3C"),
            node_id="node-a",
            workflow_id="wf-1",
        )
        assert report["checked"] is True
        assert [finding["code"] for finding in report["findings"]] == [
            "character_appearance_drift"
        ]

    def test_the_nodes_own_script_wins_over_a_stale_persisted_copy(self) -> None:
        # The persisted sibling copy says blue; the draft this execution
        # rendered from says red. The draft is the truth.
        executor = _stub_executor(
            {
                "node-a": _script(name="stale", color="#3498DB"),
                "node-b": _script(name="b", color="#3498DB"),
            }
        )
        report = executor._wardrobe_drift_report(  # type: ignore[attr-defined]
            _script(name="self", color="#3498DB"),
            node_id="node-a",
            workflow_id="wf-1",
        )
        assert report["checked"] is True
        assert report["findings"] == []

    def test_an_unreadable_workflow_says_so_instead_of_implying_a_pass(self) -> None:
        executor = _stub_executor(None)
        report = executor._wardrobe_drift_report(  # type: ignore[attr-defined]
            _script(),
            node_id="node-a",
            workflow_id="wf-1",
        )
        assert report["checked"] is False
        assert report["reason"] == "workflow_scripts_unreadable"
        assert report["findings"] == []


class TestDeclaredWardrobePalette:
    """V0.2 §5 服装的"声明"侧：同一角色资产在多场里声明的色板一致吗.

    Appearance drift compares the render colour; the palette compares what
    the author DECLARED the wardrobe to be, which is what the next scene must
    inherit. Two scenes binding the same character while declaring different
    palettes is exactly "Scene 02 把她换成黑风衣" made visible.
    """

    def test_two_nodes_declaring_the_same_palette_are_silent(self) -> None:
        node_a = _script(name="a", palette=["#2C3E50", "#FFFFFF"])
        node_b = _script(name="b", palette=["#2C3E50", "#FFFFFF"])
        assert check_cross_node_character_drift({"a": node_a, "b": node_b}) == []

    def test_palette_comparison_ignores_case(self) -> None:
        node_a = _script(name="a", palette=["#2C3E50"])
        node_b = _script(name="b", palette=["#2c3e50"])
        assert check_cross_node_character_drift({"a": node_a, "b": node_b}) == []

    def test_two_nodes_declaring_different_palettes_are_a_finding(self) -> None:
        node_a = _script(name="a", palette=["#2C3E50"])
        node_b = _script(name="b", palette=["#C0392B"])
        findings = check_cross_node_character_drift({"a": node_a, "b": node_b})
        codes = [finding.code for finding in findings]
        assert codes == ["character_palette_drift"]
        finding = findings[0]
        assert finding.subject == "asset-girl"
        # The remedy must name the field the author now has.
        assert "服装色板" in finding.remedy

    def test_an_undeclared_palette_is_not_a_drift(self) -> None:
        node_a = _script(name="a")
        node_b = _script(name="b")
        assert check_cross_node_character_drift({"a": node_a, "b": node_b}) == []

    def test_one_node_declaring_and_one_staying_silent_is_not_a_drift(self) -> None:
        node_a = _script(name="a", palette=["#2C3E50"])
        node_b = _script(name="b")
        assert check_cross_node_character_drift({"a": node_a, "b": node_b}) == []

    def test_palette_drift_and_appearance_drift_can_coexist(self) -> None:
        # Same body colour, different declared wardrobes: the render agrees,
        # the declaration does not — BOTH findings belong there.
        node_a = _script(name="a", color="#2C3E50", palette=["#2C3E50"])
        node_b = _script(name="b", color="#2C3E50", palette=["#C0392B"])
        codes = {finding.code for finding in check_cross_node_character_drift({"a": node_a, "b": node_b})}
        assert codes == {"character_palette_drift"}


class TestPaletteAgainstTheAssetDeclaration:
    """ADR 0011: the asset is the source of truth; the previs is a proxy.

    A proxy wearing colours nobody declared is inventing the one fact the
    asset binding exists to pin. The check is single-node by nature (each
    script is compared against asset METADATA, not against a sibling), which
    is why these tests run with one node and still expect an answer.
    """

    def _declared(self, **kwargs: object) -> dict[str, list[str]]:
        return kwargs.get("palettes", {})  # type: ignore[return-value]

    def test_a_previs_wearing_a_declared_colour_is_silent(self) -> None:
        findings = check_cross_node_character_drift(
            {"a": _script(color="#2C3E50")},
            asset_palettes={"asset-girl": ["#2C3E50", "#FFFFFF"]},
        )
        assert [finding.code for finding in findings] == []

    def test_a_previs_inventing_a_colour_is_flagged(self) -> None:
        findings = check_cross_node_character_drift(
            {"a": _script(color="#E74C3C")},
            asset_palettes={"asset-girl": ["#2C3E50"]},
        )
        codes = [finding.code for finding in findings]
        assert codes == ["character_palette_vs_asset_drift"]
        finding = findings[0]
        assert finding.subject == "asset-girl"
        assert "预演在替角色发明颜色" in finding.message
        assert "服装色板" in finding.remedy

    def test_a_near_enough_colour_is_the_same_colour(self) -> None:
        """Different tools pick colours at different times; hex-exact would
        flag every legitimate reuse."""

        findings = check_cross_node_character_drift(
            {"a": _script(color="#2C3E50")},
            asset_palettes={"asset-girl": ["#2D3F52"]},
        )
        assert findings == []

    def test_an_asset_that_declares_nothing_is_not_a_disagreement(self) -> None:
        findings = check_cross_node_character_drift(
            {"a": _script(color="#E74C3C")},
            asset_palettes={"some-other-asset": ["#2C3E50"]},
        )
        assert findings == []

    def test_no_palette_map_skips_instead_of_failing(self) -> None:
        assert check_cross_node_character_drift({"a": _script()}) == []

    def test_a_declared_palette_hit_counts_even_when_the_body_differs(self) -> None:
        """The author's declaration is authoritative when it intersects."""

        findings = check_cross_node_character_drift(
            {"a": _script(color="#2C3E50", palette=["#C0392B", "#FFFFFF"])},
            asset_palettes={"asset-girl": ["#2C3E50", "#C0392B"]},
        )
        assert findings == []

    def test_an_unbound_character_is_out_of_scope(self) -> None:
        findings = check_cross_node_character_drift(
            {"a": _script(asset_id=None)},
            asset_palettes={"asset-girl": ["#2C3E50"]},
        )
        assert findings == []

    def test_the_asset_side_and_the_cross_node_side_coexist(self) -> None:
        """Two scenes agreeing with each other but not with the asset: the
        cross-node check is silent and the asset check fires — both answers
        belong in one report."""

        node_a = _script(name="a", color="#E74C3C")
        node_b = _script(name="b", color="#E74C3C")
        findings = check_cross_node_character_drift(
            {"a": node_a, "b": node_b},
            asset_palettes={"asset-girl": ["#2C3E50"]},
        )
        # The cross-node side is SILENT (both previs agree with each other);
        # the asset side fires once per node, because each node's proxy is
        # inventing the same wrong colour.
        assert [f.code for f in findings] == [
            "character_palette_vs_asset_drift",
            "character_palette_vs_asset_drift",
        ]
        assert {f.subject for f in findings} == {"asset-girl"}
