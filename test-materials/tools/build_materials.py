r"""重建 test-materials/ 下的全部合成测试素材（无版权依赖：全部 ffmpeg 合成）。

布局（风格单元化）：每个风格单元目录自包含——unit.md（方案）+ brief.txt +
视频素材；非风格型公共夹具（边界片/节拍轨/参考图）放 fixtures/。

- units/replica-*/         拉片复刻风格矩阵（9 套：快剪带货/慢节奏质感/对话
                           小剧场/纯字幕直出/动作运镜/卡点混剪/对比测评/探店
                           vlog/教程步骤）
- units/scene-*/           3D 预演 NL 场景模板（7 套，含负例）
- fixtures/videos|audio|images/  公共夹具（无声/边界时长/切片锚/节拍/参考图）
- truth.json               机器可读真值（run_tests.py 的 media/quality 套件据
                           此断言；改素材必须重跑本脚本同步真值）

用法：python tools/build_materials.py
依赖：本机 ffmpeg（PATH 内），无其他依赖。产物可随时删除重建。

已知坑（沿用 apps/api/scripts/replica_e2e_build_samples.py 的教训）：
- drawtext 的裸 % 是文本扩展转义符，会静默吞字——样例文案一律避开 %；
- Windows 字体路径在 lavfi 里写成 'C\:/Windows/Fonts/...'；
- 滤镜表达式内的逗号用单引号整体包裹保护；
- zoompan 默认视口锚左上角，必须显式居中，否则快 zoom 后段把居中文字推出画面。
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

MATERIALS = Path(__file__).resolve().parents[1]
UNITS = MATERIALS / "units"
FIXTURES = MATERIALS / "fixtures"
TRUTH_PATH = MATERIALS / "truth.json"

FONT_CJK = r"'C\:/Windows/Fonts/msyh.ttc'"
FONT_EN = r"'C\:/Windows/Fonts/arial.ttf'"


def _run(command: list[str]) -> None:
    completed = subprocess.run(command, capture_output=True, text=True)
    if completed.returncode != 0:
        raise RuntimeError(
            f"command failed: {' '.join(command[:8])}...\n{completed.stderr[-1200:]}"
        )


def _esc(text: str) -> str:
    """drawtext 文本转义：% 是文本扩展转义符（不转义会静默吞字）。"""
    return text.replace("%", "%%").replace(":", r"\:").replace("'", r"\'")


def drawtext(text: str, size: int, color: str = "white", font: str = FONT_EN,
             y: str = "(h-th)/2") -> str:
    return (
        f"drawtext=fontfile={font}:text='{_esc(text)}':fontsize={size}:"
        f"fontcolor={color}:x=(w-tw)/2:y={y}:borderw=3:bordercolor=black"
    )


def zoompan(direction: str, w: int, h: int, fps: int, rate: float = 0.002) -> str:
    if direction == "in":
        z = f"min(1+{rate}*on,1.6)"
    elif direction == "in-fast":
        z = f"min(1+{rate}*on,2.4)"
    elif direction == "out":
        z = f"max(1.6-{rate}*on,1.0)"
    elif direction == "out-fast":
        z = f"max(2.4-{rate}*on,1.0)"
    else:
        z = "1.0"
    # 视口必须显式居中：zoompan 默认 x=y=0（锚左上），快 zoom 后段会把居中
    # 文字推出画面，丢掉 on_screen_text 可读信号
    return (
        f"zoompan=z='{z}':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':"
        f"d=1:s={w}x{h}:fps={fps}"
    )


def pulse_expr(bpm: float, freq: int = 1000, amp: float = 0.7) -> str:
    """BPM 精确的指数衰减脉冲串表达式（供 aevalsrc）。"""
    interval = 60.0 / bpm
    return f"{amp}*sin({freq}*2*PI*t)*exp(-40*mod(t,{interval:.7f}))"


def _hex_rgb(h: str) -> list[int]:
    h = h.lstrip("#")
    return [int(h[i:i + 2], 16) for i in (0, 2, 4)]


# ---------------------------------------------------------------- 风格单元定义
# shot: (dur, 底色, 屏上文字, 文字色, zoom, 正弦频率)
# 文字色/底色同时进 truth.json，供 quality 套件做像素级断言

STYLE_UNITS = [
    {
        "id": "fastcut", "cn": "快剪带货", "file": "rep_fastcut_9x16_15s.mp4",
        "w": 540, "h": 960, "fps": 30, "preset": "veryfast", "crf": "28",
        "shots": [
            (2.5, "d7263d", "STOP SCROLLING", "ffffff", "in", 440, "white", 60),
            (2.5, "1b2a6b", "3 SECOND HACK", "ffffff", "out", 494, "white", 60),
            (2.5, "146b3a", "IT JUST WORKS", "ffffff", "in", 554, "white", 60),
            (2.5, "b3541e", "REAL RESULTS", "ffffff", "out", 622, "white", 60),
            (2.5, "6a1b4d", "HALF PRICE TODAY", "ffff00", "in", 698, "yellow", 60),
            (2.5, "2415a0", "BUY NOW", "ffffff", "out", 784, "white", 60),
        ],
    },
    {
        "id": "luxury", "cn": "高级慢节奏质感", "file": "rep_luxury_16x9_30s.mp4",
        "w": 1280, "h": 720, "fps": 24, "preset": "veryfast", "crf": "28",
        "shots": [
            # 相邻镜头底色需保持肉眼可辨的阶梯（切点帧差门 ≥8 MAD）
            (7.5, "0a0d12", "TIMELESS", "dddddd", "in", 110, "white", 44),
            (7.5, "171e29", "CRAFTED BY HAND", "dddddd", "in", 110, "white", 44),
            (7.5, "2a3547", "SINCE 1931", "dddddd", "in", 98, "white", 44),
            (7.5, "121721", "REDISCOVER SLOW", "dddddd", "in", 87, "white", 44),
        ],
        "zoom_rate": 0.0008, "vol": 0.15,
    },
    {
        "id": "dialogue", "cn": "中文对话小剧场", "file": "rep_dialogue_9x16_20s.mp4",
        "w": 540, "h": 960, "fps": 30, "preset": "veryfast", "crf": "28",
        "font": FONT_CJK, "text_size": 54,
        "shots": [
            (4, "7a3b2e", "A：你敢信？", "ffffff", None, 440, "white", 54),
            (4, "2e5a7a", "B：我不信。", "ffffff", None, 330, "white", 54),
            (4, "7a3b2e", "A：它真的有用！", "ffffff", None, 470, "white", 54),
            (4, "2e5a7a", "B：那我试试！", "ffffff", None, 350, "white", 54),
            (4, "5a2a7a", "合：冲！！", "ffff00", None, 550, "yellow", 54),
        ],
    },
    {
        "id": "textonly", "cn": "纯字幕直出", "file": "rep_textonly_1x1_10s.mp4",
        "w": 720, "h": 720, "fps": 30, "preset": "veryfast", "crf": "28",
        "font": FONT_CJK,
        "shots": [
            (2.5, "f5e6d3", "第一天 坚持早起", "333333", None, 880, "dark", 56),
            (2.5, "d9ecf5", "第七天 看得见变化", "223344", None, 880, "dark", 56),
            (2.5, "ecddf5", "第三十天 习惯成型", "332244", None, 880, "dark", 56),
            (2.5, "222831", "现在轮到你了", "ffffff", None, 880, "white", 56),
        ],
        "vol": 0.25,
    },
    {
        "id": "action", "cn": "动作快切运镜", "file": "rep_action_9x16_12s.mp4",
        "w": 540, "h": 960, "fps": 30, "preset": "veryfast", "crf": "28",
        "shots": [
            (1.5, "e63946", "GO", "ffffff", "in-fast", 1200, "white", 96),
            (1.5, "2a9d8f", "FASTER", "ffffff", "out-fast", 1200, "white", 80),
            (1.5, "e9c46a", "NOW", "222222", "in-fast", 1200, "dark", 96),
            (1.5, "264653", "GO", "ffffff", "out-fast", 1200, "white", 96),
            (1.5, "e76f51", "FASTER", "ffffff", "in-fast", 1200, "white", 80),
            (1.5, "8ab17d", "NOW", "222222", "out-fast", 1200, "dark", 96),
            (1.5, "2b2d42", "GO", "ffffff", "in-fast", 1200, "white", 96),
            (1.5, "ef476f", "NOW", "ffffff", "out-fast", 1200, "white", 96),
        ],
        "zoom_rate": 0.03,
    },
    {
        "id": "beatsync", "cn": "卡点混剪", "file": "rep_beatsync_9x16_16s.mp4",
        "w": 540, "h": 960, "fps": 30, "preset": "veryfast", "crf": "28",
        "pulse_audio": {"bpm": 120, "freq": 880, "amp": 0.4},
        "shots": [
            (1.0, color, text, "ffffff", zoom, 0, "white", 72)
            for color, text, zoom in zip(
                ["e63946", "2a9d8f", "e9c46a", "264653"] * 4,
                ["ONE", "TWO", "THREE", "GO"] * 4,
                ["in", "out"] * 8,
            )
        ],
        "zoom_rate": 0.015,
    },
    {
        "id": "compare", "cn": "对比测评", "file": "rep_compare_9x16_16s.mp4",
        "w": 540, "h": 960, "fps": 30, "preset": "veryfast", "crf": "28",
        "shots": [
            (4, "8a8a8a", "BEFORE", "ffffff", None, 300, "white", 60),
            (4, "f4a832", "AFTER", "ffffff", "in", 600, "white", 60),
            (4, "2a6f4e", "3X FASTER", "ffffff", "out", 450, "white", 60),
            (4, "1b3a5c", "VERDICT WORTH IT", "ffffff", None, 520, "white", 48),
        ],
    },
    {
        "id": "vlogtour", "cn": "探店vlog", "file": "rep_vlogtour_9x16_18s.mp4",
        "w": 540, "h": 960, "fps": 30, "preset": "veryfast", "crf": "28",
        "shots": [
            (3, "c96f3a", "COME WITH ME", "ffffff", "in", 440, "white", 60),
            (3, "3a6fc9", "THIS PLACE", "ffffff", "out", 494, "white", 60),
            (3, "c9a53a", "ONLY 10 YUAN", "ffffff", "in", 554, "white", 60),
            (3, "7a3ac9", "SO CROWDED", "ffffff", "out", 622, "white", 60),
            (3, "3ac97a", "MUST TRY", "ffffff", "in", 698, "white", 60),
            (3, "c93a6f", "SAVE THIS", "ffffff", "out", 784, "white", 60),
        ],
    },
    {
        "id": "tutorial", "cn": "教程步骤", "file": "rep_tutorial_1x1_16s.mp4",
        "w": 720, "h": 720, "fps": 30, "preset": "veryfast", "crf": "28",
        "shots": [
            # 浅色系但相邻色差足够（奶油→薄荷→periwinkle→绯红调）
            (4, "f5ead0", "STEP 1 PREP", "333333", None, 660, "dark", 56),
            (4, "d8eedd", "STEP 2 MIX", "333333", None, 660, "dark", 56),
            (4, "d6e2f5", "STEP 3 COOK", "333333", None, 660, "dark", 56),
            (4, "f2dcea", "STEP 4 PLATE", "333333", None, 660, "dark", 56),
        ],
        "vol": 0.2,
    },
]

# 公共夹具（非风格型）：边界片 / 功能线专用片
FIXTURE_VIDEOS = [
    {"id": "silent", "file": "rep_silent_16x9_8s.mp4", "w": 640, "h": 360, "fps": 24,
     "duration": 8, "audio": False,
     "shots": [(8, "1c1c1c", "SILENT TAKE", "ffffff", None, 0, "white", 48)]},
    {"id": "edge4", "file": "rep_edge_4s_9x16.mp4", "w": 360, "h": 640, "fps": 24,
     "duration": 4, "audio": True,
     "shots": [(4, "333333", "SHORT CLIP", "ffffff", None, 440, "white", 40)]},
    {"id": "overlong", "file": "rep_overlong_16x9_61s.mp4", "w": 320, "h": 180,
     "fps": 24, "duration": 61, "audio": False, "shots": [(61, "2b2b2b", None, None, None, 0, None, 0)]},
    {"id": "s3d-refroom", "file": "s3d_refroom_16x9_8s.mp4", "w": 960, "h": 540,
     "fps": 24, "duration": 8, "audio": True, "shots": None,   # 连续横移，无静态镜头真值
     "text_spot": {"t": 2.0, "text_color": [255, 255, 255]}},
    {"id": "slice-ref", "file": "slice_ref_16x9_40s.mp4", "w": 480, "h": 270,
     "fps": 24, "duration": 40, "audio": True, "preset": "ultrafast", "crf": "30",
     "shots": [(5, color, str(i), "ffffff", None, 300 + 40 * i, "white", 140)
               for i, color in enumerate(
                   ["4455aa", "44aa55", "aa4455", "aaaa44",
                    "44aaaa", "aa44aa", "5588aa", "aa8855"], start=1)]},
]

BEAT_TRACKS = [
    ("beat_120bpm_20s.wav", 120, 20),
    ("beat_90bpm_20s.wav", 90, 20),
    ("beat_140bpm_accent_30s.wav", 140, 30),
    ("beat_mixed_120to150_20s.wav", None, 20),   # 变速：无单一真值
    ("beat_tooshort_1s.wav", 120, 1),
    ("beat_60bpm_20s.wav", 60, 20),
    ("beat_170bpm_20s.wav", 170, 20),
    ("beat_silent_10s.wav", None, 10),
    ("ref_music_15s.wav", None, 15),
]


# ---------------------------------------------------------------- 构建函数

def build_shots_video(out_path: Path, w: int, h: int, fps: int, shots: list[dict],
                      preset: str = "veryfast", crf: str = "28") -> None:
    """多镜头样片：每镜纯色底 + 屏上文字 + zoompan + 不同频率正弦音轨，concat 成片。"""
    part_paths: list[Path] = []
    for index, shot in enumerate(shots, start=1):
        part = out_path.parent / f"_{out_path.stem}_part{index}.mp4"
        vf_parts = []
        if shot.get("text"):
            vf_parts.append(
                drawtext(shot["text"], shot.get("text_size", 60),
                         shot.get("text_color", "white"), shot.get("font", FONT_EN))
            )
        if shot.get("zoom"):
            vf_parts.append(zoompan(shot["zoom"], w, h, fps, shot.get("zoom_rate", 0.002)))
        cmd = [
            "ffmpeg", "-y", "-v", "error",
            "-f", "lavfi", "-i",
            f"color=c=0x{shot['color']}:s={w}x{h}:d={shot['dur']}:r={fps}",
        ]
        if shot.get("freq"):
            cmd += ["-f", "lavfi", "-i", f"sine=frequency={shot['freq']}:duration={shot['dur']}"]
        if vf_parts:
            cmd += ["-vf", ",".join(vf_parts)]
        if shot.get("freq"):
            cmd += ["-af", f"volume={shot.get('vol', 0.35)}"]
        cmd += [
            "-c:v", "libx264", "-preset", preset, "-crf", crf, "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-shortest", str(part),
        ]
        _run(cmd)
        part_paths.append(part)

    concat_list = out_path.parent / f"_{out_path.stem}_concat.txt"
    concat_list.write_text(
        "\n".join(f"file '{p.as_posix()}'" for p in part_paths), encoding="utf-8"
    )
    _run([
        "ffmpeg", "-y", "-v", "error", "-f", "concat", "-safe", "0",
        "-i", str(concat_list), "-c", "copy", str(out_path),
    ])
    for part in part_paths:
        part.unlink()
    concat_list.unlink()


def mux_pulse(out_path: Path, bpm: float, freq: int, seconds: float, amp: float) -> None:
    """给已拼好的成片整段铺 BPM 脉冲音轨（卡点素材用，切点=整拍）。"""
    tmp = out_path.with_name(f"_{out_path.stem}_muxed.mp4")
    _run([
        "ffmpeg", "-y", "-v", "error",
        "-i", str(out_path),
        "-f", "lavfi", "-i",
        f"aevalsrc='{pulse_expr(bpm, freq=freq, amp=amp)}':s=44100:d={seconds}",
        "-c:v", "copy", "-c:a", "aac", "-shortest", str(tmp),
    ])
    tmp.replace(out_path)


def build_unit_video(unit: dict) -> None:
    out = UNITS / f"replica-{unit['id']}" / unit["file"]
    out.parent.mkdir(parents=True, exist_ok=True)
    shots = [
        dict(dur=dur, color=color, text=text, text_color=draw_color,
             text_size=size, zoom=zoom, zoom_rate=unit.get("zoom_rate", 0.002),
             freq=freq, vol=unit.get("vol", 0.35), font=unit.get("font", FONT_EN))
        for dur, color, text, draw_color, zoom, freq, _tag, size in unit["shots"]
    ]
    build_shots_video(out, unit["w"], unit["h"], unit["fps"], shots,
                      unit.get("preset", "veryfast"), unit.get("crf", "28"))
    if "pulse_audio" in unit:
        pa = unit["pulse_audio"]
        mux_pulse(out, pa["bpm"], pa["freq"], sum(s[0] for s in unit["shots"]), pa["amp"])


def build_fixture_video(fixture: dict) -> None:
    out = FIXTURES / "videos" / fixture["file"]
    out.parent.mkdir(parents=True, exist_ok=True)
    if fixture["id"] == "s3d-refroom":
        _run([
            "ffmpeg", "-y", "-v", "error",
            "-f", "lavfi", "-i", "color=c=0x2b2b3a:s=1600x540:d=8:r=24",
            "-f", "lavfi", "-i", "sine=frequency=220:duration=8",
            "-vf", ",".join([
                "drawbox=x=0:y=400:w=1600:h=140:color=0x3a3a4a:t=fill",
                "drawbox=x=200:y=90:w=180:h=150:color=0x87ceeb:t=fill",
                "drawbox=x=520:y=280:w=160:h=120:color=0x6a5acd:t=fill",
                "drawbox=x=900:y=260:w=180:h=140:color=0x2e8b57:t=fill",
                "drawbox=x=1280:y=290:w=150:h=110:color=0xcd853f:t=fill",
                drawtext("3D REF ROOM", 40, "white", FONT_EN, y="40"),
                "crop=960:540:x='min(640*t/7.5,640)':y=0",
            ]),
            "-af", "volume=0.2",
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "28", "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-shortest", str(out),
        ])
        return
    shots = [
        dict(dur=dur, color=color, text=text, text_color=draw_color, text_size=size,
             zoom=zoom, freq=freq, vol=0.35, font=FONT_EN)
        for dur, color, text, draw_color, zoom, freq, _tag, size in fixture["shots"]
    ]
    if fixture["id"] == "overlong":
        _run([
            "ffmpeg", "-y", "-v", "error",
            "-f", "lavfi", "-i", "color=c=0x2b2b2b:s=320x180:d=61:r=24",
            "-c:v", "libx264", "-preset", "ultrafast", "-crf", "32", "-pix_fmt", "yuv420p",
            str(out),
        ])
        return
    if not fixture["audio"]:
        # 无音轨：逐镜构建后 concat，再整体删音轨（concat 要求流一致）
        build_shots_video(out, fixture["w"], fixture["h"], fixture["fps"],
                          [{**s, "freq": 0} for s in shots],
                          preset=fixture.get("preset", "veryfast"))
        silent = out.with_name(f"_{out.stem}_silent.mp4")
        _run(["ffmpeg", "-y", "-v", "error", "-i", str(out), "-an", "-c:v", "copy",
              str(silent)])
        silent.replace(out)
        return
    build_shots_video(out, fixture["w"], fixture["h"], fixture["fps"], shots,
                      preset=fixture.get("preset", "veryfast"),
                      crf=fixture.get("crf", "28"))


def build_audio_fixtures() -> None:
    out_dir = FIXTURES / "audio"
    out_dir.mkdir(parents=True, exist_ok=True)
    for name, bpm, dur in BEAT_TRACKS:
        if name == "beat_silent_10s.wav":
            _run(["ffmpeg", "-y", "-v", "error",
                  "-f", "lavfi", "-i", "anullsrc=r=44100:cl=mono:d=10",
                  "-c:a", "pcm_s16le", str(out_dir / name)])
        elif name == "ref_music_15s.wav":
            _run(["ffmpeg", "-y", "-v", "error",
                  "-f", "lavfi", "-i", "sine=frequency=220:duration=15",
                  "-f", "lavfi", "-i", "sine=frequency=277:duration=15",
                  "-f", "lavfi", "-i", "sine=frequency=330:duration=15",
                  "-filter_complex",
                  "[0:a][1:a][2:a]amix=inputs=3:normalize=1,volume=0.5[out]",
                  "-map", "[out]", "-c:a", "pcm_s16le", str(out_dir / name)])
        elif name == "beat_140bpm_accent_30s.wav":
            expr = ("0.9*sin(70*2*PI*t)*exp(-22*mod(t,0.4285714))"
                    "+0.25*sin(5000*2*PI*t)*exp(-150*mod(t,0.2142857))")
            _run(["ffmpeg", "-y", "-v", "error",
                  "-f", "lavfi", "-i", f"aevalsrc='{expr}':s=44100:d={dur}",
                  "-c:a", "pcm_s16le", str(out_dir / name)])
        elif name == "beat_mixed_120to150_20s.wav":
            expr = ("if(lt(t,10)," + pulse_expr(120) + "," + pulse_expr(150, freq=1200) + ")")
            _run(["ffmpeg", "-y", "-v", "error",
                  "-f", "lavfi", "-i", f"aevalsrc='{expr}':s=44100:d={dur}",
                  "-c:a", "pcm_s16le", str(out_dir / name)])
        else:
            _run(["ffmpeg", "-y", "-v", "error",
                  "-f", "lavfi", "-i",
                  f"aevalsrc='{pulse_expr(bpm)}:s=44100:d={dur}'",
                  "-c:a", "pcm_s16le", str(out_dir / name)])


def build_image_fixtures() -> None:
    out_dir = FIXTURES / "images"
    out_dir.mkdir(parents=True, exist_ok=True)

    def png(name: str, vf: list[str], src: str) -> None:
        _run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", src,
              "-vf", ",".join(vf), "-frames:v", "1", str(out_dir / name)])

    png("s3d_room_800x600.png", [
        "drawbox=x=0:y=420:w=800:h=180:color=0x3a3a4a:t=fill",
        "drawbox=x=100:y=80:w=160:h=140:color=0x87ceeb:t=fill",
        "drawbox=x=450:y=320:w=240:h=120:color=0x8a5a3a:t=fill",
        drawtext("ROOM 01", 36, "white", FONT_EN, y="30"),
    ], "gradients=s=800x600:c0=0x2b2b3a:c1=0x6a5acd:d=1")
    png("s3d_panorama_2048x1024.png", [
        "drawbox=x=0:y=512:w=2048:h=6:color=white@0.8:t=fill",
        "drawbox=x=150:y=380:w=120:h=130:color=0xcd853f:t=fill",
        "drawbox=x=700:y=350:w=140:h=160:color=0x2e8b57:t=fill",
        "drawbox=x=1300:y=400:w=110:h=110:color=0x6a5acd:t=fill",
        "drawbox=x=1800:y=360:w=130:h=150:color=0x87ceeb:t=fill",
        drawtext("PANORAMA 2 TO 1", 44, "white", FONT_EN, y="60"),
    ], "gradients=s=2048x1024:c0=0x87b5d8:c1=0x3a4a5a:d=1")
    png("s3d_corridor_depth_800x600.png", [
        "drawbox=x=60:y=60:w=680:h=480:color=0x101018:t=fill",
        "drawbox=x=160:y=150:w=480:h=300:color=0x2a2a3a:t=fill",
        "drawbox=x=300:y=230:w=200:h=140:color=0x55557a:t=fill",
        "drawbox=x=360:y=270:w=80:h=60:color=0xb0b0e0:t=fill",
        drawtext("CORRIDOR DEPTH", 32, "white", FONT_EN, y="20"),
    ], "gradients=s=800x600:c0=0x0a0a12:c1=0xd0d0ff:d=1")
    for i in range(1, 7):
        png(f"s3d_orbit_{i}_512x512.png", [
            "drawbox=x=186:y=166:w=140:h=180:color=white@0.92:t=fill",
            "drawbox=x=216:y=106:w=80:h=60:color=white@0.92:t=fill",
            f"drawbox=x={40 + i * 60}:y=60:w=44:h=44:color=0xffe066:t=fill",
            drawtext(f"ORBIT {i} OF 6", 28, "white", FONT_EN, y="440"),
        ], f"gradients=s=512x512:c0=0x22223a:c1=0x{0x30 + i * 8:02x}5a7a:d=1")
    png("ref_product_3x4_768x1024.png", [
        "drawbox=x=264:y=312:w=240:h=400:color=white@0.92:t=fill",
        "drawbox=x=314:y=232:w=140:h=80:color=white@0.92:t=fill",
        drawtext("PRODUCT 3 TO 4", 44, "white", FONT_EN, y="60"),
    ], "gradients=s=768x1024:c0=0x22223a:c1=0x6a5acd:d=1")
    png("ref_turnaround_3view_1536x512.png", [
        "drawbox=x=128:y=176:w=120:h=200:color=white@0.92:t=fill",
        "drawbox=x=688:y=176:w=160:h=200:color=white@0.92:t=fill",
        "drawbox=x=1248:y=176:w=120:h=200:color=white@0.92:t=fill",
        drawtext("TURNAROUND ANTI CASE", 40, "white", FONT_EN, y="50"),
    ], "gradients=s=1536x512:c0=0x3a2a1a:c1=0xd2a679:d=1")
    png("ref_ultrawide_1024x288.png", [
        drawtext("ULTRAWIDE 32 TO 9 ANTI CASE", 32, "white", FONT_EN),
    ], "gradients=s=1024x288:c0=0x1a1a2a:c1=0x8a2a5a:d=1")


# ---------------------------------------------------------------- truth.json

def emit_truth() -> None:
    videos = []
    for unit in STYLE_UNITS:
        videos.append({
            "id": unit["id"], "unit": f"replica-{unit['id']}", "cn": unit["cn"],
            "path": f"units/replica-{unit['id']}/{unit['file']}",
            "w": unit["w"], "h": unit["h"], "fps": unit["fps"],
            "duration": sum(s[0] for s in unit["shots"]), "audio": True,
            "shots": [
                {"dur": dur, "color": _hex_rgb(color),
                 "text": text, "text_color": _hex_rgb(tcolor),
                 "tag": tag}
                for dur, color, text, tcolor, _z, _f, tag, _s in unit["shots"]
            ],
        })
    for fx in FIXTURE_VIDEOS:
        videos.append({
            "id": fx["id"], "unit": None, "cn": fx["id"], "path": f"fixtures/videos/{fx['file']}",
            "w": fx["w"], "h": fx["h"], "fps": fx["fps"],
            "duration": fx["duration"],
            "audio": fx["audio"],
            "text_spot": fx.get("text_spot"),
            "shots": None if fx["shots"] is None else [
                {"dur": dur, "color": _hex_rgb(color), "text": text,
                 "text_color": _hex_rgb(tc) if tc else None, "tag": tag}
                for dur, color, text, tc, _z, _f, tag, _s in fx["shots"]
            ],
        })
    images = sorted(
        ({"path": f"fixtures/images/{p.name}",
          "w": int(p.stem.rsplit("_", 1)[-1].split("x")[0]),
          "h": int(p.stem.rsplit("_", 1)[-1].split("x")[1])}
         for p in (FIXTURES / "images").glob("*.png")),
        key=lambda d: d["path"],
    )
    audio = [{"path": f"fixtures/audio/{name}", "bpm": bpm, "duration": dur}
             for name, bpm, dur in BEAT_TRACKS]
    TRUTH_PATH.write_text(json.dumps(
        {"videos": videos, "images": images, "audio": audio},
        ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"truth.json → {TRUTH_PATH}")


def verify() -> None:
    print("生成完成，ffprobe 校验：")
    for video in json.loads(TRUTH_PATH.read_text(encoding="utf-8"))["videos"]:
        path = MATERIALS / video["path"]
        probe = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries",
             "format=duration:stream=codec_type,width,height",
             "-of", "json", str(path)],
            capture_output=True, text=True,
        )
        info = json.loads(probe.stdout)
        streams = {(s.get("codec_type"), s.get("width"), s.get("height"))
                   for s in info.get("streams", [])}
        print(f"  {video['path']:<58} dur={float(info['format']['duration']):.2f}s "
              f"streams={sorted(str(s) for s in streams)}")
    for item in json.loads(TRUTH_PATH.read_text(encoding="utf-8"))["audio"]:
        path = MATERIALS / item["path"]
        probe = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "csv=p=0", str(path)], capture_output=True, text=True)
        print(f"  {item['path']:<58} dur={float(probe.stdout.strip()):.2f}s")


def main() -> None:
    for unit in STYLE_UNITS:
        build_unit_video(unit)
    for fixture in FIXTURE_VIDEOS:
        build_fixture_video(fixture)
    build_audio_fixtures()
    build_image_fixtures()
    emit_truth()
    verify()


if __name__ == "__main__":
    sys.exit(main())
