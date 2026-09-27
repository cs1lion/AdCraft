"""Tests for the node patch scope report (ADR 0009 决策 2).

Locks the contract the author depends on: a content edit reports NO affected
neighbours (downstream consumes output, not authoring state), the edited keys
are named exactly, and an unclassified patch field cannot silently be local.
"""

from __future__ import annotations

from app.services.agent_canvas_scope_report import (
    AUTHORING_PATCH_FIELDS,
    build_patch_scope_report,
)


class TestContentEditScope:
    def test_a_scene_script_edit_names_its_keys_and_no_neighbours(self) -> None:
        before = {"scene_script": {"scene": {"name": "lab"}, "characters": [{"id": "a"}]}}
        patch = {
            "structured_content": {
                "scene_script": {"scene": {"name": "lab"}, "characters": [{"id": "a"}, {"id": "b"}]}
            }
        }

        report = build_patch_scope_report(
            node_type="scene-3d",
            before_structured=before,
            patch_fields=patch,
        )

        assert report.affected_neighbours == ()
        # The report names the touched area in the author's vocabulary.
        assert "场景脚本" in report.content_areas
        assert report.edited_keys  # and the exact paths
        assert any("characters" in key for key in report.edited_keys)
        # The "no neighbours" fact is STATED, not left as an empty list.
        assert any("不影响任何已绑定节点" in note for note in report.notes)
        assert report.dirty_reasons == ("场景脚本有未提交的作者修改",)

    def test_scalar_authoring_edits_are_local_too(self) -> None:
        report = build_patch_scope_report(
            node_type="voice-cast",
            before_structured={"audio_bed": {"scripts": []}},
            patch_fields={"generation_prompt": "新的对白"},
        )

        assert report.affected_neighbours == ()
        assert report.edited_keys == ("generation_prompt",)
        assert "生成提示词" in report.content_areas

    def test_merge_semantics_the_report_is_about_the_merged_result(self) -> None:
        # The patch carries ONE key of structured_content; the report diffs
        # against the whole merged dict (narration must survive and NOT be
        # reported as changed).
        report = build_patch_scope_report(
            node_type="scene-3d",
            before_structured={"narration": "低沉的风声", "dialogue_lines": []},
            patch_fields={"structured_content": {"dialogue_lines": [{"text": "x"}]}},
        )

        assert "narration" not in " ".join(report.edited_keys)
        assert "台词行" in report.content_areas

    def test_a_no_op_patch_says_so(self) -> None:
        report = build_patch_scope_report(
            node_type="scene-3d",
            before_structured={"scene_script": {"scene": {"name": "lab"}}},
            patch_fields={"structured_content": {}},
        )

        assert report.edited_keys == ()
        assert report.notes == ("补丁没有改变任何字段。",)


class TestUnclassifiedFields:
    def test_a_field_outside_the_registry_is_not_silently_local(self) -> None:
        report = build_patch_scope_report(
            node_type="video",
            before_structured={},
            patch_fields={"output_asset_id": "asset_1"},
        )

        # No scope claim at all — the patch must be refused/classified first.
        assert report.edited_keys == ()
        assert report.affected_neighbours == ()
        assert any("未在 ADR 0009 范围登记表" in note for note in report.notes)

    def test_the_registry_covers_the_patch_schema(self) -> None:
        for name in (
            "title",
            "summary_prompt",
            "generation_prompt",
            "structured_content",
            "model_selection_mode",
            "model_ref",
            "parameters",
        ):
            assert name in AUTHORING_PATCH_FIELDS


class TestSerialization:
    def test_the_report_round_trips_for_the_api_response(self) -> None:
        report = build_patch_scope_report(
            node_type="scene-3d",
            before_structured={"scene_script": {"a": 1}},
            patch_fields={"structured_content": {"scene_script": {"a": 2}}},
        )

        payload = report.to_dict()
        assert payload["affected_neighbours"] == []
        assert payload["edited_keys"]
        assert payload["dirty_reasons"]
        assert payload["notes"]
