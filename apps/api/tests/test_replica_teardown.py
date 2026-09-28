"""Unit tests for the 拉片复刻 reference teardown (MVP slice).

Covers: the mocked-LLM analysis + synthesis flow, normalize 兜底 (LLM output
is untrusted), the deterministic replica storyboard draft, duration gating,
and the HTTP endpoint contract (asset_id / multipart / validation). No
network and no ffmpeg: the LLM boundary, metadata extraction and keyframe
extraction are monkeypatched.

Design rationale: docs/plans/hypit-replica-research.md (§2, §6.3).
"""

from __future__ import annotations

import json

import pytest

from app.services.replica.teardown import (
    DEFAULT_NUM_FRAMES,
    MAX_TEARDOWN_DURATION_SECONDS,
    AnalysisError,
    TeardownFrameAnalysis,
    TeardownReport,
    TeardownResult,
    TeardownRhythm,
    TeardownShot,
    TeardownSystems,
    StructureBeat,
    analyze_reference_teardown,
    build_replica_draft,
)
from app.services.replica import teardown as _teardown_module
from app.services.scene3d.reference_upload import VideoMetadata


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------


def _metadata(duration: float = 12.0) -> VideoMetadata:
    return VideoMetadata(
        duration_seconds=duration,
        width=1080,
        height=1920,
        frame_rate=30.0,
        frame_count=int(duration * 30),
        codec_name="h264",
        file_size_bytes=1024 * 1024,
    )


def _frame_analysis_json(on_screen_text: str = "") -> str:
    return json.dumps(
        {
            "scene_type": "indoor",
            "environment_description": "bright studio desk",
            "lighting": "soft",
            "camera_angle": "eye-level",
            "shot_size": "closeup",
            "camera_motion_hint": "static",
            "characters": [
                {
                    "description": "young woman holding a cleanser",
                    "position_hint": "center",
                    "action": "talking",
                    "facing": "toward camera",
                }
            ],
            "props": ["cleanser bottle"],
            "on_screen_text": on_screen_text,
            "notable_elements": "product label faces the lens",
        }
    )


def _synthesis_dict() -> dict:
    return {
        "whole_piece_reading": "前3秒用错误示范制造焦虑，中段产品证明，结尾CTA。",
        "format_name": "product-comparison",
        "beats": [
            {"role": "hook", "description": "错误示范抓注意力", "start_seconds": 0.0, "end_seconds": 3.0},
            {"role": "proof", "description": "连续7天对比", "start_seconds": 3.0, "end_seconds": 9.0},
            {"role": "cta", "description": "引导下单", "start_seconds": 9.0, "end_seconds": 12.0},
        ],
        "shots": [
            {"index": 2, "start_seconds": 3.0, "end_seconds": 7.5, "shot_size": "medium",
             "camera_motion": "pushing_in", "subject_action": "涂抹对比", "on_screen_text": "第3天",
             "transition_to_next": "dissolve"},
            {"index": 1, "start_seconds": 0.0, "end_seconds": 3.0, "shot_size": "closeup",
             "camera_motion": "static", "subject_action": "唇部特写", "on_screen_text": "别再这样洗脸",
             "transition_to_next": "cut"},
        ],
        "rhythm": {"avg_shot_seconds": 0.0, "cut_points_seconds": [], "energy_curve": "前快后缓"},
        "systems": {
            "captions": "底部关键词高亮",
            "music": "轻快电子",
            "graphics": ["价格贴: 产品提到时弹入"],
            "sfx": ["切换 whoosh"],
        },
    }


class _FakeClient:
    def close(self) -> None:  # pragma: no cover - trivial
        pass


@pytest.fixture
def mocked_teardown(monkeypatch, tmp_path):
    """Monkeypatch the teardown boundary: metadata, keyframes, LLM.

    Creates a real (dummy-content) video file so the service's existence
    check passes, and returns (calls, synthesis_payload, video_path) where
    synthesis_payload allows tests to override the synthesis JSON.
    """
    video = tmp_path / "reference.mp4"
    video.write_bytes(b"fake-video-bytes")
    calls: list[dict] = []
    synthesis_payload = {"json": _synthesis_dict()}
    frame_text = {"on_screen": "别再这样洗脸"}

    def fake_call(*, client, base_url, api_key, model, system_prompt, user_text, image_path, max_tokens, **kwargs):
        calls.append({"has_image": image_path is not None, "system": system_prompt, "user": user_text})
        if image_path is not None:
            return _frame_analysis_json(frame_text["on_screen"])
        return json.dumps(synthesis_payload["json"], ensure_ascii=False)

    monkeypatch.setattr(_teardown_module, "_call_multimodal_llm", fake_call)
    monkeypatch.setattr(
        _teardown_module,
        "_build_llm_client",
        lambda: (_FakeClient(), "http://llm.test", "key", "test-model"),
    )
    monkeypatch.setattr(_teardown_module, "extract_metadata", lambda path: _metadata())
    monkeypatch.setattr(
        _teardown_module,
        "extract_keyframes_from_video",
        lambda video_path, output_dir, num_keyframes: [
            str(output_dir / f"keyframe_{i:02d}.png") for i in range(num_keyframes)
        ],
    )
    # G6 缓存隔离：默认缓存目录是共享的 media_data_dir——不隔离的话同一
    # 会话里先跑的测试写缓存、后跑的测试命中，"LLM 失败应抛出"这类断言
    # 会被缓存命中悄悄抵消。每个测试一个 tmp 缓存目录。
    monkeypatch.setattr(
        _teardown_module,
        "teardown_cache_dir",
        lambda media_dir: tmp_path / "teardown_cache",
    )
    return calls, synthesis_payload, video


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


def test_analyze_reference_teardown_happy_path(mocked_teardown) -> None:
    _, _, video = mocked_teardown
    result = analyze_reference_teardown(video)

    assert isinstance(result, TeardownResult)
    report = result.report
    assert report.format_name == "product-comparison"
    assert "前3秒" in report.whole_piece_reading
    # shots: re-sorted by start, index re-sequenced
    assert [s.index for s in report.shots] == [1, 2]
    assert report.shots[0].start_seconds == 0.0
    assert report.shots[0].on_screen_text == "别再这样洗脸"
    assert report.shots[1].transition_to_next == "dissolve"
    # rhythm derived: avg from shots (12s / 2 shots), cut points from starts
    assert report.rhythm.avg_shot_seconds == 6.0
    assert 0.0 in report.rhythm.cut_points_seconds
    assert 3.0 in report.rhythm.cut_points_seconds
    # systems
    assert report.systems.captions == "底部关键词高亮"
    assert report.systems.graphics == ["价格贴: 产品提到时弹入"]
    # frames + metadata
    assert result.num_frames_analyzed == DEFAULT_NUM_FRAMES
    assert result.video_metadata.duration_seconds == 12.0
    # honesty constraints always present
    assert any("推断值" in c for c in report.constraints)
    # draft is the bridge into the normal flow
    assert "复刻分镜草稿" in report.replica_storyboard_draft
    assert "镜头表" in report.replica_storyboard_draft


def test_frame_analysis_includes_on_screen_text(mocked_teardown) -> None:
    calls, _, video = mocked_teardown
    result = analyze_reference_teardown(video)
    # 8 frame calls with images + 1 synthesis call without
    assert sum(1 for c in calls if c["has_image"]) == DEFAULT_NUM_FRAMES
    assert result.frame_analyses[0].on_screen_text == "别再这样洗脸"


# ---------------------------------------------------------------------------
# normalize 兜底（LLM 输出不可信）
# ---------------------------------------------------------------------------


def test_normalize_shots_falls_back_to_single_shot() -> None:
    from app.services.replica.teardown import _normalize_shots

    shots = _normalize_shots({"shots": "not-a-list"}, 10.0)
    assert len(shots) == 1
    assert shots[0]["start_seconds"] == 0.0
    assert shots[0]["end_seconds"] == 10.0
    assert shots[0]["index"] == 1


def test_normalize_shots_clamps_and_sequences() -> None:
    from app.services.replica.teardown import _normalize_shots

    shots = _normalize_shots(
        {
            "shots": [
                {"start_seconds": 4.0, "end_seconds": 99.0, "shot_size": "wide"},
                {"start_seconds": -3.0, "end_seconds": 2.0},
                "garbage",
                {"start_seconds": 8.0, "end_seconds": 6.0},  # reversed → swapped
            ]
        },
        10.0,
    )
    assert [s["index"] for s in shots] == [1, 2, 3]
    assert shots[0]["start_seconds"] == 0.0  # clamped from -3
    assert shots[0]["end_seconds"] == 2.0
    assert shots[1]["start_seconds"] == 4.0
    assert shots[1]["end_seconds"] == 10.0  # clamped from 99
    assert shots[1]["shot_size"] == "wide"
    assert shots[2]["start_seconds"] == 6.0  # swapped
    assert shots[2]["end_seconds"] == 8.0


def test_normalize_rhythm_derives_missing_values() -> None:
    from app.services.replica.teardown import _normalize_rhythm

    shots = [
        {"start_seconds": 0.0, "end_seconds": 2.0},
        {"start_seconds": 2.0, "end_seconds": 5.0},
    ]
    rhythm = _normalize_rhythm({"rhythm": {"avg_shot_seconds": 0.0}}, shots, 5.0)
    assert rhythm["avg_shot_seconds"] == 2.5
    assert rhythm["cut_points_seconds"] == [0.0, 2.0]


# ---------------------------------------------------------------------------
# Draft rendering
# ---------------------------------------------------------------------------


def test_build_replica_draft_is_deterministic_and_complete() -> None:
    report = TeardownReport(
        whole_piece_reading="整片解读",
        format_name="talking-head",
        shots=[TeardownShot(index=1, start_seconds=0.0, end_seconds=2.1, shot_size="closeup", camera_motion="static", subject_action="口播", on_screen_text="标题")],
        beats=[StructureBeat(role="hook", description="钩子", start_seconds=0.0, end_seconds=2.1)],
        rhythm=TeardownRhythm(avg_shot_seconds=2.1, cut_points_seconds=[0.0], energy_curve="平"),
        systems=TeardownSystems(captions="底部", music="电子", graphics=["贴片"], sfx=[]),
    )
    draft_a = build_replica_draft(report)
    draft_b = build_replica_draft(report)
    assert draft_a == draft_b  # deterministic: no LLM in the loop
    assert "格式判断：talking-head" in draft_a
    assert "[0.0–2.1s] hook：钩子" in draft_a
    assert "1. [0.0–2.1s] closeup / static — 口播。屏上文字：标题。转场：cut" in draft_a
    assert "字幕：底部" in draft_a
    assert "复刻提示" in draft_a


# ---------------------------------------------------------------------------
# Failure paths
# ---------------------------------------------------------------------------


def test_analyze_teardown_rejects_over_long_video(mocked_teardown, monkeypatch) -> None:
    monkeypatch.setattr(_teardown_module, "extract_metadata", lambda path: _metadata(MAX_TEARDOWN_DURATION_SECONDS + 1))
    with pytest.raises(AnalysisError) as exc:
        analyze_reference_teardown("/fake/long.mp4")  # exists check is not reached
    assert exc.value.error_type == "input"


def test_analyze_teardown_missing_video(mocked_teardown) -> None:
    with pytest.raises(AnalysisError) as exc:
        analyze_reference_teardown("/nonexistent/video.mp4")
    assert exc.value.error_type == "input"


def test_analyze_teardown_llm_error_propagates(mocked_teardown, monkeypatch) -> None:
    def boom(*, client, base_url, api_key, model, system_prompt, user_text, image_path, max_tokens, **kwargs):
        raise AnalysisError("LLM boom", error_type="llm_error")

    monkeypatch.setattr(_teardown_module, "_call_multimodal_llm", boom)
    with pytest.raises(AnalysisError) as exc:
        analyze_reference_teardown(mocked_teardown[2])
    assert exc.value.error_type == "llm_error"


def test_analyze_teardown_unparsable_synthesis(mocked_teardown, monkeypatch) -> None:
    def garbage(*, client, base_url, api_key, model, system_prompt, user_text, image_path, max_tokens, **kwargs):
        if image_path is not None:
            return _frame_analysis_json()
        return "not json at all"

    monkeypatch.setattr(_teardown_module, "_call_multimodal_llm", garbage)
    with pytest.raises(AnalysisError) as exc:
        analyze_reference_teardown(mocked_teardown[2])
    assert exc.value.error_type == "json_parse"


# ---------------------------------------------------------------------------
# 词级转录接线（transcript → 报告/综合 prompt/约束）
# ---------------------------------------------------------------------------


def test_transcript_unavailable_degrades_honestly(mocked_teardown) -> None:
    """默认配置（estimated）不跑转录：报告显式标注降级，约束告知用户。"""
    calls, _payload, video = mocked_teardown
    result = analyze_reference_teardown(video)
    assert result.report.transcript.source == "unavailable"
    assert result.report.transcript.reason == "engine_disabled"
    assert any("词级转录不可用" in c for c in result.report.constraints)


def test_transcript_whisperx_flows_into_synthesis_and_beats(
    mocked_teardown, monkeypatch
) -> None:
    """whisperX 词流进入综合 prompt；beats 带台词原文；来源标注 whisperx。"""
    import app.services.replica.transcribe as transcribe_module

    calls, synthesis_payload, video = mocked_teardown
    beats = synthesis_payload["json"].setdefault("beats", [])
    beats.append(
        {
            "role": "hook",
            "description": "错误示范",
            "line": "别再这样洗脸了",
            "start_seconds": 0.0,
            "end_seconds": 3.0,
        }
    )
    transcript = transcribe_module.TeardownTranscript(
        source=transcribe_module.TRANSCRIBE_SOURCE_WHISPERX,
        language="zh",
        lines=(
            transcribe_module.TranscriptLine(
                text="别再这样洗脸了", start_seconds=0.2, end_seconds=1.6
            ),
        ),
        words=(
            transcribe_module.TranscriptWord(text="别再", start_seconds=0.2, end_seconds=0.5),
            transcribe_module.TranscriptWord(text="洗脸", start_seconds=0.9, end_seconds=1.4),
        ),
    )
    monkeypatch.setattr(
        transcribe_module, "transcribe_reference_video", lambda path, settings=None, **kw: transcript
    )

    result = analyze_reference_teardown(video)
    assert result.report.transcript.source == "whisperx"
    assert result.report.transcript.lines[0]["text"] == "别再这样洗脸了"
    # 台词原文进入规范化 beats
    assert any(beat.line == "别再这样洗脸了" for beat in result.report.beats)
    # 综合拆解的 user prompt 带上了转录（时间脊柱）且约束不再报降级
    synthesis_call = next(c for c in calls if c["has_image"] is False)
    assert "别再这样洗脸了" in synthesis_call["user"]
    assert "[0.20-1.60s]" in synthesis_call["user"]
    assert not any("词级转录不可用" in c for c in result.report.constraints)


def test_normalize_beats_passes_line_through_clamped() -> None:
    data = {
        "beats": [
            {"role": "hook", "description": "d", "line": "x" * 3000,
             "start_seconds": 0.0, "end_seconds": 1.0},
        ]
    }
    beats = _teardown_module._normalize_beats(data, duration_seconds=5.0)
    assert len(beats[0]["line"]) == 2_048  # 钳制到 schema 上限


# ---------------------------------------------------------------------------
# HTTP endpoint（最小 app + 单 router，参考 scene_3d 测试模式）
# ---------------------------------------------------------------------------


def _mocked_result(user_description: str | None = None) -> TeardownResult:
    report = TeardownReport(
        whole_piece_reading="整片解读",
        format_name="talking-head",
        shots=[TeardownShot(index=1, start_seconds=0.0, end_seconds=2.1)],
        rhythm=TeardownRhythm(avg_shot_seconds=2.1, cut_points_seconds=[0.0]),
        systems=TeardownSystems(captions="底部"),
    )
    report.replica_storyboard_draft = build_replica_draft(report)
    report.constraints = ["test-constraint"]
    return TeardownResult(
        report=report,
        frame_analyses=[
            TeardownFrameAnalysis(
                frame_index=0,
                timestamp_seconds=0.0,
                scene_type="indoor",
                environment_description="studio",
                lighting="soft",
                camera_angle="eye-level",
                shot_size="closeup",
                camera_motion_hint="static",
                characters=[],
                props=[],
                on_screen_text="",
                notable_elements="",
            )
        ],
        video_metadata=_metadata(),
        num_frames_analyzed=1,
        user_description=user_description,
    )


@pytest.fixture
def replica_client(monkeypatch, tmp_path):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from app.api.v1.endpoints import replica as replica_endpoint

    monkeypatch.setattr(
        replica_endpoint,
        "analyze_reference_teardown",
        lambda **kwargs: _mocked_result(user_description=kwargs.get("user_description")),
    )

    stored = tmp_path / "reference.mp4"
    stored.write_bytes(b"fake")
    monkeypatch.setattr(replica_endpoint, "get_reference_video_path", lambda asset_id: stored)

    app = FastAPI()
    app.include_router(replica_endpoint.router)
    return TestClient(app)


def test_teardown_endpoint_by_asset_id(replica_client) -> None:
    response = replica_client.post("/replica/teardown", data={"asset_id": "abc123"})
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["success"] is True
    assert body["report"]["format_name"] == "talking-head"
    assert body["report"]["replica_storyboard_draft"]
    assert body["num_frames_analyzed"] == 1
    assert body["frame_analyses"][0]["shot_size"] == "closeup"
    assert body["video_metadata"]["duration_seconds"] == 12.0


def test_teardown_endpoint_multipart(replica_client) -> None:
    response = replica_client.post(
        "/replica/teardown",
        files={"file": ("ref.mp4", b"fake-bytes", "video/mp4")},
        data={"user_description": "换商品不换人", "num_frames": "8"},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["success"] is True
    assert body["user_description"] == "换商品不换人"


def test_teardown_endpoint_requires_source(replica_client) -> None:
    response = replica_client.post("/replica/teardown", data={"num_frames": "8"})
    assert response.status_code == 400


def test_teardown_endpoint_unknown_asset(replica_client, monkeypatch) -> None:
    from app.api.v1.endpoints import replica as replica_endpoint

    monkeypatch.setattr(replica_endpoint, "get_reference_video_path", lambda asset_id: None)
    response = replica_client.post("/replica/teardown", data={"asset_id": "missing"})
    assert response.status_code == 404


def test_teardown_endpoint_clamps_num_frames(replica_client, monkeypatch) -> None:
    from app.api.v1.endpoints import replica as replica_endpoint

    seen: dict = {}

    def spy(**kwargs):
        seen.update(kwargs)
        return _mocked_result()

    monkeypatch.setattr(replica_endpoint, "analyze_reference_teardown", spy)
    response = replica_client.post(
        "/replica/teardown", data={"asset_id": "abc123", "num_frames": "99"}
    )
    assert response.status_code == 200, response.text
    assert seen["num_frames"] == 16  # clamped to MAX_NUM_FRAMES


# ---------------------------------------------------------------------------
# Blueprint + instantiate endpoints（复刻半场）
# ---------------------------------------------------------------------------


def _blueprint_payload() -> dict:
    """A valid replica blueprint content payload (as stored on a replica node)."""
    from app.services.replica.blueprint import blueprint_from_teardown

    report = {
        "whole_piece_reading": "整片解读",
        "format_name": "product-comparison",
        "shots": [
            {"index": 1, "start_seconds": 0.0, "end_seconds": 2.1, "shot_size": "closeup",
             "camera_motion": "static", "subject_action": "口播", "on_screen_text": "标题",
             "transition_to_next": "cut", "note": "同机位换商品"},
        ],
        "beats": [
            {"role": "hook", "description": "钩子", "start_seconds": 0.0, "end_seconds": 3.0},
        ],
        "rhythm": {"avg_shot_seconds": 2.1, "cut_points_seconds": [0.0], "energy_curve": "平"},
        "systems": {"captions": "底部", "music": "电子", "graphics": [], "sfx": []},
        "constraints": ["推断值"],
    }
    blueprint = blueprint_from_teardown(report, source_asset_id="a1", duration_seconds=3.0)
    return blueprint.model_dump(mode="json")


def test_blueprint_endpoint_converts_report(replica_client) -> None:
    response = replica_client.post(
        "/replica/blueprint",
        json={
            "report": {
                "whole_piece_reading": "读片",
                "format_name": "talking-head",
                "shots": [],
                "beats": [],
                "rhythm": {},
                "systems": {},
            },
            "source_video_asset_id": "asset-x",
            "duration_seconds": 9.0,
            "replica_goal": "换商品",
        },
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["success"] is True
    assert body["blueprint"]["blueprint_version"] == "replica-blueprint-v1"
    assert body["blueprint"]["source_video_asset_id"] == "asset-x"
    # slots + script always derived
    assert len(body["blueprint"]["slots"]) == 5
    assert "# 复刻脚本" in body["replica_script"]


class _FakeNode:
    node_type = "replica"
    structured_content = _blueprint_payload()

    class position:
        x = 40.0
        y = 80.0


class _FakeWorkflow:
    revision = 7


class _FakeRepo:
    def __init__(self):
        self.bindings = []

    def get_workflow(self, workflow_id):
        return _FakeWorkflow()

    def add_binding(self, binding, *, expected_revision):
        self.bindings.append(binding)

    def get_node(self, workflow_id, node_id):
        if node_id != "node_replica":
            from app.persistence.errors import V2PersistenceError

            raise V2PersistenceError("canvas_node_not_found", "not found", stage="test")
        return _FakeNode()


class _FakeNodeService:
    def __init__(self):
        self.calls = []
        self.patches = []

    def create(self, workflow_id, request, *, expected_revision):
        self.calls.append((workflow_id, request, expected_revision))

        class _Created:
            node_id = "node_script_1"

        return _Created()

    def patch(self, workflow_id, node_id, request, *, expected_revision):
        self.patches.append((workflow_id, node_id, request.structured_content))
        return object()


@pytest.fixture
def instantiate_client(monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from app.api.v1.endpoints import replica as replica_endpoint

    service = _FakeNodeService()
    repo = _FakeRepo()
    monkeypatch.setattr(
        replica_endpoint, "_canvas_node_service", lambda: (service, repo)
    )
    app = FastAPI()
    app.include_router(replica_endpoint.router)
    return TestClient(app), service, repo


def test_instantiate_creates_script_node(instantiate_client) -> None:
    client, service, repo = instantiate_client
    response = client.post(
        "/replica/instantiate",
        json={"workflow_id": "wf-1", "replica_node_id": "node_replica"},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["success"] is True
    assert body["script_node_id"] == "node_script_1"
    assert body["workflow_revision"] == 8
    assert "# 复刻脚本" in body["script_text"]

    workflow_id, request, expected_revision = service.calls[0]
    assert workflow_id == "wf-1"
    assert request.node_type == "script"
    assert request.creative_role == "script"
    assert request.authoring_origin == "agent_guided"
    assert request.position.y == 340.0  # 80 (replica) + 260 offset
    assert expected_revision == 7
    assert request.structured_content["replica_source_node_id"] == "node_replica"
    # 绑定自动创建：replica → script（text_context）
    assert body["binding_id"].startswith("binding_")
    assert len(repo.bindings) == 1
    assert repo.bindings[0].source.source_node_id == "node_replica"
    assert repo.bindings[0].target_node_id == "node_script_1"
    # 实例化指针写回
    _, _, patched_content = service.patches[0]
    assert patched_content["instantiated_script_node_id"] == "node_script_1"


def test_instantiate_applies_slot_updates(instantiate_client) -> None:
    client, service, repo = instantiate_client
    response = client.post(
        "/replica/instantiate",
        json={
            "workflow_id": "wf-1",
            "replica_node_id": "node_replica",
            "slot_updates": {"product": "洗面奶A"},
        },
    )
    assert response.status_code == 200, response.text
    _, request, _ = service.calls[0]
    assert "替换为「洗面奶A」" in request.structured_content["content"]


def test_instantiate_rejects_non_replica_node(instantiate_client, monkeypatch) -> None:
    class _OtherNode(_FakeNode):
        node_type = "script"

    client, _, _ = instantiate_client
    monkeypatch.setattr(_FakeRepo, "get_node", lambda self, w, n: _OtherNode())
    response = client.post(
        "/replica/instantiate",
        json={"workflow_id": "wf-1", "replica_node_id": "node_replica"},
    )
    assert response.status_code == 400


def test_instantiate_unknown_node_is_404(instantiate_client) -> None:
    client, _, _ = instantiate_client
    response = client.post(
        "/replica/instantiate",
        json={"workflow_id": "wf-1", "replica_node_id": "node_missing"},
    )
    assert response.status_code == 404
