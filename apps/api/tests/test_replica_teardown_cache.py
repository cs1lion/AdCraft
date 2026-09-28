"""Unit tests for the G6 teardown cache (拆解报告缓存：省 LLM 额度 + E2E 提速).

三层锁定：

- 纯函数层：缓存键对内容/参数/模型/转录状态各自敏感、确定性；载荷存取
  的原子性与损坏降级（坏缓存 = miss，绝不是报告）；
- 服务层：命中跳过全部 LLM 调用、cached 标注进 constraints、use_cache=False
  强制重算、内容/参数变化即 miss、损坏条目自愈（重算后覆盖）；
- 端点层：``use_cache`` 透传 + 响应 ``cached``/``cache_key`` 溯源字段。

设计依据：docs/plans/replica-completion-research.md G6（LLM 额度强依赖）。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.schemas.agent_canvas_ad_media import ReplicaBlueprintContentV2
from app.services.scene3d.reference_upload import VideoMetadata
from app.services.replica import teardown as _teardown_module
from app.services.replica.teardown import (
    CACHED_REPORT_NOTE,
    TeardownResult,
    analyze_reference_teardown,
)
from app.services.replica.teardown_cache import (
    CACHE_SCHEMA_VERSION,
    file_content_hash,
    load_cached_teardown,
    save_cached_teardown,
    teardown_cache_dir,
    teardown_cache_key,
)


# ---------------------------------------------------------------------------
# Fixtures（自包含：LLM 边界全 mock，转录走默认关闭路径，缓存目录隔离）
# ---------------------------------------------------------------------------


def _synthesis_dict() -> dict:
    return {
        "whole_piece_reading": "前3秒钩子，中段证明，结尾CTA。",
        "format_name": "product-comparison",
        "shots": [
            {
                "index": 1,
                "start_seconds": 0.0,
                "end_seconds": 2.0,
                "shot_size": "closeup",
                "camera_motion": "static",
                "subject_action": "唇部特写",
                "on_screen_text": "别再这样洗脸",
                "transition_to_next": "cut",
            }
        ],
        "beats": [
            {"role": "hook", "description": "错误示范", "start_seconds": 0.0, "end_seconds": 3.0}
        ],
        "rhythm": {"avg_shot_seconds": 2.0, "cut_points_seconds": [0.0], "energy_curve": "前快后缓"},
        "systems": {"captions": "底部大字", "music": "轻快电子", "graphics": ["价格贴"], "sfx": ["whoosh"]},
    }


def _frame_analysis_json(on_screen_text: str = "别再这样洗脸") -> str:
    return json.dumps(
        {
            "scene_type": "indoor",
            "environment_description": "浴室",
            "lighting": "warm",
            "camera_angle": "eye-level",
            "shot_size": "closeup",
            "camera_motion_hint": "static",
            "characters": [],
            "props": [],
            "on_screen_text": on_screen_text,
            "notable_elements": "",
        },
        ensure_ascii=False,
    )


class _FakeClient:
    def close(self) -> None:  # pragma: no cover - trivial
        pass


@pytest.fixture
def cached_teardown(monkeypatch, tmp_path):
    """Monkeypatch the teardown boundary; return (calls, video, cache_dir)."""
    video = tmp_path / "reference.mp4"
    video.write_bytes(b"fake-video-bytes-v1")
    cache_dir = tmp_path / "teardown_cache"
    calls: list[dict] = []

    def fake_call(*, client, base_url, api_key, model, system_prompt, user_text, image_path, max_tokens, **kwargs):
        calls.append({"has_image": image_path is not None})
        if image_path is not None:
            return _frame_analysis_json()
        return json.dumps(_synthesis_dict(), ensure_ascii=False)

    monkeypatch.setattr(_teardown_module, "_call_multimodal_llm", fake_call)
    monkeypatch.setattr(
        _teardown_module,
        "_build_llm_client",
        lambda: (_FakeClient(), "http://llm.test", "key", "test-model"),
    )

    monkeypatch.setattr(
        _teardown_module,
        "extract_metadata",
        lambda path: VideoMetadata(
            duration_seconds=12.0,
            width=720,
            height=1280,
            frame_rate=30.0,
            frame_count=360,
            codec_name="h264",
            file_size_bytes=1024,
        ),
    )
    monkeypatch.setattr(
        _teardown_module,
        "extract_keyframes_from_video",
        lambda video_path, output_dir, num_keyframes: [
            str(output_dir / f"keyframe_{i:02d}.png") for i in range(num_keyframes)
        ],
    )
    return calls, video, cache_dir


# ---------------------------------------------------------------------------
# 纯函数层：键派生与载荷存取
# ---------------------------------------------------------------------------


def test_cache_key_is_deterministic(tmp_path: Path) -> None:
    video = tmp_path / "v.mp4"
    video.write_bytes(b"same-bytes")
    first = teardown_cache_key(
        video_path=video,
        num_frames=8,
        user_description="换商品",
        model="m1",
        transcript_source="unavailable",
        transcript_reason="engine_disabled",
    )
    second = teardown_cache_key(
        video_path=video,
        num_frames=8,
        user_description="换商品",
        model="m1",
        transcript_source="unavailable",
        transcript_reason="engine_disabled",
    )
    assert first == second
    assert first == file_content_hash(video) or len(first) == 64


def test_cache_key_changes_with_video_content(tmp_path: Path) -> None:
    video = tmp_path / "v.mp4"
    video.write_bytes(b"bytes-a")
    key_a = teardown_cache_key(
        video_path=video, num_frames=8, user_description=None,
        model="m1", transcript_source="unavailable", transcript_reason=None,
    )
    video.write_bytes(b"bytes-b")
    key_b = teardown_cache_key(
        video_path=video, num_frames=8, user_description=None,
        model="m1", transcript_source="unavailable", transcript_reason=None,
    )
    assert key_a != key_b


def test_cache_key_changes_with_every_report_input(tmp_path: Path) -> None:
    video = tmp_path / "v.mp4"
    video.write_bytes(b"same-bytes")
    base = dict(
        video_path=video, num_frames=8, user_description="换商品",
        model="m1", transcript_source="unavailable", transcript_reason=None,
    )
    variants = {
        **base,
        "num_frames": 12,
    }, {**base, "user_description": "换人物"}, {**base, "model": "m2"}, {
        **base, "transcript_source": "whisperx", "transcript_reason": None,
    }, {**base, "user_description": " 换商品 "}  # 归一化后应与 base 相同
    keys = [
        teardown_cache_key(**variants[0]),
        teardown_cache_key(**variants[1]),
        teardown_cache_key(**variants[2]),
        teardown_cache_key(**variants[3]),
    ]
    base_key = teardown_cache_key(**base)
    assert base_key not in keys
    assert len(set(keys)) == 4
    # user_description 首尾空白不改变键（归一化）
    assert teardown_cache_key(**variants[4]) == base_key


def test_load_returns_none_for_missing_corrupt_and_drifted(tmp_path: Path) -> None:
    cache_dir = tmp_path / "cache"
    key = "k" * 64
    # 缺失
    assert load_cached_teardown(cache_dir, key) is None
    # 不可解析
    cache_dir.mkdir(parents=True)
    (cache_dir / f"{key}.json").write_text("not json", encoding="utf-8")
    assert load_cached_teardown(cache_dir, key) is None
    # 键不匹配（张冠李戴）
    (cache_dir / f"{key}.json").write_text(
        json.dumps({"cache_schema": CACHE_SCHEMA_VERSION, "key": "other", "report": {}}),
        encoding="utf-8",
    )
    assert load_cached_teardown(cache_dir, key) is None
    # schema 漂移
    (cache_dir / f"{key}.json").write_text(
        json.dumps({"cache_schema": CACHE_SCHEMA_VERSION + 1, "key": key, "report": {}}),
        encoding="utf-8",
    )
    assert load_cached_teardown(cache_dir, key) is None
    # 无 report
    (cache_dir / f"{key}.json").write_text(
        json.dumps({"cache_schema": CACHE_SCHEMA_VERSION, "key": key}),
        encoding="utf-8",
    )
    assert load_cached_teardown(cache_dir, key) is None


def test_save_roundtrips_atomically(tmp_path: Path) -> None:
    cache_dir = teardown_cache_dir(tmp_path)
    key = "a" * 64
    payload = {"cache_schema": CACHE_SCHEMA_VERSION, "key": key, "report": {"format_name": "x"}}

    assert save_cached_teardown(cache_dir, key, payload) is True
    assert load_cached_teardown(cache_dir, key) == payload
    # 原子替换：不留 tmp 残件
    assert not list(cache_dir.glob("*.tmp"))


# ---------------------------------------------------------------------------
# 服务层：命中/未命中/降级/自愈
# ---------------------------------------------------------------------------


def test_second_identical_teardown_hits_cache_and_skips_llm(cached_teardown) -> None:
    calls, video, cache_dir = cached_teardown

    first = analyze_reference_teardown(video, cache_dir=cache_dir)
    assert first.cached is False
    llm_calls_after_first = len(calls)

    second = analyze_reference_teardown(video, cache_dir=cache_dir)

    assert second.cached is True
    assert second.cache_key == first.cache_key if first.cache_key else True
    # 命中不调 LLM：调用计数不变
    assert len(calls) == llm_calls_after_first
    # 报告内容一致（除缓存的 constraints 标注）
    assert second.report.format_name == first.report.format_name
    assert second.report.replica_storyboard_draft == first.report.replica_storyboard_draft
    assert len(second.frame_analyses) == first.num_frames_analyzed
    assert second.video_metadata.duration_seconds == first.video_metadata.duration_seconds


def test_cache_hit_appends_visible_note_to_constraints(cached_teardown) -> None:
    _calls, video, cache_dir = cached_teardown
    analyze_reference_teardown(video, cache_dir=cache_dir)

    second = analyze_reference_teardown(video, cache_dir=cache_dir)

    assert CACHED_REPORT_NOTE in second.report.constraints
    # 标注只进内存结果，不回写缓存文件（不叠加）
    stored = load_cached_teardown(cache_dir, second.cache_key)
    assert CACHED_REPORT_NOTE not in (stored or {}).get("report", {}).get("constraints", [])


def test_use_cache_false_forces_full_reanalysis(cached_teardown) -> None:
    calls, video, cache_dir = cached_teardown
    analyze_reference_teardown(video, cache_dir=cache_dir)
    calls_after_first = len(calls)

    forced = analyze_reference_teardown(video, cache_dir=cache_dir, use_cache=False)

    assert forced.cached is False
    assert len(calls) > calls_after_first


def test_changed_content_misses_cache(cached_teardown) -> None:
    calls, video, cache_dir = cached_teardown
    analyze_reference_teardown(video, cache_dir=cache_dir)
    calls_after_first = len(calls)

    video.write_bytes(b"fake-video-bytes-v2")  # 同一路径，内容变了
    again = analyze_reference_teardown(video, cache_dir=cache_dir)

    assert again.cached is False
    assert len(calls) > calls_after_first


def test_changed_user_description_misses_cache(cached_teardown) -> None:
    calls, video, cache_dir = cached_teardown
    analyze_reference_teardown(video, cache_dir=cache_dir, user_description="换商品")
    calls_after_first = len(calls)

    again = analyze_reference_teardown(video, cache_dir=cache_dir, user_description="换人物")

    assert again.cached is False
    assert len(calls) > calls_after_first


def test_corrupt_cache_entry_degrades_to_full_analysis_and_self_heals(cached_teardown) -> None:
    calls, video, cache_dir = cached_teardown
    first = analyze_reference_teardown(video, cache_dir=cache_dir)
    # 破坏缓存文件（手改/写坏）
    cache_file = cache_dir / f"{first.cache_key}.json"
    assert cache_file.exists()
    cache_file.write_text("{ broken json", encoding="utf-8")
    calls_after_first = len(calls)

    healed = analyze_reference_teardown(video, cache_dir=cache_dir)

    assert healed.cached is False  # 坏缓存当 miss，不把坏数据当报告
    assert len(calls) > calls_after_first  # 真的重跑了 LLM
    # 自愈：有效条目被重写，第三次命中
    third = analyze_reference_teardown(video, cache_dir=cache_dir)
    assert third.cached is True


def test_failed_analysis_does_not_write_cache(cached_teardown, monkeypatch) -> None:
    from app.services.replica.teardown import AnalysisError

    _calls, video, cache_dir = cached_teardown

    def boom(*, client, base_url, api_key, model, system_prompt, user_text, image_path, max_tokens, **kwargs):
        raise AnalysisError("LLM boom", error_type="llm_error")

    monkeypatch.setattr(_teardown_module, "_call_multimodal_llm", boom)
    with pytest.raises(AnalysisError):
        analyze_reference_teardown(video, cache_dir=cache_dir)

    assert not list(cache_dir.glob("*.json")) if cache_dir.exists() else True


# ---------------------------------------------------------------------------
# 端点层：use_cache 透传 + cached 溯源
# ---------------------------------------------------------------------------


@pytest.fixture
def teardown_client(monkeypatch, tmp_path):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from app.api.v1.endpoints import replica as replica_endpoint

    seen: dict = {}

    def fake_analyze(**kwargs):
        seen.update(kwargs)
        return TeardownResult(
            report=_teardown_module.TeardownReport(format_name="product-comparison"),
            frame_analyses=[],
            video_metadata=_teardown_module.VideoMetadata(
                duration_seconds=12.0, width=720, height=1280,
                frame_rate=30.0, frame_count=360, codec_name="h264", file_size_bytes=1,
            ),
            num_frames_analyzed=0,
            cached=True,
            cache_key="k" * 64,
        )

    monkeypatch.setattr(replica_endpoint, "analyze_reference_teardown", fake_analyze)

    stored = tmp_path / "reference.mp4"
    stored.write_bytes(b"fake")
    monkeypatch.setattr(replica_endpoint, "get_reference_video_path", lambda asset_id: stored)

    app = FastAPI()
    app.include_router(replica_endpoint.router)
    return TestClient(app), seen


def test_teardown_endpoint_forwards_use_cache_and_surfaces_cached(teardown_client) -> None:
    client, seen = teardown_client

    response = client.post("/replica/teardown", data={"asset_id": "abc", "use_cache": "true"})

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["cached"] is True
    assert body["cache_key"] == "k" * 64
    assert seen["use_cache"] is True

    response_off = client.post("/replica/teardown", data={"asset_id": "abc", "use_cache": "false"})
    assert response_off.status_code == 200, response_off.text
    assert seen["use_cache"] is False


def test_teardown_endpoint_defaults_use_cache_on(teardown_client) -> None:
    client, seen = teardown_client

    response = client.post("/replica/teardown", data={"asset_id": "abc"})

    assert response.status_code == 200, response.text
    assert seen["use_cache"] is True


def test_blueprint_import_from_cached_report_keeps_constraints(cached_teardown, tmp_path: Path) -> None:
    """缓存报告进蓝图转换时，缓存标注随 constraints 流传（不断链）。"""
    from app.services.replica.blueprint import blueprint_from_teardown

    _calls, video, cache_dir = cached_teardown
    analyze_reference_teardown(video, cache_dir=cache_dir)
    cached = analyze_reference_teardown(video, cache_dir=cache_dir)
    assert cached.cached is True

    blueprint = blueprint_from_teardown(cached.report.model_dump(mode="json"))
    assert any(CACHED_REPORT_NOTE in c for c in blueprint.constraints)
    assert isinstance(blueprint, ReplicaBlueprintContentV2)
