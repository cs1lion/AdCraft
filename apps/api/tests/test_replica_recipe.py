"""Unit tests for the G5 .adrecipe layer (hypit recipes 的 AdCraft 落地).

三层锁定：

- 文档层：.adrecipe 往返（未设置的维度不写/不回填）、结构错误显式报错
  （未知维度/根元素/版本/缺 id/缺 subtitle）、normalize 兜底；
- 词汇表纪律：配方只收渲染链真实消费的六维（font/color/position/lead/tail/
  handoff），apply_recipe 是 1:1 合并（未设置的维度保持样式原值）；
- 变体 × 编译：变体 = skill × recipe（确定性轮换、相邻变体配方不同），
  编译层应用配方后 cue 样式与可见窗真实改变，变体渲染计划之间**看得见
  差异**（不再是除槽位值外逐字节相同）；端点契约（recipes/export/import/
  direct-execute 的 recipe 字段/variant-render-plans 的配方差异）。

设计依据：docs/plans/replica-hypit-gap-analysis.md P2 recipes 行。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.schemas.agent_canvas_ad_media import (
    ReplicaBeatV2,
    ReplicaBlueprintContentV2,
    ReplicaShotV2,
)
from app.schemas.workflow_v2 import WorkflowV2TimelineSubtitleStyle
from app.services.replica import variants as va
from app.services.replica.direct_execute import plan_direct_execute
from app.services.replica.direct_execute_render import plan_direct_execute_render
from app.services.replica import recipe as rc
from app.services.replica.recipe import (
    ADRECIPE_VERSION,
    AdRecipeParseError,
    ReplicaRecipeV2,
    ReplicaSubtitleRecipeV2,
    adrecipe_from_recipe,
    apply_recipe,
    default_recipe,
    load_recipes,
    recipe_from_adrecipe,
)


# ---------------------------------------------------------------------------
# 文档层：往返与拒绝
# ---------------------------------------------------------------------------


def _recipe(**overrides) -> ReplicaRecipeV2:
    payload = {
        "recipe_id": "amber-emphasis",
        "name": "琥珀强调",
        "description": "暖色强调字幕。",
        "version": "1",
        "subtitle": ReplicaSubtitleRecipeV2(
            font_size=40,
            color="#FFC658",
            position="bottom_center",
            lead_seconds=0.1,
            tail_seconds=0.2,
            handoff="cut",
        ),
    }
    payload.update(overrides)
    return ReplicaRecipeV2(**payload)


def test_adrecipe_roundtrip_full_dimensions() -> None:
    recipe = _recipe()
    text = adrecipe_from_recipe(recipe)

    assert f'<adrecipe version="{ADRECIPE_VERSION}" kind="subtitle-style" id="amber-emphasis"' in text
    assert "font-size=\"40\"" in text
    assert "color=\"#FFC658\"" in text
    assert "lead=\"0.1\"" in text
    assert "tail=\"0.2\"" in text
    assert 'handoff="cut"' in text
    assert recipe_from_adrecipe(text) == recipe


def test_adrecipe_omits_unset_dimensions() -> None:
    """未设置的维度不写进文档，也不在回读时被填默认值。"""
    recipe = _recipe(subtitle=ReplicaSubtitleRecipeV2(font_size=56, position="center"))

    text = adrecipe_from_recipe(recipe)
    back = recipe_from_adrecipe(text)

    assert "color" not in text
    assert back.subtitle.applied_fields() == {"font_size": 56, "position": "center"}


def test_adrecipe_rejects_unknown_property() -> None:
    text = adrecipe_from_recipe(_recipe()).replace(
        "<subtitle ", '<subtitle motion="whip-pan" ', 1
    )
    with pytest.raises(AdRecipeParseError, match="Unknown subtitle recipe property"):
        recipe_from_adrecipe(text)


def test_adrecipe_rejects_structural_errors() -> None:
    good = adrecipe_from_recipe(_recipe())
    with pytest.raises(AdRecipeParseError, match="Unexpected root element"):
        recipe_from_adrecipe(
            good.replace("<adrecipe", "<advideo", 1).replace("</adrecipe>", "</advideo>", 1)
        )
    with pytest.raises(AdRecipeParseError, match="version"):
        recipe_from_adrecipe(good.replace(f'version="{ADRECIPE_VERSION}"', 'version="99"', 1))
    with pytest.raises(AdRecipeParseError, match="kind"):
        recipe_from_adrecipe(good.replace('kind="subtitle-style"', 'kind="other"', 1))
    with pytest.raises(AdRecipeParseError, match="id"):
        recipe_from_adrecipe(good.replace(' id="amber-emphasis"', "", 1))
    with pytest.raises(AdRecipeParseError, match="subtitle"):
        recipe_from_adrecipe(good.replace("<subtitle", "<subtitles", 1).replace("/>", "></subtitles>", 1))
    with pytest.raises(AdRecipeParseError):
        recipe_from_adrecipe("not xml at all")


def test_adrecipe_rejects_out_of_range_values() -> None:
    text = adrecipe_from_recipe(_recipe()).replace('font-size="40"', 'font-size="200"', 1)
    with pytest.raises(AdRecipeParseError, match="Invalid subtitle recipe values"):
        recipe_from_adrecipe(text)


# ---------------------------------------------------------------------------
# 词汇表纪律：apply_recipe 是 1:1 合并
# ---------------------------------------------------------------------------


def test_apply_recipe_merges_only_set_dimensions() -> None:
    style = WorkflowV2TimelineSubtitleStyle(
        font_size=42, color="#FFFFFF", position="bottom_center",
        lead_seconds=0.1, tail_seconds=0.2, handoff="cut",
    )
    recipe = _recipe(
        subtitle=ReplicaSubtitleRecipeV2(font_size=24, position="top_center")
    )

    merged = apply_recipe(style, recipe)

    assert merged.font_size == 24  # 配方覆盖
    assert merged.position == "top_center"  # 配方覆盖
    assert merged.color == "#FFFFFF"  # 未设置 → 保持样式原值
    assert (merged.lead_seconds, merged.tail_seconds, merged.handoff) == (0.1, 0.2, "cut")


def test_apply_recipe_none_is_identity() -> None:
    style = WorkflowV2TimelineSubtitleStyle(font_size=33)
    assert apply_recipe(style, None) is style


def test_recipe_vocabulary_matches_style_schema() -> None:
    """词汇表 ↔ 样式 schema 同口径（收一个渲染器不消费的字段就是让文档说谎）。"""
    style_fields = set(WorkflowV2TimelineSubtitleStyle.model_fields)
    recipe_fields = set(ReplicaSubtitleRecipeV2.model_fields)
    assert recipe_fields == style_fields


# ---------------------------------------------------------------------------
# 内置库
# ---------------------------------------------------------------------------


def test_load_recipes_scans_real_catalog() -> None:
    recipes = load_recipes()
    ids = {r.recipe_id for r in recipes}
    assert {"bottom-bold", "top-tag", "center-stage", "karaoke-tight", "amber-emphasis"} <= ids
    for recipe in recipes:
        assert recipe.subtitle.applied_fields(), f"{recipe.recipe_id} 设置了维度才算配方"


def test_default_recipe_is_bottom_bold() -> None:
    default = default_recipe()
    assert default.recipe_id == rc.DEFAULT_RECIPE_ID
    assert default.subtitle.font_size == 42


def test_load_recipes_missing_catalog_raises(tmp_path: Path) -> None:
    with pytest.raises(rc.RecipeError, match="not found"):
        load_recipes(tmp_path)


def test_load_recipes_skips_broken_entries(tmp_path: Path) -> None:
    (tmp_path).mkdir(parents=True, exist_ok=True)
    (tmp_path / "catalog.json").write_text(
        json.dumps(
            {
                "recipes": [
                    {"recipe_id": "ok", "font_size": 30},
                    {"recipe_id": "", "font_size": 30},  # 缺 id → 跳过
                    {"recipe_id": "bad", "font_size": 999},  # 越界 → 跳过
                    "not-a-dict",  # 坏条目 → 跳过
                ]
            }
        ),
        encoding="utf-8",
    )
    recipes = load_recipes(tmp_path)
    assert [r.recipe_id for r in recipes] == ["ok"]


# ---------------------------------------------------------------------------
# 编译层应用
# ---------------------------------------------------------------------------


def _feasible_blueprint() -> ReplicaBlueprintContentV2:
    return ReplicaBlueprintContentV2(
        aspect="9:16",
        duration_seconds=6.0,
        shots=[
            ReplicaShotV2(index=1, start_seconds=0.0, end_seconds=2.0, on_screen_text="A"),
            ReplicaShotV2(index=2, start_seconds=3.0, end_seconds=5.0, on_screen_text="B"),
        ],
        beats=[ReplicaBeatV2(beat_id="b1", role="hook", start_seconds=0.0, end_seconds=6.0)],
    )


def _cues(plan):
    return [c for c in plan.timeline.clips if c.clip_type == "subtitle"]


def test_compiled_cues_default_without_recipe() -> None:
    blueprint = _feasible_blueprint()
    plan = plan_direct_execute_render(blueprint, plan_direct_execute(blueprint))

    cue = _cues(plan)[0]
    style = cue.subtitle_style
    assert (style.font_size, style.color, style.position) == (42, "#FFFFFF", "bottom_center")
    assert (style.lead_seconds, style.tail_seconds, style.handoff) == (0.1, 0.2, "cut")


def test_compiled_cues_apply_recipe_dimensions() -> None:
    blueprint = _feasible_blueprint()
    gate = plan_direct_execute(blueprint)
    recipe = next(r for r in load_recipes() if r.recipe_id == "amber-emphasis")

    plan = plan_direct_execute_render(blueprint, gate, recipe=recipe)

    for cue in _cues(plan):
        style = cue.subtitle_style
        assert (style.font_size, style.color) == (40, "#FFC658")
    # lead/tail 进可见窗（配方 0.1/0.2 → 首 cue 可见头 -0.1 钳到 0）
    first = _cues(plan)[0]
    assert first.metadata["visible_start_seconds"] == 0.0


def test_recipe_lead_tail_override_visible_window() -> None:
    """karaoke-tight（lead/tail=0）让可见窗等于语义窗——配方真实改变成片时间。"""
    blueprint = _feasible_blueprint()
    gate = plan_direct_execute(blueprint)
    recipe = next(r for r in load_recipes() if r.recipe_id == "karaoke-tight")

    plan = plan_direct_execute_render(blueprint, gate, recipe=recipe)

    for cue in _cues(plan):
        assert cue.metadata["visible_start_seconds"] == cue.start_time
        assert cue.metadata["visible_end_seconds"] == round(cue.start_time + cue.duration, 3)


def test_top_tag_recipe_moves_position() -> None:
    blueprint = _feasible_blueprint()
    recipe = next(r for r in load_recipes() if r.recipe_id == "top-tag")
    plan = plan_direct_execute_render(
        blueprint, plan_direct_execute(blueprint), recipe=recipe
    )
    assert all(c.subtitle_style.position == "top_center" for c in _cues(plan))


# ---------------------------------------------------------------------------
# 变体 = skill × recipe
# ---------------------------------------------------------------------------


def _variant(recipe_id: str = "") -> va.StyleVariant:
    return va.StyleVariant(
        variant_id="v0",
        skill_ids=("gentle-everyday-vlog",),
        names=("温柔日常",),
        score=1.0,
        rationale="匹配关键词：日常",
        recipe_id=recipe_id,
    )


def test_attach_recipes_rotates_deterministically() -> None:
    recipes = load_recipes()
    first = va.attach_recipes([_variant(), _variant(), _variant()], recipes, seed_material="s")

    assert [v.recipe_id for v in first] == [r.recipe_id for r in recipes[:3]]
    assert first[0].recipe_id != first[1].recipe_id  # 相邻变体配方不同（差异可感知）
    assert "样式配方：" in first[0].rationale
    # 确定性：同输入同输出
    again = va.attach_recipes([_variant(), _variant(), _variant()], recipes, seed_material="s")
    assert [v.variant_id for v in first] == [v.variant_id for v in again]


def test_attach_recipes_empty_library_keeps_variants() -> None:
    kept = va.attach_recipes([_variant()], [])
    assert kept[0].recipe_id == ""
    assert kept[0].variant_id == "v0"


def test_attach_recipes_missing_library_degrades() -> None:
    """库目录缺失 → 变体保持无配方（库是增强不是依赖）。"""
    from app.services.replica import recipe as recipe_module

    original = recipe_module._DEFAULT_RECIPES_DIR
    recipe_module._DEFAULT_RECIPES_DIR = original / "does-not-exist"
    try:
        kept = va.attach_recipes([_variant()])
    finally:
        recipe_module._DEFAULT_RECIPES_DIR = original
    assert kept[0].recipe_id == ""


def test_plan_style_variants_carries_distinct_recipes() -> None:
    variants = va.plan_style_variants(_feasible_blueprint(), n=3)

    assert len(variants) == 3
    recipe_ids = [v.recipe_id for v in variants]
    assert all(recipe_ids), "每个变体都应带配方"
    assert len(set(recipe_ids)) == len(recipe_ids), "相邻变体配方必须不同"


# ---------------------------------------------------------------------------
# 端点契约
# ---------------------------------------------------------------------------


@pytest.fixture
def recipe_client():
    app = FastAPI()
    from app.api.v1.endpoints import replica as replica_endpoint

    app.include_router(replica_endpoint.router)
    return TestClient(app)


def test_recipes_endpoint_lists_catalog(recipe_client) -> None:
    response = recipe_client.get("/replica/blueprint/recipes")

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["success"] is True
    ids = {r["recipe_id"] for r in body["recipes"]}
    assert "amber-emphasis" in ids
    entry = next(r for r in body["recipes"] if r["recipe_id"] == "amber-emphasis")
    assert entry["subtitle"]["color"] == "#FFC658"


def test_recipe_export_import_roundtrip_over_http(recipe_client) -> None:
    recipe = _recipe()
    exported = recipe_client.post(
        "/replica/blueprint/recipe/export", json={"recipe": recipe.model_dump(mode="json")}
    )
    assert exported.status_code == 200, exported.text
    text = exported.json()["adrecipe"]

    imported = recipe_client.post("/replica/blueprint/recipe/import", json={"adrecipe": text})
    assert imported.status_code == 200, imported.text
    assert imported.json()["recipe"] == recipe.model_dump(mode="json")


def test_recipe_import_rejects_unknown_dimension(recipe_client) -> None:
    text = adrecipe_from_recipe(_recipe()).replace(
        "<subtitle ", '<subtitle motion="whip-pan" ', 1
    )
    response = recipe_client.post("/replica/blueprint/recipe/import", json={"adrecipe": text})
    assert response.status_code == 422, response.text


def test_direct_execute_endpoint_accepts_recipe(recipe_client) -> None:
    blueprint = _feasible_blueprint()
    plan = plan_direct_execute(blueprint).to_dict()
    recipe = next(r for r in load_recipes() if r.recipe_id == "top-tag")

    response = recipe_client.post(
        "/replica/blueprint/direct-execute",
        json={
            "blueprint": blueprint.model_dump(mode="json"),
            "plan": plan,
            "recipe": recipe.model_dump(mode="json"),
        },
    )

    assert response.status_code == 200, response.text
    cues = [c for c in response.json()["timeline"]["clips"] if c["clip_type"] == "subtitle"]
    assert all(c["subtitle_style"]["position"] == "top_center" for c in cues)


def test_direct_execute_endpoint_rejects_bad_recipe(recipe_client) -> None:
    response = recipe_client.post(
        "/replica/blueprint/direct-execute",
        json={
            "blueprint": _feasible_blueprint().model_dump(mode="json"),
            "plan": plan_direct_execute(_feasible_blueprint()).to_dict(),
            "recipe": {"recipe_id": "x", "subtitle": {"font_size": 999}},
        },
    )
    assert response.status_code == 422, response.text


def test_variant_render_plans_differ_in_subtitle_style(recipe_client) -> None:
    """G5 的兑付：变体渲染计划之间第一次有**看得见的样式差异**。"""
    response = recipe_client.post(
        "/replica/blueprint/variant-render-plans",
        json={
            "blueprint": _feasible_blueprint().model_dump(mode="json"),
            "n": 3,
            "render_representatives": 3,
        },
    )

    assert response.status_code == 200, response.text
    entries = [e for e in response.json()["variants"] if e.get("timeline")]
    assert len(entries) >= 2
    signatures = set()
    for entry in entries:
        assert entry["recipe_id"], "每个变体计划都应带配方"
        cues = [c for c in entry["timeline"]["clips"] if c["clip_type"] == "subtitle"]
        style = cues[0]["subtitle_style"]
        signatures.add((style["font_size"], style["color"], style["position"]))
    assert len(signatures) >= 2, "代表变体的字幕样式签名必须互不相同"


def test_style_variants_endpoint_carries_recipe_fields(recipe_client) -> None:
    response = recipe_client.post(
        "/replica/blueprint/style-variants",
        json={"blueprint": _feasible_blueprint().model_dump(mode="json"), "n": 2},
    )
    assert response.status_code == 200, response.text
    for variant in response.json()["variants"]:
        assert variant["recipe_id"]
        assert variant["recipe_name"]
