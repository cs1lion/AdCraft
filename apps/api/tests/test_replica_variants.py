"""Unit tests for the style-variant engine (Jev 式风格导演的确定性实现).

Covers: catalog scanning (real repo catalog), deterministic scoring that
surfaces relevant skills, ranked single-skill recommendation, weighted
mixing (reproducible, non-applicable for multi-skill), clamping, and the
endpoint contract.

Design rationale: docs/plans/hypit-replica-research.md §4.4 (Jev+Hypit).
"""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.schemas.agent_canvas_ad_media import ReplicaBlueprintContentV2
from app.services.replica import variants as va


def _blueprint(**overrides) -> ReplicaBlueprintContentV2:
    payload = {
        "replica_goal": "日常 vlog 手持观察，温柔日常感",
        "whole_piece_reading": "亲密手持、生活化的日常记录",
        "format_name": "lifestyle-vlog",
    }
    payload.update(overrides)
    return ReplicaBlueprintContentV2(**payload)


# ---------------------------------------------------------------------------
# 目录扫描
# ---------------------------------------------------------------------------


def test_load_style_skills_scans_real_catalog() -> None:
    skills = va.load_style_skills()
    ids = {s.skill_id for s in skills}
    assert len(skills) >= 30  # 六大类 35 个 + platform-default
    assert "gentle-everyday-vlog" in ids
    assert "platform-default" in ids
    gentle = next(s for s in skills if s.skill_id == "gentle-everyday-vlog")
    assert gentle.name  # SKILL.md frontmatter 的中文名
    assert gentle.description


def test_load_style_skills_missing_catalog_raises(tmp_path) -> None:
    with pytest.raises(va.StyleVariantError, match="not found"):
        va.load_style_skills(tmp_path)


# ---------------------------------------------------------------------------
# 打分与变体
# ---------------------------------------------------------------------------


def test_scoring_surfaces_relevant_skill() -> None:
    scored = dict(
        (s.skill_id, score) for s, score in va.score_skills(_blueprint(), va.load_style_skills())
    )
    top = max(scored, key=scored.get)
    assert top == "gentle-everyday-vlog"


def test_plan_variants_single_is_ranked_and_deterministic() -> None:
    first = va.plan_style_variants(_blueprint(), n=4)
    again = va.plan_style_variants(_blueprint(), n=4)
    assert [v.variant_id for v in first] == [v.variant_id for v in again]
    assert first[0].skill_ids == ("gentle-everyday-vlog",)
    assert all(v.mixable_applied for v in first)
    # 单风格为排名序（分数不升）
    assert all(a.score >= b.score for a, b in zip(first, first[1:]))


def test_plan_variants_mixing_is_weighted_and_reproducible() -> None:
    mixed = va.plan_style_variants(_blueprint(), n=3, mix_size=2)
    assert len(mixed) == 3
    assert all(len(v.skill_ids) == 2 for v in mixed)
    assert all(not v.mixable_applied for v in mixed)  # 多风格激活未支持
    again = va.plan_style_variants(_blueprint(), n=3, mix_size=2)
    assert [v.skill_ids for v in mixed] == [v.skill_ids for v in again]
    # 组合去重
    assert len({v.skill_ids for v in mixed}) == 3


def test_plan_variants_platform_default_never_recommended() -> None:
    for variant in va.plan_style_variants(
        ReplicaBlueprintContentV2(), n=8, mix_size=2
    ):
        assert "platform-default" not in variant.skill_ids


def test_plan_variants_empty_blueprint_still_returns_candidates() -> None:
    variants = va.plan_style_variants(ReplicaBlueprintContentV2(), n=3)
    assert 0 < len(variants) <= 3  # 无命中也按库序给候选（rationale 说明）


def test_plan_variants_clamps_arguments() -> None:
    with pytest.raises(va.StyleVariantError, match="n out of range"):
        va.plan_style_variants(_blueprint(), n=0)
    with pytest.raises(va.StyleVariantError, match="mix_size out of range"):
        va.plan_style_variants(_blueprint(), mix_size=4)


# ---------------------------------------------------------------------------
# 端点契约
# ---------------------------------------------------------------------------


@pytest.fixture
def variants_client():
    from app.api.v1.endpoints import replica as replica_endpoint

    app = FastAPI()
    app.include_router(replica_endpoint.router)
    return TestClient(app)


def test_style_variants_endpoint(variants_client) -> None:
    response = variants_client.post(
        "/replica/blueprint/style-variants",
        json={"blueprint": _blueprint().model_dump(mode="json"), "n": 3},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["success"] is True
    assert len(body["variants"]) == 3
    assert body["variants"][0]["skill_ids"] == ["gentle-everyday-vlog"]
    assert body["variants"][0]["mixable_applied"] is True


def test_style_variants_endpoint_rejects_bad_blueprint(variants_client) -> None:
    response = variants_client.post(
        "/replica/blueprint/style-variants",
        json={"blueprint": {"blueprint_version": "x"}, "n": 3},
    )
    assert response.status_code == 422, response.text


# ---------------------------------------------------------------------------
# 变体 → 重编译渲染计划（D：组件化替换 × direct-execute 汇合点）
# ---------------------------------------------------------------------------


def test_variant_render_plans_endpoint_returns_representative_timelines(variants_client) -> None:
    blueprint = _blueprint()
    # 补纯字幕镜头使可行性门可判 feasible
    blueprint = blueprint.model_copy(
        update={
            "shots": [
                {
                    "index": 1, "start_seconds": 0.0, "end_seconds": 3.0,
                    "on_screen_text": "HALF PRICE SALE", "subject_action": "",
                }
            ],
            "systems_captions": "底部大字",
        }
    )
    response = variants_client.post(
        "/replica/blueprint/variant-render-plans",
        json={"blueprint": blueprint.model_dump(mode="json"), "n": 4,
              "render_representatives": 2},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert len(body["variants"]) == 4
    # 只有前 render_representatives 个代表携带时间线（低成本审片）
    with_timeline = [v for v in body["variants"] if v["timeline"] is not None]
    assert len(with_timeline) == 2
    # 每个变体的风格槽位都应用了各自候选
    assert all(v["skill_ids"] for v in body["variants"])


def test_variant_render_plans_endpoint_rejects_bad_blueprint(variants_client) -> None:
    response = variants_client.post(
        "/replica/blueprint/variant-render-plans",
        json={"blueprint": {"slots": 1}, "n": 2},
    )
    assert response.status_code == 422, response.text
