"""Media tests for the direct-execute placeholder-video fallback (ADR 0010 R1).

Locks the A's acceptance: a feasible pure-caption blueprint (no video source
at all) renders end-to-end at zero model cost — the renderer generates a
solid-color placeholder video clip, the composition completes, and the
output probes as a real playable file. Requires ffmpeg/ffprobe + a readable
subtitle font (skipped otherwise).

Blueprint source: docs/plans/replica-teardown.md §10; ADR 0010 R1 验收.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from app.schemas.agent_canvas_ad_media import (
    ReplicaBeatV2,
    ReplicaBlueprintContentV2,
    ReplicaShotV2,
)
from app.schemas.workflow_v2 import (
    WorkflowItemV2,
    WorkflowSlotV2,
    WorkflowV2,
)
from app.services.replica.direct_execute import plan_direct_execute
from app.services.replica.direct_execute_render import (
    plan_direct_execute_render,
    resolve_library_clip,
)
from app.services.v2_final_composition_renderer import V2FinalCompositionRenderer

_FONT_CANDIDATES = [
    Path(r"C:\Windows\Fonts\arial.ttf"),
    Path(r"C:\Windows\Fonts\msyh.ttc"),
    Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
]


def _settings(tmp_path: Path):
    import dataclasses

    from app.core.config import get_settings

    font = next((p for p in _FONT_CANDIDATES if p.exists()), None)
    if font is None:
        pytest.skip("No readable subtitle font on this machine")
    return dataclasses.replace(
        get_settings(),
        media_data_dir=tmp_path,
        final_composition_subtitle_font_path=str(font),
        final_composition_render_mode="timeline_editor",
    )


def _pure_caption_blueprint() -> ReplicaBlueprintContentV2:
    """全部镜头只有屏上文字（direct-execute 可行），带台词/字幕/音效/BGM 意图。"""
    return ReplicaBlueprintContentV2(
        replica_goal="纯字幕促销片直出验收",
        aspect="9:16",
        duration_seconds=6.0,
        whole_piece_reading="四段式纯字幕促销结构。",
        format_name="caption-promo",
        # 纯字幕片：台词即屏上文字，无口播（有 line 会触发 TTS 生成步骤）
        beats=[
            ReplicaBeatV2(beat_id="b1", role="hook", start_seconds=0.0, end_seconds=1.5),
            ReplicaBeatV2(beat_id="b2", role="proof", start_seconds=1.5, end_seconds=3.0),
            ReplicaBeatV2(beat_id="b3", role="cta", start_seconds=3.0, end_seconds=6.0),
        ],
        shots=[
            ReplicaShotV2(
                index=i,
                start_seconds=start,
                end_seconds=end,
                on_screen_text=text,
                subject_action="",
            )
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
        systems_captions="底部大字",
        systems_music="促销电子",
        systems_sfx=["whoosh"],
    )


@pytest.fixture
def render_env(tmp_path: Path):
    if shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None:
        pytest.skip("ffmpeg/ffprobe not on PATH")
    settings = _settings(tmp_path)
    renderer = V2FinalCompositionRenderer(data_dir=tmp_path, settings=settings)
    now = "2026-09-27T00:00:00+00:00"
    workflow = WorkflowV2(
        workflow_id="wf_replica_media",
        name="replica media test",
        prompt="direct-execute render test",
        audio_mode="bgm_only",
        created_at=now,
        updated_at=now,
    )
    item = WorkflowItemV2(
        item_id="item_fc",
        node_id="node_fc",
        item_type="final_composition",
        display_name="Final Composition",
    )
    slot = WorkflowSlotV2(
        slot_id="slot_fc",
        node_id="node_fc",
        item_id="item_fc",
        slot_type="final_video",
        media_type="video",
    )
    return renderer, workflow, item, slot, settings


@pytest.fixture
def payload():
    blueprint = _pure_caption_blueprint()
    plan = plan_direct_execute_render(
        blueprint, plan_direct_execute(blueprint)
    )
    assert plan.feasible is True
    assert plan.needs_placeholder_video is True
    return {
        "canonical_timeline": plan.timeline.model_dump(mode="json"),
        "render_id": "render_media_test01",
    }, plan


def test_pure_caption_piece_renders_with_placeholder_video(
    render_env, payload, tmp_path: Path
) -> None:
    """验收：零模型费纯字幕片端到端出片（占位画面自动补齐）。"""
    renderer, workflow, item, slot, settings = render_env
    payload_dict, plan = payload

    result = renderer.render(workflow, item, slot, payload_dict)

    assert result.status == "completed", getattr(result, "metadata", {})
    output_path = tmp_path / result.local_file_path
    assert output_path.exists()
    assert output_path.stat().st_size > 10_000
    # 占位片源与最终产物都在渲染目录里
    placeholder = output_path.parent / "placeholder-video.mp4"
    assert placeholder.exists()
    # 元数据锁定占位来源（诚实标注，不伪造素材）
    assert "__placeholder_video__" in result.reference_asset_ids
    assert result.metadata["timeline_duration_seconds"] == plan.timeline.duration_seconds

    from app.services.v2_final_composition_renderer import V2MediaProbe

    probe = V2MediaProbe(ffprobe_path=settings.ffprobe_path)(output_path, 'video')
    assert probe.error is None
    assert abs(probe.duration_seconds - plan.timeline.duration_seconds) < 0.5
    assert probe.width == 720 and probe.height == 1280


def test_no_video_and_no_placeholder_flag_still_rejected(render_env, tmp_path: Path) -> None:
    """无 video clip 且无 needs_placeholder_video 标记 → 维持原硬约束拒绝。"""
    renderer, workflow, item, slot, _settings = render_env
    blueprint = _pure_caption_blueprint()
    plan = plan_direct_execute_render(blueprint, plan_direct_execute(blueprint))
    timeline_dict = plan.timeline.model_dump(mode="json")
    timeline_dict["metadata"].pop("needs_placeholder_video")

    result = renderer.render(
        workflow,
        item,
        slot,
        {"canonical_timeline": timeline_dict, "render_id": "render_media_test02"},
    )
    assert result.status == "failed"
    assert result.provider_payload_snapshot is not None


def test_resolved_bgm_renders_real_audio_into_final_video(
    render_env, tmp_path: Path
) -> None:
    """G7 验收：resolve-library 启用 BGM 后，成片带真实音轨。

    锁 resolve → 渲染音频路径：编译层产的 BGM clip 是"库素材意图"（哨兵、
    enabled=False）；经 ``resolve_library_clip`` 绑到真实音频资产并启用后，
    渲染器必须把音轨混进成片——否则"启用 BGM"只是文本上的谎言。
    """
    import subprocess

    renderer, workflow, item, slot, settings = render_env

    # 1) 合成一条真实音频资产（6s 正弦波，aac/mp4——与合成链容器一致）
    bgm_rel = "library/bgm_e2e.mp4"
    bgm_path = tmp_path / bgm_rel
    bgm_path.parent.mkdir(parents=True, exist_ok=True)
    synth = subprocess.run(
        [
            "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
            "-f", "lavfi", "-i", "sine=frequency=440:duration=6",
            "-c:a", "aac", "-b:a", "128k",
            str(bgm_path),
        ],
        capture_output=True,
        text=True,
    )
    assert synth.returncode == 0, synth.stderr[-500:]

    # 2) 注册进 v2 资产库（渲染器按 asset/version 解析真实文件）
    from app.schemas.workflow_v2 import WorkflowAssetVersionV2
    from app.services.v2_asset_store import V2AssetStoreService

    asset_id, version_id = "asset_bgm_e2e", "ver_bgm_e2e"
    V2AssetStoreService(tmp_path).save_asset_version(
        WorkflowAssetVersionV2(
            asset_id=asset_id,
            version_id=version_id,
            media_type="audio",
            source_type="generated",
            file_path=bgm_rel,
            workflow_id="wf_replica_media",
            created_by="replica-media-test",
        )
    )

    # 3) 编译 → 人工解析 BGM（SFX 保持未解析：哨兵 clip 渲染器本就跳过）
    blueprint = _pure_caption_blueprint()
    plan = plan_direct_execute_render(blueprint, plan_direct_execute(blueprint))
    timeline = resolve_library_clip(
        plan.timeline,
        clip_id="bgm_system",
        asset_id=asset_id,
        version_id=version_id,
    )
    bgm = next(c for c in timeline.clips if c.clip_id == "bgm_system")
    assert bgm.enabled is True
    assert bgm.source_asset_id == asset_id

    # 4) 渲染：占位画面 + 字幕 + 真实 BGM 音轨
    result = renderer.render(
        workflow,
        item,
        slot,
        {
            "canonical_timeline": timeline.model_dump(mode="json"),
            "render_id": "render_media_bgm",
        },
    )
    assert result.status == "completed", getattr(result, "metadata", {})

    # 5) 成片确实有音轨，且 BGM 资产在溯源里
    output_path = tmp_path / result.local_file_path
    assert output_path.exists()
    assert asset_id in result.reference_asset_ids

    from app.services.v2_final_composition_renderer import V2MediaProbe

    probe = V2MediaProbe(ffprobe_path=settings.ffprobe_path)(output_path, "video")
    assert probe.error is None
    assert probe.has_audio is True, "resolve-library 启用的 BGM 没有混进成片"
    assert abs(probe.duration_seconds - plan.timeline.duration_seconds) < 0.5
