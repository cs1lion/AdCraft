"""拉片复刻 · 参考片拆解器（reference teardown）。

输入一条参考视频，输出结构化拆解报告 + 复刻分镜草稿：

    参考视频 → ffprobe 元数据 → 均匀抽帧 → 多模态 LLM 逐帧分析
             → LLM 综合拆解（整片解读/Beats/镜头表/节奏/系统）
             → pydantic 校验 + normalize 兜底 → 复刻分镜草稿（确定性生成）

与 scene3d 的 reference_video_analyzer 共享同一 LLM 边界（OpenAI 兼容
chat/completions + image_url），在测试中整体 monkeypatch，无网络依赖。

两条刻意的产品边界（写进报告的 constraints，面向用户保持诚实）：
1. 镜头边界与运动轨迹是 LLM 基于稀疏抽帧的**推断值**，不是帧级测量；
2. 复刻目标是**结构与关系**（镜头顺序/节奏/锚点/系统），不是像素还原。
"""

from __future__ import annotations

import dataclasses
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from app.core.config import get_settings
from app.services.replica.teardown_cache import (
    CACHE_SCHEMA_VERSION,
    load_cached_teardown,
    save_cached_teardown,
    teardown_cache_dir,
    teardown_cache_key,
)
from app.services.scene3d.reference_upload import (
    VideoMetadata,
    extract_keyframes_from_video,
    extract_metadata,
)
from app.services.scene3d.reference_video_analyzer import (
    AnalysisError,
    _call_multimodal_llm,
    _extract_json_from_response,
)


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

DEFAULT_NUM_FRAMES = 8
"""拉片默认抽帧数：比 SceneScript 的 6 帧更密，短广告 8-12 帧可分辨多数切点。"""

MIN_NUM_FRAMES = 4
MAX_NUM_FRAMES = 16

MAX_TEARDOWN_DURATION_SECONDS = 60.0
"""拉片面向短广告/短视频；超过 60s 的素材建议先裁剪。"""

DEFAULT_LLM_TIMEOUT_SECONDS = 120
DEFAULT_MAX_TOKENS_FRAME_ANALYSIS = 3000
DEFAULT_MAX_TOKENS_SYNTHESIS = 16000


# ---------------------------------------------------------------------------
# Report schema（pydantic 校验 + normalize 兜底，沿用 SceneScript 的教训）
# ---------------------------------------------------------------------------


class TeardownShot(BaseModel):
    """一个镜头的拆解条目。"""

    index: int = 1
    start_seconds: float = 0.0
    end_seconds: float = 0.0
    shot_size: str = "medium"
    camera_motion: str = "static"
    subject_action: str = ""
    on_screen_text: str = Field(
        default="",
        description="屏上文字（字幕/价格贴/贴纸），抄 hypit 对 Caption/MG 系统的关注",
    )
    transition_to_next: str = "cut"
    note: str = ""


class StructureBeat(BaseModel):
    """结构段落（hook/problem/proof/cta/transition/body）。

    ``line`` 是该段落的台词原文（词级转录可用时来自转录）——词级锚定的
    文本载体；无转录时为空。
    """

    role: str = "body"
    description: str = ""
    line: str = ""
    start_seconds: float = 0.0
    end_seconds: float = 0.0


class TeardownRhythm(BaseModel):
    """节奏：平均镜长、切点、能量曲线描述。"""

    avg_shot_seconds: float = 0.0
    cut_points_seconds: list[float] = Field(default_factory=list)
    energy_curve: str = ""


class TeardownSystems(BaseModel):
    """跨镜头存活的视觉/听觉系统（hypit：系统比单镜头更长寿）。"""

    captions: str = ""
    music: str = ""
    graphics: list[str] = Field(default_factory=list)
    sfx: list[str] = Field(default_factory=list)


class TeardownTranscriptInfo(BaseModel):
    """词级转录的紧凑信息块（详见 services/replica/transcribe.py）。

    ``source="unavailable"`` 时 ``reason`` 说明降级原因；words 供蓝图把
    锚点事件解析到具体词上。
    """

    source: str = "unavailable"
    language: str = ""
    reason: str = ""
    lines: list[dict[str, Any]] = Field(default_factory=list)
    words: list[dict[str, Any]] = Field(default_factory=list)


class TeardownReport(BaseModel):
    """完整拉片拆解报告。replica_storyboard_draft 由确定性代码生成。"""

    whole_piece_reading: str = ""
    format_name: str = "short-video"
    shots: list[TeardownShot] = Field(default_factory=list)
    beats: list[StructureBeat] = Field(default_factory=list)
    rhythm: TeardownRhythm = Field(default_factory=TeardownRhythm)
    systems: TeardownSystems = Field(default_factory=TeardownSystems)
    transcript: TeardownTranscriptInfo = Field(default_factory=TeardownTranscriptInfo)
    replica_storyboard_draft: str = ""
    constraints: list[str] = Field(default_factory=list)


@dataclass(frozen=True)
class TeardownFrameAnalysis:
    """单帧拉片分析（参考 FrameAnalysis，增加屏上文字维度）。"""

    frame_index: int
    timestamp_seconds: float
    scene_type: str
    environment_description: str
    lighting: str
    camera_angle: str
    shot_size: str
    camera_motion_hint: str
    characters: list[dict[str, Any]]
    props: list[str]
    on_screen_text: str
    notable_elements: str


@dataclass(frozen=True)
class TeardownResult:
    """analyze_reference_teardown 的完整结果。"""

    report: TeardownReport
    frame_analyses: list[TeardownFrameAnalysis]
    video_metadata: VideoMetadata
    num_frames_analyzed: int
    user_description: str | None = None
    # G6 缓存溯源：True = 本报告来自缓存（未调用 LLM）。缓存是优化不是
    # 真相源，"这份报告没花新额度"必须说得出口。
    cached: bool = False
    cache_key: str = ""


#: 缓存命中时追加进 report.constraints 的用户可见标注（与 fixture 降级标注
#: 同一区块：报告里"这份东西怎么来的"永远可见）。
CACHED_REPORT_NOTE = "本报告来自拆解缓存（相同视频内容与参数），未重新调用 LLM"


# ---------------------------------------------------------------------------
# LLM boundary（与 reference_video_analyzer 同一套 OpenAI 兼容调用）
# ---------------------------------------------------------------------------


def _build_llm_client() -> tuple[Any, str, str, str]:
    """构建 httpx client，返回 (client, base_url, api_key, model)。"""
    import httpx

    from app.core.config import get_settings

    settings = get_settings()
    if not settings.llm_api_key or not settings.llm_base_url:
        raise AnalysisError(
            "LLM not configured: set LLM_API_KEY and LLM_BASE_URL",
            error_type="configuration",
        )
    model = settings.llm_scene_model or settings.llm_front_desk_model
    client = httpx.Client(timeout=DEFAULT_LLM_TIMEOUT_SECONDS)
    return client, settings.llm_base_url, settings.llm_api_key, model


# ---------------------------------------------------------------------------
# 逐帧分析
# ---------------------------------------------------------------------------

_TEARDOWN_FRAME_SYSTEM_PROMPT = """You are a professional film editor performing a 拉片 \
(shot-by-shot teardown) of a short reference video. Analyze a single frame and describe \
what you actually see in structured JSON. Be precise and objective.

Also note: this may be a 3D low-fidelity previs video where characters are colored \
geometric shapes (a box body with a sphere head). If you see such shapes, identify them \
as characters and describe their color, position and apparent action.

Output ONLY a JSON object with these fields:
{
  "scene_type": "indoor|outdoor|mixed",
  "environment_description": "brief description of the space and key elements",
  "lighting": "warm|cool|neutral|dramatic|soft|hard",
  "camera_angle": "high-angle|eye-level|low-angle",
  "shot_size": "extreme_closeup|closeup|medium|wide|over_shoulder|pov",
  "camera_motion_hint": "static|pushing_in|pulling_out|pan_left|pan_right|tracking|handheld|orbiting|crane",
  "characters": [
    {"description": "what the person looks like / is wearing", "position_hint": "left foreground|center|right background|etc", "action": "walking|sitting|standing|gesturing|talking|running|entering|exiting", "facing": "toward camera|away|left|right"}
  ],
  "props": ["notable objects"],
  "on_screen_text": "transcribe any visible captions / subtitles / price tags / stickers briefly; empty string if none",
  "notable_elements": "anything else important: door opening, dramatic lighting, spatial depth, etc"
}

If there are no characters, return an empty array. - Be concise: whole_piece_reading is 2-3 short sentences; beat/shot descriptions stay under 30 characters. JSON must be small enough to parse.
Do not include any text outside the JSON object."""


def _analyze_teardown_frame(
    client: Any,
    base_url: str,
    api_key: str,
    model: str,
    image_path: Path,
    frame_index: int,
    timestamp_seconds: float,
    total_frames: int,
) -> TeardownFrameAnalysis:
    """Analyze a single frame for the teardown (adds on-screen text)."""
    user_text = (
        f"This is frame {frame_index + 1} of {total_frames} "
        f"(timestamp {timestamp_seconds:.2f}s) from a reference video being torn down. "
        f"Analyze this frame and output the structured JSON."
    )
    raw = _call_multimodal_llm(
        client=client,
        base_url=base_url,
        api_key=api_key,
        model=model,
        system_prompt=_TEARDOWN_FRAME_SYSTEM_PROMPT,
        user_text=user_text,
        image_path=image_path,
        max_tokens=DEFAULT_MAX_TOKENS_FRAME_ANALYSIS,
        extra_payload={"reasoning_effort": "low"},
    )
    data = _extract_json_from_response(raw)

    return TeardownFrameAnalysis(
        frame_index=frame_index,
        timestamp_seconds=timestamp_seconds,
        scene_type=data.get("scene_type", "indoor"),
        environment_description=data.get("environment_description", ""),
        lighting=data.get("lighting", "neutral"),
        camera_angle=data.get("camera_angle", "eye-level"),
        shot_size=data.get("shot_size", "medium"),
        camera_motion_hint=data.get("camera_motion_hint", "static"),
        characters=list(data.get("characters", [])),
        props=list(data.get("props", [])),
        on_screen_text=str(data.get("on_screen_text", "") or ""),
        notable_elements=data.get("notable_elements", ""),
    )


def _serialize_frame_analyses(frames: list[TeardownFrameAnalysis]) -> str:
    """Compact JSON dump of frame analyses for the synthesis prompt."""
    return json.dumps(
        [
            {
                "timestamp_seconds": fa.timestamp_seconds,
                "shot_size": fa.shot_size,
                "camera_motion_hint": fa.camera_motion_hint,
                "camera_angle": fa.camera_angle,
                "characters": fa.characters,
                "on_screen_text": fa.on_screen_text,
                "notable_elements": fa.notable_elements,
            }
            for fa in frames
        ],
        ensure_ascii=False,
    )


# ---------------------------------------------------------------------------
# 综合拆解（LLM）
# ---------------------------------------------------------------------------

_TEARDOWN_SYNTHESIS_SYSTEM_PROMPT = """You are a senior creative director performing a \
拉片复刻 (reference teardown) of a short reference video. Given per-frame analyses \
(with timestamps) of the video, synthesize a structured teardown as JSON.

Output ONLY a JSON object:
{
  "whole_piece_reading": "why this piece works: hook → argument → payoff, 2-4 sentences",
  "format_name": "short format label, e.g. product-comparison / unboxing / talking-head / vlog / tutorial",
  "beats": [
    {"role": "hook|problem|proof|cta|transition|body", "description": "what this section does for the viewer", "line": "the spoken line(s) in this section, verbatim from the transcript", "start_seconds": 0.0, "end_seconds": 3.0}
  ],
  "shots": [
    {"index": 1, "start_seconds": 0.0, "end_seconds": 2.1, "shot_size": "closeup", "camera_motion": "static", "subject_action": "what the subject does", "on_screen_text": "", "transition_to_next": "cut"}
  ],
  "rhythm": {"avg_shot_seconds": 2.4, "cut_points_seconds": [0.0, 2.1, 4.8], "energy_curve": "one sentence on pacing"},
  "systems": {"captions": "caption style/placement if any", "music": "music mood", "graphics": ["price-tag: pops on product mention"], "sfx": ["whoosh on cut"]}
}

Rules:
- Infer shot boundaries from CONSECUTIVE FRAME DIFFERENCES (a change of shot_size, camera motion, scene or on-screen text between adjacent frames marks a probable cut).
- All times in seconds, within [0, duration]. Be honest about precision: this is a relationship replica, not a pixel replica.
- on_screen_text comes from the frame analyses; leave empty when none was detected.
- When a word-level transcript is provided, `line` of each beat MUST quote its spoken words verbatim, and `systems.graphics`/`systems.sfx` entries should name the exact spoken word(s) that trigger them (e.g. "price-tag: pops on the word 价格"). Without a transcript, leave `line` empty.
- Keep it useful for recreation: the shot table will be reused to re-cut a NEW video with different subject/product/copy.
- Be concise: whole_piece_reading is 2-3 short sentences; beat/shot descriptions stay under 30 characters. JSON must be small enough to parse.
Do not include any text outside the JSON object."""


def _serialize_transcript(transcript: TeardownTranscriptInfo) -> str:
    """词级转录 → 综合拆解的文本块（时间脊柱：词/句 → 秒）。"""
    if not transcript.lines:
        return ""
    rows = "\n".join(
        f"[{line['start_seconds']:.2f}-{line['end_seconds']:.2f}s] {line['text']}"
        for line in transcript.lines
    )
    return f"Word-level transcript of the audio:\n{rows}\n\n"


def _synthesize_teardown(
    client: Any,
    base_url: str,
    api_key: str,
    model: str,
    frames: list[TeardownFrameAnalysis],
    duration_seconds: float,
    user_description: str | None,
    transcript: TeardownTranscriptInfo | None = None,
) -> dict[str, Any]:
    """One LLM call: frame analyses + metadata (+ transcript) → teardown JSON dict."""
    user_text = (
        f"The reference video is {duration_seconds:.1f}s long. "
        f"I analyzed {len(frames)} evenly-spaced frames:\n"
        f"{_serialize_frame_analyses(frames)}\n\n"
    )
    if transcript is not None:
        user_text += _serialize_transcript(transcript)
    if user_description:
        user_text += f"User's note about the video: {user_description}\n\n"
    user_text += "Produce the structured teardown JSON."

    raw = _call_multimodal_llm(
        client=client,
        base_url=base_url,
        api_key=api_key,
        model=model,
        system_prompt=_TEARDOWN_SYNTHESIS_SYSTEM_PROMPT,
        user_text=user_text,
        image_path=None,
        max_tokens=DEFAULT_MAX_TOKENS_SYNTHESIS,
        extra_payload={"reasoning_effort": "low"},
    )
    return _extract_json_from_response(raw)


# ---------------------------------------------------------------------------
# normalize 兜底（LLM 输出不可信：默认值 + 钳制 + 派生）
# ---------------------------------------------------------------------------


def _clamp(value: Any, low: float, high: float, default: float) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    if number != number:  # NaN
        return default
    return max(low, min(high, number))


def _normalize_shots(
    data: dict[str, Any], duration_seconds: float
) -> list[dict[str, Any]]:
    """Normalize the shot list: clamp times, sequential index, sane defaults."""
    raw_shots = data.get("shots")
    shots: list[dict[str, Any]] = []
    if isinstance(raw_shots, list):
        for raw in raw_shots:
            if not isinstance(raw, dict):
                continue
            start = _clamp(raw.get("start_seconds"), 0.0, duration_seconds, 0.0)
            end = _clamp(raw.get("end_seconds"), 0.0, duration_seconds, duration_seconds)
            if end < start:
                start, end = end, start
            shots.append(
                {
                    "start_seconds": round(start, 2),
                    "end_seconds": round(end, 2),
                    "shot_size": str(raw.get("shot_size") or "medium"),
                    "camera_motion": str(raw.get("camera_motion") or "static"),
                    "subject_action": str(raw.get("subject_action") or ""),
                    "on_screen_text": str(raw.get("on_screen_text") or ""),
                    "transition_to_next": str(raw.get("transition_to_next") or "cut"),
                    "note": str(raw.get("note") or ""),
                }
            )

    if not shots:
        # LLM 没给出可用镜头表：退化为单镜头全片，而不是失败。
        shots = [
            {
                "start_seconds": 0.0,
                "end_seconds": round(duration_seconds, 2),
                "shot_size": "medium",
                "camera_motion": "static",
                "subject_action": "",
                "on_screen_text": "",
                "transition_to_next": "cut",
                "note": "LLM 未给出镜头表，已退化为单镜头全片",
            }
        ]

    shots.sort(key=lambda s: (s["start_seconds"], s["end_seconds"]))
    for i, shot in enumerate(shots, start=1):
        shot["index"] = i
    return shots


def _normalize_beats(
    data: dict[str, Any], duration_seconds: float
) -> list[dict[str, Any]]:
    raw_beats = data.get("beats")
    beats: list[dict[str, Any]] = []
    if isinstance(raw_beats, list):
        for raw in raw_beats:
            if not isinstance(raw, dict):
                continue
            start = _clamp(raw.get("start_seconds"), 0.0, duration_seconds, 0.0)
            end = _clamp(raw.get("end_seconds"), 0.0, duration_seconds, duration_seconds)
            if end < start:
                start, end = end, start
            beats.append(
                {
                    "role": str(raw.get("role") or "body"),
                    "description": str(raw.get("description") or ""),
                    "line": str(raw.get("line") or "")[:2_048],
                    "start_seconds": round(start, 2),
                    "end_seconds": round(end, 2),
                }
            )
    beats.sort(key=lambda b: b["start_seconds"])
    return beats


def _normalize_rhythm(
    data: dict[str, Any],
    shots: list[dict[str, Any]],
    duration_seconds: float,
) -> dict[str, Any]:
    raw = data.get("rhythm")
    raw = raw if isinstance(raw, dict) else {}

    avg = _clamp(raw.get("avg_shot_seconds"), 0.0, duration_seconds, 0.0)
    if avg <= 0.0:
        avg = duration_seconds / len(shots) if shots else duration_seconds

    cut_points: list[float] = []
    raw_cuts = raw.get("cut_points_seconds")
    if isinstance(raw_cuts, list):
        cut_points = [
            round(_clamp(c, 0.0, duration_seconds, 0.0), 2) for c in raw_cuts
        ]
    if not cut_points:
        # 从镜头表派生：每个镜头的起点即一个切点（含 0）。
        cut_points = sorted({round(s["start_seconds"], 2) for s in shots} | {0.0})

    return {
        "avg_shot_seconds": round(avg, 2),
        "cut_points_seconds": cut_points,
        "energy_curve": str(raw.get("energy_curve") or ""),
    }


def _normalize_systems(data: dict[str, Any]) -> dict[str, Any]:
    raw = data.get("systems")
    raw = raw if isinstance(raw, dict) else {}

    def _str_list(value: Any) -> list[str]:
        if isinstance(value, list):
            return [str(v) for v in value if str(v).strip()]
        if isinstance(value, str) and value.strip():
            return [value]
        return []

    return {
        "captions": str(raw.get("captions") or ""),
        "music": str(raw.get("music") or ""),
        "graphics": _str_list(raw.get("graphics")),
        "sfx": _str_list(raw.get("sfx")),
    }


def _build_constraints(
    num_frames_analyzed: int, transcript: Any | None = None
) -> list[str]:
    """面向用户的诚实声明（复刻关系，不复刻像素；降级显式可查询）。"""
    constraints = [
        "镜头边界与运动为 LLM 基于稀疏抽帧的推断值，非帧级测量；复刻目标是结构与关系，不是像素还原。",
        "拆解结果为复刻蓝图的初稿：保留镜头顺序/节奏/系统关系，替换人物/商品/台词/风格后由画布继续创作。",
    ]
    if num_frames_analyzed < DEFAULT_NUM_FRAMES:
        constraints.append(
            f"仅分析 {num_frames_analyzed} 帧（默认 {DEFAULT_NUM_FRAMES} 帧），细节有限。"
        )
    if transcript is not None and not transcript.available:
        reason_note = {
            "engine_disabled": "未启用 whisperX（SPEECH_ALIGNMENT_ENGINE=whisperx 开启）",
            "no_audio_track": "未提取到音轨",
            "engine_unavailable": "whisperX 未安装或加载失败",
            "failed": "whisperX 转录失败",
        }.get(transcript.reason, transcript.reason or "未知原因")
        constraints.append(
            f"词级转录不可用（{reason_note}），锚点事件停留在段落级；"
            "安装 whisperX 并启用后可升级为词级锚定。"
        )
    return constraints


# ---------------------------------------------------------------------------
# 复刻分镜草稿（确定性生成，不调 LLM——拉片报告→正常创作流的桥）
# ---------------------------------------------------------------------------


def build_replica_draft(report: TeardownReport) -> str:
    """Render the teardown report as a paste-ready Chinese storyboard draft.

    Deterministic (no LLM): the user pastes this into a script node or the
    agent chat to continue the normal creation flow.
    """
    lines: list[str] = []
    lines.append("# 复刻分镜草稿（来自拉片复刻 · 参考片拆解）")
    lines.append(f"格式判断：{report.format_name or 'short-video'}")
    lines.append("")

    if report.whole_piece_reading:
        lines.append("## 整片解读")
        lines.append(report.whole_piece_reading.strip())
        lines.append("")

    if report.beats:
        lines.append("## 结构")
        for beat in report.beats:
            lines.append(
                f"- [{beat.start_seconds:.1f}–{beat.end_seconds:.1f}s] "
                f"{beat.role}：{beat.description}"
            )
        lines.append("")

    lines.append(f"## 镜头表（共 {len(report.shots)} 个镜头）")
    for shot in report.shots:
        text = shot.on_screen_text.strip() or "无"
        lines.append(
            f"{shot.index}. [{shot.start_seconds:.1f}–{shot.end_seconds:.1f}s] "
            f"{shot.shot_size} / {shot.camera_motion} — "
            f"{shot.subject_action or '（动作未标注）'}。屏上文字：{text}。"
            f"转场：{shot.transition_to_next}"
        )
    lines.append("")

    rhythm = report.rhythm
    lines.append("## 节奏")
    lines.append(f"平均镜头 {rhythm.avg_shot_seconds:.1f}s；"
                 f"切点：{', '.join(f'{c:g}' for c in rhythm.cut_points_seconds)}")
    if rhythm.energy_curve:
        lines.append(f"能量曲线：{rhythm.energy_curve}")
    lines.append("")

    systems = report.systems
    lines.append("## 视觉系统")
    lines.append(f"字幕：{systems.captions or '未检测到'}")
    lines.append(f"音乐：{systems.music or '未检测到'}")
    lines.append(
        "图形/MG：" + ("；".join(systems.graphics) if systems.graphics else "未检测到")
    )
    lines.append("音效：" + ("；".join(systems.sfx) if systems.sfx else "未检测到"))
    lines.append("")

    lines.append("## 复刻提示")
    lines.append("- 保留：镜头顺序、节奏、转场方式与视觉系统关系。")
    lines.append("- 替换：人物、商品、场景、台词与风格（在画布中继续创作）。")
    lines.append("- 提示：镜头边界为推断值，实际复刻时以创作流中的分镜脚本为准微调。")
    lines.append("")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# 主入口
# ---------------------------------------------------------------------------


def analyze_reference_teardown(
    video_path: str | Path,
    num_frames: int = DEFAULT_NUM_FRAMES,
    user_description: str | None = None,
    *,
    use_cache: bool = True,
    cache_dir: Path | None = None,
) -> TeardownResult:
    """分析参考视频，产出拉片拆解报告 + 复刻分镜草稿。

    Args:
        video_path: 参考视频文件路径。
        num_frames: 均匀抽帧数（clamp 到 [MIN_NUM_FRAMES, MAX_NUM_FRAMES]）。
        user_description: 用户补充说明，引导 LLM 读片。
        use_cache: 命中内容 hash + 参数 + 模型 + 转录状态相同的缓存时直接
            复用（跳过全部 LLM 调用，结果标注 ``cached=True``）。
        cache_dir: 缓存目录（默认 ``<media_data_dir>/replica_teardown_cache``）。

    Raises:
        AnalysisError: 配置缺失 / 输入非法 / LLM 失败 / 报告校验失败。
    """
    num_frames = max(MIN_NUM_FRAMES, min(MAX_NUM_FRAMES, int(num_frames)))
    video_path = Path(video_path)
    if not video_path.exists():
        raise AnalysisError(f"Video not found: {video_path}", error_type="input")

    # 1. 元数据 + 时长校验
    metadata = extract_metadata(video_path)
    if metadata.duration_seconds > MAX_TEARDOWN_DURATION_SECONDS:
        raise AnalysisError(
            f"Video too long: {metadata.duration_seconds:.1f}s "
            f"(max {MAX_TEARDOWN_DURATION_SECONDS:.0f}s for a teardown)",
            error_type="input",
        )

    # 2. 模型身份 + 词级转录（缓存键的两个输入）。转录前置是有意为之：
    # 转录的 source/reason 决定报告内容（进键），换来"降级转录的报告不会
    # 被 whisperx 正常的运行命中"的精确性；引擎默认关闭时转录零成本。
    # client 在缓存检查前构建（不产生连接；命中即关）——配置校验只此一条
    # 路径，不复制"LLM 未配置"的第二份判断。
    from app.services.replica.transcribe import transcribe_reference_video

    transcript = transcribe_reference_video(video_path)
    transcript_info = TeardownTranscriptInfo(**transcript.to_report_dict())
    client, base_url, api_key, model = _build_llm_client()

    def _close_client() -> None:
        close = getattr(client, "close", None)
        if callable(close):
            close()

    # 2.5 G6 缓存：命中即返回（不抽帧、不调 LLM）
    resolved_cache_dir = cache_dir or teardown_cache_dir(get_settings().media_data_dir)
    cache_key = ""
    if use_cache:
        cache_key = teardown_cache_key(
            video_path=video_path,
            num_frames=num_frames,
            user_description=user_description,
            model=model,
            transcript_source=str(transcript_info.source),
            transcript_reason=transcript_info.reason,
        )
        cached = _teardown_result_from_cache(
            load_cached_teardown(resolved_cache_dir, cache_key),
            user_description=user_description,
            cache_key=cache_key,
        )
        if cached is not None:
            _close_client()
            return cached

    # 2. 均匀抽帧（复用 scene3d 基建；时间戳按同一匀排公式还原）。
    # 临时目录必须覆盖到逐帧分析：帧文件在分析时仍要读取——此前 with 块
    # 提前结束导致真实运行必然"关键帧不存在"（单测全 mock 未暴露，E2E 首跑抓住）。
    import tempfile

    with tempfile.TemporaryDirectory(prefix="replica_teardown_") as tmp_dir:
        keyframe_paths = extract_keyframes_from_video(
            video_path, Path(tmp_dir), num_frames
        )
        if not keyframe_paths:
            raise AnalysisError(
                "Failed to extract frames from the video", error_type="input"
            )
        # extract_keyframes_from_video 只返回路径；时间戳与它的匀排公式一致：
        # t_i = duration * i / (num_frames - 1)，实际抽到几张就用几张。
        extracted = len(keyframe_paths)
        timestamps = [
            (metadata.duration_seconds * i) / (extracted - 1) if extracted > 1 else 0.0
            for i in range(extracted)
        ]

        # 3. LLM：逐帧分析 → 综合拆解（词级转录可用时进入综合视野）
        try:
            frame_analyses = [
                _analyze_teardown_frame(
                    client=client,
                    base_url=base_url,
                    api_key=api_key,
                    model=model,
                    image_path=Path(keyframe_path),
                    frame_index=i,
                    timestamp_seconds=timestamps[i],
                    total_frames=extracted,
                )
                for i, keyframe_path in enumerate(keyframe_paths)
            ]

            teardown_data = _synthesize_teardown(
                client=client,
                base_url=base_url,
                api_key=api_key,
                model=model,
                frames=frame_analyses,
                duration_seconds=metadata.duration_seconds,
                user_description=user_description,
                transcript=transcript_info,
            )
        finally:
            _close_client()

    # 4. normalize + schema 校验（LLM 输出不可信）
    shots = _normalize_shots(teardown_data, metadata.duration_seconds)
    normalized = {
        "whole_piece_reading": str(teardown_data.get("whole_piece_reading") or ""),
        "format_name": str(teardown_data.get("format_name") or "short-video"),
        "shots": shots,
        "beats": _normalize_beats(teardown_data, metadata.duration_seconds),
        "transcript": transcript_info,
        "rhythm": _normalize_rhythm(teardown_data, shots, metadata.duration_seconds),
        "systems": _normalize_systems(teardown_data),
    }
    try:
        report = TeardownReport.model_validate(normalized)
    except Exception as exc:
        raise AnalysisError(
            f"Teardown report validation failed: {exc}", error_type="report_validation"
        )

    # 5. 确定性生成复刻分镜草稿（不调 LLM）
    report.replica_storyboard_draft = build_replica_draft(report)
    report.constraints = _build_constraints(len(frame_analyses), transcript)

    result = TeardownResult(
        report=report,
        frame_analyses=frame_analyses,
        video_metadata=metadata,
        num_frames_analyzed=len(frame_analyses),
        user_description=user_description,
        # 新算的报告同样带上它落盘的缓存键（cached=False 但键可追溯）；
        # use_cache=False 时没有键，留空——不假装自己有缓存身份。
        cache_key=cache_key if use_cache else "",
    )

    # 5.5 G6 缓存写入：只缓存完整成功的分析（fixture 降级/失败不进缓存）。
    # 尽力而为——写失败只是下次全价，不影响本次结果。
    if use_cache and cache_key:
        save_cached_teardown(
            resolved_cache_dir,
            cache_key,
            {
                "cache_schema": CACHE_SCHEMA_VERSION,
                "key": cache_key,
                "num_frames_analyzed": result.num_frames_analyzed,
                "report": report.model_dump(mode="json"),
                "frame_analyses": [
                    dataclasses.asdict(frame) for frame in frame_analyses
                ],
                "video_metadata": dataclasses.asdict(metadata),
            },
        )

    return result


def _teardown_result_from_cache(
    payload: dict[str, Any] | None,
    *,
    user_description: str | None,
    cache_key: str,
) -> TeardownResult | None:
    """把缓存 payload 复核成 TeardownResult；任何复核失败返回 None（miss）。

    **缓存数据不可信**：schema 会漂移（升级后旧格式）、文件会被手改——
    所以逐字段 model_validate，失败即当 miss 退化为全价分析，绝不把坏数据
    当报告返回。命中时追加缓存标注（constraints），并在结果上置 cached。
    """
    if payload is None:
        return None
    try:
        report = TeardownReport.model_validate(payload.get("report"))
        frames = [
            TeardownFrameAnalysis(**frame)
            for frame in (payload.get("frame_analyses") or [])
            if isinstance(frame, dict)
        ]
        metadata = VideoMetadata(**payload.get("video_metadata") or {})
        num_frames_analyzed = int(payload.get("num_frames_analyzed", len(frames)))
    except Exception:
        return None
    report.constraints = [*report.constraints, CACHED_REPORT_NOTE]
    return TeardownResult(
        report=report,
        frame_analyses=frames,
        video_metadata=metadata,
        num_frames_analyzed=num_frames_analyzed,
        user_description=user_description,
        cached=True,
        cache_key=cache_key,
    )
