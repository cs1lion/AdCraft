"""Unit tests for the direct-execute render bridge (ADR 0010 R3 后端半边).

两层锁定：

- 服务层（fake 的 v2 timeline/render 服务）：编译 → 解析回填 → 剥哨兵 →
  写盘（乐观锁）→ start_render 的编排正确性，含非可行拒绝与服务错误
  透传；
- 端点层（dependency_overrides）：路由、序列化与错误映射（422 非可行 /
  422 坏蓝图 / 404 时间线服务错误）。

设计依据：docs/plans/replica-completion-research.md G1（最后一公里）+
ADR 0010（复用剪辑域 start_render，不建第二执行链）。
"""

from __future__ import annotations

from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.v1.endpoints import replica as replica_endpoint
from app.schemas.agent_canvas_ad_media import ReplicaBlueprintContentV2
from app.schemas.workflow_v2 import (
    WorkflowV2Timeline,
    WorkflowV2TimelineRenderRequest,
    WorkflowV2TimelineRenderStartResponse,
    WorkflowV2TimelineResponse,
    WorkflowV2TimelineTrack,
    WorkflowV2TimelineUpdateRequest,
    WorkflowV2TimelineUpdateResponse,
)
from app.services.replica.direct_execute_bridge import (
    ReplicaLibraryResolution,
    ReplicaRenderNotFeasible,
    render_replica_blueprint,
    strip_unresolved_clips,
)
from app.services.v2_final_composition_timeline import V2FinalCompositionTimelineError


def _feasible_blueprint(**overrides: Any) -> ReplicaBlueprintContentV2:
    """纯字幕片：镜头全是屏上文字、无台词无主体替换 → 零模型费可行。"""
    payload: dict[str, Any] = {
        "replica_goal": "纯字幕促销片直出",
        "aspect": "9:16",
        "duration_seconds": 6.0,
        "shots": [
            {
                "index": i,
                "start_seconds": start,
                "end_seconds": end,
                "on_screen_text": text,
                "subject_action": "",
            }
            for i, (start, end, text) in enumerate(
                [
                    (0.0, 1.5, "HALF PRICE SALE"),
                    (1.5, 3.0, "NEW PRODUCT"),
                    (3.0, 4.5, "DAY 7 RESULT"),
                    (4.5, 6.0, "BUY NOW"),
                ],
                start=1,
            )
        ],
        "beats": [
            {"beat_id": "b1", "role": "hook", "line": "",
             "start_seconds": 0.0, "end_seconds": 1.5},
            {"beat_id": "b2", "role": "proof", "line": "",
             "start_seconds": 1.5, "end_seconds": 4.5},
            {"beat_id": "b3", "role": "cta", "line": "",
             "start_seconds": 4.5, "end_seconds": 6.0},
        ],
        "systems_captions": "底部大字",
        "systems_music": "促销电子",
        "systems_sfx": ["whoosh"],
    }
    payload.update(overrides)
    return ReplicaBlueprintContentV2(**payload)


class _FakeTimelineService:
    """录制 get/save 调用的 v2 final-composition timeline 服务替身。"""

    def __init__(self, *, version: int = 3, error: V2FinalCompositionTimelineError | None = None) -> None:
        self.version = version
        self.error = error
        self.get_calls: list[str] = []
        self.saved: WorkflowV2TimelineUpdateRequest | None = None

    def _raise(self) -> None:
        if self.error is not None:
            raise self.error

    def get_timeline(self, workflow_id: str) -> WorkflowV2TimelineResponse:
        self.get_calls.append(workflow_id)
        self._raise()
        return WorkflowV2TimelineResponse(
            workflow_id=workflow_id,
            item_id="item_fc",
            timeline=WorkflowV2Timeline(
                timeline_id="tl-current",
                version=self.version,
                duration_seconds=0,
                tracks=[
                    WorkflowV2TimelineTrack(track_id="track-video", track_type="video", order=1)
                ],
                clips=[],
            ),
            source="saved",
            runtime={},
        )

    def save_timeline(
        self, workflow_id: str, request: WorkflowV2TimelineUpdateRequest
    ) -> WorkflowV2TimelineUpdateResponse:
        self.saved = request
        self._raise()
        return WorkflowV2TimelineUpdateResponse(
            workflow_id=workflow_id,
            timeline=request.timeline.model_copy(
                update={"version": self.version + 1}, deep=True
            ),
            changed_clip_ids=[],
            runtime={},
        )


class _FakeRenderService:
    """录制 start_render 调用的耐久渲染服务替身。"""

    def __init__(
        self,
        *,
        error: V2FinalCompositionTimelineError | None = None,
        reused: bool = False,
        reuse_kind: str | None = None,
    ) -> None:
        self.error = error
        # D7: 底层 v2 渲染服务的幂等复用事实（同一指纹 → 同一 render）
        self.reused = reused
        self.reuse_kind = reuse_kind
        self.calls: list[WorkflowV2TimelineRenderRequest] = []

    def _raise(self) -> None:
        if self.error is not None:
            raise self.error

    def start_render(
        self, workflow_id: str, request: WorkflowV2TimelineRenderRequest
    ) -> WorkflowV2TimelineRenderStartResponse:
        self.calls.append(request)
        self._raise()
        return WorkflowV2TimelineRenderStartResponse(
            workflow_id=workflow_id,
            render_id="render_bridge01",
            status="queued",
            timeline_id=request.timeline_id,
            timeline_version=request.timeline_version,
            events_cursor=9,
            reused=self.reused,
            reused_from_render_id="render_bridge01" if self.reused else None,
            reuse_kind=self.reuse_kind,
        )


def _services(**kwargs: Any) -> tuple[_FakeTimelineService, _FakeRenderService]:
    timeline_error = kwargs.pop("timeline_error", None)
    render_error = kwargs.pop("render_error", None)
    render_reused = kwargs.pop("render_reused", False)
    render_reuse_kind = kwargs.pop("render_reuse_kind", None)
    return (
        _FakeTimelineService(error=timeline_error, **kwargs),
        _FakeRenderService(
            error=render_error, reused=render_reused, reuse_kind=render_reuse_kind
        ),
    )


# ---------------------------------------------------------------------------
# 服务层：编排正确性
# ---------------------------------------------------------------------------

def test_bridge_passes_through_render_reuse_fact() -> None:
    """D7: 同一蓝图重复提交时，底层按组合指纹复用同一 render（在途或已完成
    发布）——桥必须把这个事实透出，否则前端只看到"新 render_id"，无法如实
    告知用户"未重复出片"（真幂等的可观测半边）。"""
    timeline_service, render_service = _services(
        version=3, render_reused=True, render_reuse_kind="active_render"
    )
    blueprint = _feasible_blueprint()

    outcome = render_replica_blueprint(
        "wf-1",
        blueprint,
        timeline_service=timeline_service,
        render_service=render_service,
    )

    assert outcome.render_id == "render_bridge01"
    assert outcome.reused is True
    assert outcome.reused_from_render_id == "render_bridge01"
    assert outcome.reuse_kind == "active_render"


def test_bridge_defaults_reuse_flags_off() -> None:
    """没有复用时字段如实为 False/None（不假装幂等）。"""
    timeline_service, render_service = _services(version=3)
    outcome = render_replica_blueprint(
        "wf-1",
        _feasible_blueprint(),
        timeline_service=timeline_service,
        render_service=render_service,
    )
    assert outcome.reused is False
    assert outcome.reused_from_render_id is None
    assert outcome.reuse_kind is None



def test_bridge_saves_replica_timeline_and_starts_durable_render() -> None:
    """可行蓝图 → 以当前版本为 expected_version 写盘 → start_render 用保存后的版本。"""
    timeline_service, render_service = _services(version=3)
    blueprint = _feasible_blueprint()

    outcome = render_replica_blueprint(
        "wf_bridge",
        blueprint,
        timeline_service=timeline_service,
        render_service=render_service,
    )

    # 写盘：expected_version 取自当前时间线（乐观锁），时间线内容来自复刻编译层
    assert timeline_service.get_calls == ["wf_bridge"]
    assert timeline_service.saved is not None
    assert timeline_service.saved.expected_version == 3
    saved_timeline = timeline_service.saved.timeline
    assert saved_timeline.timeline_id == "replica-direct-execute-1"
    assert saved_timeline.metadata.get("origin") == "replica-direct-execute"
    assert saved_timeline.metadata.get("needs_placeholder_video") is True
    # 四条相邻等长 cue 被 0.4s 合并规则并成一条（字幕不闪跳，既有行为）
    assert [c.clip_id for c in saved_timeline.clips] == [
        "sub_s1+sub_s2+sub_s3+sub_s4",
    ]

    # 渲染：用保存后的 timeline_id/version（4 = 当前 3 + 1）
    assert len(render_service.calls) == 1
    assert render_service.calls[0].timeline_id == "replica-direct-execute-1"
    assert render_service.calls[0].timeline_version == 4

    # 结果：替换事实与待解析意图都透出
    assert outcome.workflow_id == "wf_bridge"
    assert outcome.render_id == "render_bridge01"
    assert outcome.status == "queued"
    assert outcome.previous_timeline_version == 3
    assert outcome.timeline_version == 4
    assert outcome.subtitle_cue_count == 1  # 四条相邻 cue 合并后为一条
    assert outcome.needs_placeholder_video is True


def test_bridge_drops_unresolved_sentinel_clips_before_saving() -> None:
    """未解析库素材的哨兵 clip 写盘前剥掉（进了 v2 时间线会被 404 拒）。"""
    timeline_service, render_service = _services()
    blueprint = _feasible_blueprint()  # systems_music + systems_sfx → 两个哨兵 clip

    outcome = render_replica_blueprint(
        "wf_bridge",
        blueprint,
        timeline_service=timeline_service,
        render_service=render_service,
    )

    assert timeline_service.saved is not None
    saved_clip_ids = [c.clip_id for c in timeline_service.saved.timeline.clips]
    assert "bgm_system" not in saved_clip_ids
    assert "sfx_system" not in saved_clip_ids
    assert set(outcome.dropped_unresolved_clip_ids) == {"bgm_system", "sfx_system"}
    # 剥掉后没有剩余待解析意图（它们已经连同 clip 一起出去了）
    assert outcome.unresolved_assets == ()
    # BGM/SFX 轨一并移除（没有 clip 引用它们）
    saved_track_ids = {t.track_id for t in timeline_service.saved.timeline.tracks}
    assert "track-bgm" not in saved_track_ids
    assert "track-sfx" not in saved_track_ids


def test_bridge_applies_library_resolutions_and_keeps_resolved_clip() -> None:
    """人工解析回填后的 clip 是真实资产 → 保留并参与渲染。"""
    timeline_service, render_service = _services()
    blueprint = _feasible_blueprint()

    outcome = render_replica_blueprint(
        "wf_bridge",
        blueprint,
        library_resolutions=(
            ReplicaLibraryResolution(
                clip_id="bgm_system", asset_id="asset_bgm_1", version_id="ver_bgm_1"
            ),
        ),
        timeline_service=timeline_service,
        render_service=render_service,
    )

    assert timeline_service.saved is not None
    bgm = [c for c in timeline_service.saved.timeline.clips if c.clip_id == "bgm_system"]
    assert len(bgm) == 1
    assert bgm[0].enabled is True
    assert bgm[0].source_asset_id == "asset_bgm_1"
    assert bgm[0].source_version_id == "ver_bgm_1"
    # 只解析了 BGM：SFX 仍未解析 → 被剥掉且如实透出
    assert outcome.dropped_unresolved_clip_ids == ("sfx_system",)
    unresolved_clip_ids = [u["clip_id"] for u in outcome.unresolved_assets]
    assert unresolved_clip_ids == []


def test_bridge_rejects_infeasible_blueprint_without_touching_services() -> None:
    """非可行蓝图：拒绝渲染，且不读不写不渲染（门不降级）。"""
    timeline_service, render_service = _services()
    blueprint = _feasible_blueprint(
        shots=[
            {
                "index": 1,
                "start_seconds": 0.0,
                "end_seconds": 2.0,
                "on_screen_text": "第7天",
                "subject_action": "产品特写",
            }
        ],
        beats=[
            {"beat_id": "b1", "role": "hook", "line": "",
             "start_seconds": 0.0, "end_seconds": 2.0}
        ],
    )

    with pytest.raises(ReplicaRenderNotFeasible) as excinfo:
        render_replica_blueprint(
            "wf_bridge",
            blueprint,
            timeline_service=timeline_service,
            render_service=render_service,
        )

    assert excinfo.value.rejected  # 缺失清单非空
    assert timeline_service.get_calls == []
    assert timeline_service.saved is None
    assert render_service.calls == []


def test_bridge_propagates_timeline_service_error_and_skips_render() -> None:
    """时间线服务错误（如 409 版本冲突）原样透传，渲染不启动。"""
    conflict = V2FinalCompositionTimelineError(
        "v2_timeline_version_conflict",
        "Timeline version does not match expected_version.",
        status_code=409,
    )
    timeline_service, render_service = _services(version=7, timeline_error=conflict)

    with pytest.raises(V2FinalCompositionTimelineError) as excinfo:
        render_replica_blueprint(
            "wf_bridge",
            _feasible_blueprint(),
            timeline_service=timeline_service,
            render_service=render_service,
        )

    assert excinfo.value.code == "v2_timeline_version_conflict"
    assert render_service.calls == []


def test_strip_unresolved_clips_is_noop_when_clean() -> None:
    """没有哨兵 clip 的时间线原样返回（同一对象，零复制）。"""
    timeline_service, _render = _services()
    from app.services.replica.direct_execute import plan_direct_execute
    from app.services.replica.direct_execute_render import plan_direct_execute_render

    blueprint = _feasible_blueprint(systems_music="", systems_sfx=[])
    plan = plan_direct_execute_render(blueprint, plan_direct_execute(blueprint))

    same, dropped = strip_unresolved_clips(plan.timeline)

    assert dropped == ()
    assert same is plan.timeline


# ---------------------------------------------------------------------------
# 端点层：路由、序列化与错误映射
# ---------------------------------------------------------------------------


@pytest.fixture
def bridge_client():
    app = FastAPI()
    app.include_router(replica_endpoint.router)
    timeline_service = _FakeTimelineService()
    render_service = _FakeRenderService()
    app.dependency_overrides[replica_endpoint.get_replica_final_timeline_service] = (
        lambda: timeline_service
    )
    app.dependency_overrides[replica_endpoint.get_replica_final_render_service] = (
        lambda: render_service
    )
    return TestClient(app), timeline_service, render_service


def test_render_bridge_endpoint_happy_path(bridge_client) -> None:
    client, _timeline_service, render_service = bridge_client

    response = client.post(
        "/replica/blueprint/direct-execute/render",
        json={
            "workflow_id": "wf_bridge",
            "blueprint": _feasible_blueprint().model_dump(mode="json"),
        },
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["success"] is True
    assert body["feasible"] is True
    assert body["render_id"] == "render_bridge01"
    assert body["status"] == "queued"
    assert body["previous_timeline_version"] == 3
    assert body["timeline_version"] == 4
    assert body["subtitle_cue_count"] == 1  # 四条相邻 cue 合并后为一条
    assert body["needs_placeholder_video"] is True
    # 哨兵 clip 被剥掉这件事必须出现在响应里
    assert set(body["dropped_unresolved_clip_ids"]) == {"bgm_system", "sfx_system"}
    assert render_service.calls and render_service.calls[0].timeline_version == 4


def test_render_bridge_endpoint_rejects_infeasible(bridge_client) -> None:
    client, timeline_service, render_service = bridge_client

    response = client.post(
        "/replica/blueprint/direct-execute/render",
        json={
            "workflow_id": "wf_bridge",
            "blueprint": _feasible_blueprint(
                shots=[
                    {
                        "index": 1,
                        "start_seconds": 0.0,
                        "end_seconds": 2.0,
                        "on_screen_text": "第7天",
                        "subject_action": "产品特写",
                    }
                ],
            ).model_dump(mode="json"),
        },
    )

    assert response.status_code == 422, response.text
    body = response.json()
    detail = body["detail"]
    assert detail["error_type"] == "direct_execute_not_feasible"
    assert detail["rejected"]
    # 拒绝即拒绝：时间线没读没写，渲染没启动
    assert timeline_service.get_calls == []
    assert render_service.calls == []


def test_render_bridge_endpoint_rejects_bad_blueprint(bridge_client) -> None:
    client, _timeline_service, _render_service = bridge_client

    response = client.post(
        "/replica/blueprint/direct-execute/render",
        json={"workflow_id": "wf_bridge", "blueprint": {"slots": "oops"}},
    )

    assert response.status_code == 422, response.text


def test_render_bridge_endpoint_rejects_incomplete_resolution(bridge_client) -> None:
    client, _timeline_service, _render_service = bridge_client

    response = client.post(
        "/replica/blueprint/direct-execute/render",
        json={
            "workflow_id": "wf_bridge",
            "blueprint": _feasible_blueprint().model_dump(mode="json"),
            "library_resolutions": [{"clip_id": "bgm_system", "asset_id": "a1"}],
        },
    )

    assert response.status_code == 422, response.text


def test_render_bridge_endpoint_maps_timeline_error(bridge_client) -> None:
    client, _timeline_service, render_service = bridge_client
    _timeline_service.error = V2FinalCompositionTimelineError(
        "workflow_not_found", "Workflow not found: wf_missing", status_code=404
    )

    response = client.post(
        "/replica/blueprint/direct-execute/render",
        json={
            "workflow_id": "wf_missing",
            "blueprint": _feasible_blueprint().model_dump(mode="json"),
        },
    )

    assert response.status_code == 404, response.text
    assert response.json()["detail"]["code"] == "workflow_not_found"
    assert render_service.calls == []


@pytest.mark.integration
@pytest.mark.parametrize("font_size,color", [(40, "#FFC658"), (56, "#123456")])
def test_actual_render_accepts_recipe_and_matches_preview(bridge_client, font_size, color):
    """Locks HTTP recipe propagation all the way to the saved canonical timeline."""
    from app.services.replica.direct_execute import plan_direct_execute
    from app.services.replica.direct_execute_render import plan_direct_execute_render
    from app.services.replica.recipe import ReplicaRecipeV2

    client, timeline_service, _render = bridge_client
    blueprint = _feasible_blueprint(systems_music="", systems_sfx=[])
    recipe = ReplicaRecipeV2.model_validate({
        "recipe_id": "review-recipe", "name": "review",
        "subtitle": {"font_size": font_size, "color": color},
    })
    preview = plan_direct_execute_render(blueprint, plan_direct_execute(blueprint), recipe=recipe)
    response = client.post("/replica/blueprint/direct-execute/render", json={
        "workflow_id": "wf_bridge", "blueprint": blueprint.model_dump(mode="json"),
        "recipe": recipe.model_dump(mode="json"),
    })
    assert response.status_code == 200, response.text
    assert timeline_service.saved is not None
    assert timeline_service.saved.timeline.clips == preview.timeline.clips


@pytest.mark.integration
def test_actual_render_rejects_bad_recipe_before_saving(bridge_client):
    client, timeline_service, render_service = bridge_client
    response = client.post("/replica/blueprint/direct-execute/render", json={
        "workflow_id": "wf_bridge", "blueprint": _feasible_blueprint().model_dump(mode="json"),
        "recipe": {"recipe_id": "bad", "name": "bad", "subtitle": {"font_size": 200}},
    })
    assert response.status_code == 422
    assert timeline_service.saved is None
    assert render_service.calls == []
