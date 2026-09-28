r"""test-materials 自动化测试入口（agent 友好）。

六个套件，两种运行环境：
- local 套件（media / quality / adreplica / beats）：不需要后端。
  推荐在 API 虚拟环境里跑以覆盖全部四个：
      cd apps/api && uv run python ../../test-materials/tools/run_tests.py
  裸 python 也能跑 media，其余套件会显式 SKIP 并给出提示。
- api 套件（api-replica / api-scene3d）：需要后端（部分用例还需 LLM key）。
  先启动：cd apps/api && uv run python start_backend.py
      python tools/run_tests.py --suite api-replica,api-scene3d

套件说明：
  media      规格（时长/分辨率/音轨）——断言依据 tools/../truth.json
  quality    内容质量（镜头颜色、切点准确、文字可读像素、音频电平）
  adreplica  .adreplica 解析器正反例 + 往返锁定
  beats      节拍分析器真值（含 BPM 边界与异常轨）
  api-replica / api-scene3d   端到端 API 用例

常用开关：
  --list                     列出全部用例 id 与标题
  --suite media,quality      选择套件（默认 local 四件套）
  --only RT-01,S3-PANO       只跑匹配 id（子串匹配）
  --skip RT-02               排除用例
  --full-matrix              teardown 全风格矩阵（默认只跑 4 条代表性素材）
  --base-url URL             后端地址（默认 http://127.0.0.1:8000）
  --link-url URL             提供后跑 ingest-link 用例（默认 SKIP）
  --strict                   SKIP 也按失败计（退出码 2）

结果：results/run-<时间戳>/report.json + summary.md；控制台打印每条用例结果。
退出码：0=无 FAIL；1=有 FAIL；2=--strict 且有 SKIP。
素材与断言真值唯一来源：test-materials/truth.json（由 build_materials.py 生成）。
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import time
import traceback
import urllib.error
import urllib.parse
import urllib.request
import uuid
from datetime import datetime, timezone
from pathlib import Path

MATERIALS = Path(__file__).resolve().parents[1]
REPO = MATERIALS.parent
API_DIR = REPO / "apps" / "api"
RESULTS = MATERIALS / "results"
UNITS = MATERIALS / "units"
FIXTURES = MATERIALS / "fixtures"
TEXT = MATERIALS / "text"
TRUTH_PATH = MATERIALS / "truth.json"

PASS, FAIL, SKIP = "PASS", "FAIL", "SKIP"

# 这些后端错误归类为环境/配置未就绪（SKIP），不是产品缺陷（FAIL）
ENV_SKIP_MARKERS = (
    "llm", "api key", "apikey", "provider", "credential",
    "model_default_not_configured", "not configured",
)


# ---------------------------------------------------------------- 基础设施

def _run(command: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(command, capture_output=True, text=True)


def ffprobe(path: Path) -> dict:
    done = _run([
        "ffprobe", "-v", "error", "-show_entries",
        "format=duration:stream=codec_type,width,height",
        "-of", "json", str(path),
    ])
    if done.returncode != 0:
        raise RuntimeError(done.stderr[-300:])
    return json.loads(done.stdout)


def _load_truth() -> dict:
    if not TRUTH_PATH.exists():
        raise FileNotFoundError(
            f"truth.json 缺失：先运行 python tools/build_materials.py 生成素材与真值")
    return json.loads(TRUTH_PATH.read_text(encoding="utf-8"))


# ---- 视频像素级探针（quality 套件用；全部纯 ffmpeg，无第三方依赖） ----

def probe_mean_rgb(path: Path, t: float) -> tuple[int, int, int]:
    """t 时刻帧的平均颜色：缩到 64x36 取平均。"""
    done = subprocess.run(
        ["ffmpeg", "-v", "error", "-ss", f"{t:.3f}", "-i", str(path),
         "-frames:v", "1", "-vf", "scale=64:36", "-f", "rawvideo",
         "-pix_fmt", "rgb24", "-"],
        capture_output=True)
    if done.returncode != 0 or not done.stdout:
        raise RuntimeError(f"probe_mean_rgb failed: {done.stderr[-200:]}")
    data = done.stdout
    n = len(data) // 3
    r = sum(data[0::3]) / n
    g = sum(data[1::3]) / n
    b = sum(data[2::3]) / n
    return round(r), round(g), round(b)


def probe_gray(path: Path, t: float) -> bytes:
    """t 时刻帧的灰度原始数据（高度压到 480 以内，保持足够文字分辨率）。"""
    done = subprocess.run(
        ["ffmpeg", "-v", "error", "-ss", f"{t:.3f}", "-i", str(path),
         "-frames:v", "1", "-vf", "scale=-2:'min(480,ih)'", "-f", "rawvideo",
         "-pix_fmt", "gray", "-"],
        capture_output=True)
    if done.returncode != 0 or not done.stdout:
        raise RuntimeError(f"probe_gray failed: {done.stderr[-200:]}")
    return done.stdout


def probe_mad_rgb(path: Path, t1: float, t2: float) -> float:
    """两个时刻帧的平均绝对差（RGB，0-255）。真实切点应显著高于镜头内抖动。"""
    def frame(t: float) -> bytes:
        done = subprocess.run(
            ["ffmpeg", "-v", "error", "-ss", f"{t:.3f}", "-i", str(path),
             "-frames:v", "1", "-vf", "scale=64:36", "-f", "rawvideo",
             "-pix_fmt", "rgb24", "-"],
            capture_output=True)
        if done.returncode != 0 or not done.stdout:
            raise RuntimeError(f"probe_mad frame failed: {done.stderr[-200:]}")
        return done.stdout
    a, b = frame(t1), frame(t2)
    n = min(len(a), len(b)) // 3
    total = 0
    for i in range(n):
        total += abs(a[i * 3] - b[i * 3]) + abs(a[i * 3 + 1] - b[i * 3 + 1]) \
            + abs(a[i * 3 + 2] - b[i * 3 + 2])
    return total / (n * 3)


def audio_rms_db(path: Path) -> float | None:
    """首条音轨的 Overall RMS（dBFS）；无音轨返回 None。"""
    done = subprocess.run(
        ["ffmpeg", "-v", "info", "-i", str(path), "-map", "0:a:0",
         "-af", "astats=metadata=0", "-f", "null", "-"],
        capture_output=True, text=True)
    if done.returncode != 0:
        return None
    values = re.findall(r"RMS level dB:\s*(-?[\d.]+|-?inf)", done.stderr)
    if not values:
        return None
    raw = values[-1]
    return -99.0 if "inf" in raw else float(raw)


def _luma(rgb: list[int]) -> float:
    return 0.299 * rgb[0] + 0.587 * rgb[1] + 0.114 * rgb[2]


def _dist(c1, c2) -> float:
    return (sum((a - b) ** 2 for a, b in zip(c1, c2))) ** 0.5


def _multipart(fields: dict[str, str], files: list[tuple[str, str, bytes, str]]):
    boundary = "----zdmat" + uuid.uuid4().hex
    chunks: list[bytes] = []
    for name, value in fields.items():
        chunks.append(
            f"--{boundary}\r\n"
            f'Content-Disposition: form-data; name="{name}"\r\n\r\n{value}\r\n'.encode()
        )
    for field, filename, content, ctype in files:
        chunks.append(
            f"--{boundary}\r\n"
            f'Content-Disposition: form-data; name="{field}"; filename="{filename}"\r\n'
            f"Content-Type: {ctype}\r\n\r\n".encode()
        )
        chunks.append(content + b"\r\n")
    chunks.append(f"--{boundary}--\r\n".encode())
    return b"".join(chunks), f"multipart/form-data; boundary={boundary}"


def http_full(method: str, url: str, *, json_body=None, fields=None,
              files=None, headers=None, timeout=30):
    """返回 (status, body_dict_or_text, response_headers)。HTTPError 也返回状态码。"""
    data = None
    send_headers = dict(headers or {})
    if files is not None:
        data, ctype = _multipart(fields or {}, files)
        send_headers["Content-Type"] = ctype
    elif fields is not None:
        data = urllib.parse.urlencode(fields).encode()
        send_headers["Content-Type"] = "application/x-www-form-urlencoded"
    elif json_body is not None:
        data = json.dumps(json_body, ensure_ascii=False).encode("utf-8")
        send_headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=send_headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8", "replace")
            # Starlette 回传的响应头是小写键（etag/if-match），统一小写化便于查找
            resp_headers = {k.lower(): v for k, v in resp.headers.items()}
            try:
                return resp.status, json.loads(raw), resp_headers
            except json.JSONDecodeError:
                return resp.status, {"_raw": raw}, resp_headers
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", "replace")
        exc_headers = {k.lower(): v for k, v in (exc.headers or {}).items()}
        try:
            return exc.code, json.loads(raw), exc_headers
        except json.JSONDecodeError:
            return exc.code, {"_raw": raw}, exc_headers


def api_alive(base_url: str) -> bool:
    try:
        status, _, _ = http_full("GET", base_url + "/docs", timeout=5)
        return status == 200
    except Exception:
        return False


def error_texts(status: int, body) -> str:
    parts: list[str] = [f"HTTP {status}"]
    if isinstance(body, dict):
        for key in ("error_type", "error", "detail", "message"):
            value = body.get(key)
            if value:
                parts.append(f"{key}={value}")
        if body.get("_raw"):
            parts.append(str(body["_raw"])[:200])
    return " | ".join(parts)


def looks_env_related(body) -> bool:
    """错误体里出现 LLM/配置类标记 → 环境未就绪（SKIP），否则视为缺陷（FAIL）。"""
    text = json.dumps(body, ensure_ascii=False).lower() if isinstance(body, dict) else str(body).lower()
    return any(marker in text for marker in ENV_SKIP_MARKERS)


def brief_text(unit: str, filename: str = "brief.txt") -> str:
    """单元 brief 文件里取「粘贴以下内容」之后的正文。"""
    raw = (UNITS / unit / filename).read_text(encoding="utf-8")
    for marker in ("粘贴以下内容", "paste the text below"):
        if marker in raw:
            return raw.split(marker, 1)[1].strip()
    return raw.strip()


# ---------------------------------------------------------------- 用例模型

class Case:
    def __init__(self, cid: str, suite: str, title: str, fn, note: str = ""):
        self.id, self.suite, self.title, self.fn, self.note = cid, suite, title, fn, note

    def run(self) -> dict:
        started = time.time()
        try:
            status, detail = self.fn()
        except Exception as exc:  # 用例内未捕获异常按 FAIL 记录，附调用栈尾
            status, detail = FAIL, {
                "error": f"{type(exc).__name__}: {exc}",
                "traceback_tail": traceback.format_exc()[-500:],
            }
        return {
            "id": self.id, "suite": self.suite, "title": self.title,
            "status": status, "seconds": round(time.time() - started, 2),
            "detail": detail,
        }


def expect(cond: bool, actual, want: str) -> tuple[str, dict]:
    return (PASS, {"actual": actual}) if cond else (FAIL, {"actual": actual, "expected": want})


# ---------------------------------------------------------------- suite: media

def build_media_cases(truth: dict) -> list[Case]:
    cases = []
    for i, video in enumerate(truth["videos"], 1):
        def fn(video=video):
            path = MATERIALS / video["path"]
            info = ffprobe(path)
            dur = float(info["format"]["duration"])
            vs = next((s for s in info["streams"] if s.get("codec_type") == "video"), {})
            has_audio = any(s.get("codec_type") == "audio" for s in info["streams"])
            ok = (abs(dur - video["duration"]) <= 0.3
                  and vs.get("width") == video["w"] and vs.get("height") == video["h"]
                  and has_audio == video["audio"])
            actual = {"duration": dur, "size": f'{vs.get("width")}x{vs.get("height")}',
                      "audio": has_audio}
            want = (f"dur={video['duration']}±0.3 {video['w']}x{video['h']} "
                    f"audio={video['audio']}")
            return expect(ok, actual, want)
        cases.append(Case(f"MD-{i:02d}", "media", f"视频规格 {video['path']}", fn))
    for i, image in enumerate(truth["images"], 1):
        def fn(image=image):
            path = MATERIALS / image["path"]
            done = _run(["ffprobe", "-v", "error", "-show_entries",
                         "stream=width,height", "-of", "csv=p=0", str(path)])
            w, h = (int(x) for x in done.stdout.strip().split(",")[:2])
            return expect((w, h) == (image["w"], image["h"]), f"{w}x{h}",
                          f'{image["w"]}x{image["h"]}')
        cases.append(Case(f"MD-I{i:02d}", "media", f"图片尺寸 {image['path']}", fn))
    return cases


# ---------------------------------------------------------------- suite: quality

# 质量门阈值（素材为纯色底+大字设计，以下裕量都留得很宽）
COLOR_TOL = 90.0        # 镜头中点平均色与设计底色的欧氏距离上限
TEXT_MIN_PIXELS = 150   # 文字极性像素数下限（480p 灰度帧）
CUT_MIN_MAD = 8.0       # 跨切点帧差下限（RGB MAD）
RMS_RANGE = (-42.0, -3.0)  # 音频 Overall RMS（dBFS）合理区间


def build_quality_cases(truth: dict) -> list[Case]:
    cases = []
    for i, video in enumerate(truth["videos"], 1):
        cases.append(Case(f"QC-{i:02d}", "quality", f"内容质量 {video['path']}",
                          quality_case(video)))
    return cases


def quality_case(video: dict):
    def fn():
        path = MATERIALS / video["path"]
        problems: list[str] = []
        detail: dict = {"checks": []}

        shots = video.get("shots")
        starts: list[float] = []
        if shots:
            t = 0.0
            for shot in shots:
                starts.append(round(t, 3))
                t += shot["dur"]

        # 1) 每镜中点：平均色 ≈ 设计底色；文字极性像素存在
        if shots:
            for idx, (shot, start) in enumerate(zip(shots, starts), 1):
                mid = start + shot["dur"] / 2
                entry = {"shot": idx, "mid": mid}
                mean = probe_mean_rgb(path, mid)
                dist = _dist(mean, shot["color"])
                entry["color"] = {"mean": list(mean), "design": shot["color"], "dist": round(dist, 1)}
                if dist > COLOR_TOL:
                    problems.append(f"镜{idx} 中点平均色偏离设计（dist={dist:.0f}>{COLOR_TOL}）")
                if shot.get("text") and shot.get("text_color"):
                    luma = _luma(shot["text_color"])
                    gray = probe_gray(path, mid)
                    if luma >= 128:
                        thr, count = luma - 30, sum(1 for b in gray if b >= luma - 30)
                        entry["text"] = {"polarity": "light", "thr": round(thr), "pixels": count}
                    else:
                        thr, count = luma + 30, sum(1 for b in gray if b <= luma + 30)
                        entry["text"] = {"polarity": "dark", "thr": round(thr), "pixels": count}
                    if count < TEXT_MIN_PIXELS:
                        problems.append(
                            f"镜{idx} 文字可读像素不足（{count}<{TEXT_MIN_PIXELS}，"
                            f"thr={entry['text']['thr']}）")
                detail["checks"].append(entry)

            # 2) 切点准确：跨切点帧差显著高于镜头内抖动
            for idx in range(1, len(shots)):
                boundary = starts[idx]
                cross = probe_mad_rgb(path, boundary - 0.25, boundary + 0.25)
                mid_prev = starts[idx - 1] + shots[idx - 1]["dur"] / 2
                base = probe_mad_rgb(path, mid_prev - 0.25, mid_prev + 0.25)
                need = max(CUT_MIN_MAD, base * 3)
                detail["checks"].append({"cut_at": boundary, "cross_mad": round(cross, 2),
                                         "baseline_mad": round(base, 2)})
                if cross <= need:
                    problems.append(
                        f"切点 {boundary}s 帧差不足（cross={cross:.1f} ≤ need={need:.1f}）")
        elif video.get("text_spot"):
            spot = video["text_spot"]
            gray = probe_gray(path, spot["t"])
            luma = _luma(spot["text_color"])
            count = sum(1 for b in gray if b >= luma - 30)
            detail["checks"].append({"text_spot": spot["t"], "pixels": count})
            if count < TEXT_MIN_PIXELS:
                problems.append(f"横移片文字探针像素不足（{count}<{TEXT_MIN_PIXELS}）")

        # 3) 音频电平合理（非静音、无削波）
        if video["audio"]:
            rms = audio_rms_db(path)
            detail["checks"].append({"rms_dbfs": rms})
            if rms is None:
                problems.append("音轨存在但 astats 未产出 RMS")
            elif not RMS_RANGE[0] <= rms <= RMS_RANGE[1]:
                problems.append(f"音频 RMS 超出合理区间 {RMS_RANGE}：{rms:.1f} dBFS")

        if problems:
            return FAIL, {"problems": problems, "detail": detail}
        return PASS, {"actual": {"checks": len(detail["checks"]), "note": "颜色/文字/切点/电平全过"}}
    return fn


# ---------------------------------------------------------------- suite: adreplica

def _load_adreplica_module():
    sys.path.insert(0, str(API_DIR))
    from app.services.replica import adreplica  # noqa: PLC0415
    return adreplica


def build_adreplica_cases() -> list[Case]:
    cases: list[Case] = []
    valid = [
        ("valid_luxury_16x9.adreplica", 3),      # product/style/scene applied
        ("valid_textonly_1x1.adreplica", 0),
        ("valid_dialogue_cjk_anchors.adreplica", 2),
    ]
    invalid = [
        ("invalid_hypit_host_slot.adreplica", "Unknown slot kind"),
        ("invalid_ghost_anchor.adreplica", "references unknown event"),
        ("invalid_unknown_event.adreplica", "Unknown event element"),
        ("invalid_version_2.adreplica", "Unsupported"),
    ]

    def import_ok():
        ad = _load_adreplica_module()
        results = {}
        for name, want_applied in valid:
            bp = ad.blueprint_from_adreplica((TEXT / "adreplica" / name).read_text(encoding="utf-8"))
            applied = sum(1 for s in bp.slots if s.replace_with)
            results[name] = {"slots": len(bp.slots), "beats": len(bp.beats),
                             "applied": applied}
            if len(bp.slots) < 5 or len(bp.beats) < 4 or applied != want_applied:
                return FAIL, {"actual": results, "expected": f"slots>=5 beats>=4 applied={want_applied}"}
        return PASS, {"actual": results}

    def roundtrip():
        ad = _load_adreplica_module()
        name = "valid_dialogue_cjk_anchors.adreplica"
        text1 = (TEXT / "adreplica" / name).read_text(encoding="utf-8")
        bp1 = ad.blueprint_from_adreplica(text1)
        text2 = ad.adreplica_from_blueprint(bp1)
        bp2 = ad.blueprint_from_adreplica(text2)
        ok = bp1 == bp2 and ad.adreplica_from_blueprint(bp2) == text2
        return expect(ok, "parse→export→parse 幂等", "往返锁定（文档=唯一真相源）")

    def import_reject(name: str, want_msg: str):
        def fn():
            ad = _load_adreplica_module()
            try:
                ad.blueprint_from_adreplica((TEXT / "adreplica" / name).read_text(encoding="utf-8"))
                return FAIL, {"actual": "被接受", "expected": f"422 且报错含 {want_msg!r}"}
            except ad.AdReplicaParseError as exc:
                return expect(want_msg.lower() in str(exc).lower(), str(exc)[:120],
                              f"报错含 {want_msg!r}")
        return fn

    def guarded(fn):
        def wrapper():
            try:
                _load_adreplica_module()
            except Exception as exc:
                return SKIP, {"reason": f"无法导入解析器（需 apps/api 依赖）：{exc}",
                              "hint": "cd apps/api && uv run python ../../test-materials/tools/run_tests.py"}
            return fn()
        return wrapper

    cases.append(Case("AD-01", "adreplica", "3 个正例导入并落槽正确", guarded(import_ok)))
    cases.append(Case("AD-02", "adreplica", "导出→再解析往返锁定", guarded(roundtrip)))
    for i, (name, msg) in enumerate(invalid, 3):
        cases.append(Case(f"AD-{i:02d}", "adreplica", f"反例被拒 {name}",
                          guarded(import_reject(name, msg))))
    return cases


# ---------------------------------------------------------------- suite: beats

BEAT_WINDOWS = {
    "beat_120bpm_20s.wav": [(117, 123)],
    "beat_90bpm_20s.wav": [(87, 94)],
    "beat_140bpm_accent_30s.wav": [(136, 143)],
    "beat_60bpm_20s.wav": [(57, 63)],
    "beat_170bpm_20s.wav": [(163, 177), (80, 91)],   # 高速档可能判半频（实测 84.7）
}


def build_beat_cases(truth: dict) -> list[Case]:
    cases: list[Case] = []

    def bpm_case(name, windows):
        def fn():
            from app.services.timeline_beat_analysis import BeatAnalyzer
            result = BeatAnalyzer("ffmpeg").analyze(str(FIXTURES / "audio" / name))
            ok = any(lo <= result.bpm <= hi for lo, hi in windows)
            return expect(ok, f"bpm={result.bpm} conf={result.confidence} beats={len(result.beats)}",
                          f"bpm 在 {windows} 之一")
        return fn

    def error_case(name, want_msg):
        def fn():
            from app.services.timeline_beat_analysis import BeatAnalyzer
            try:
                result = BeatAnalyzer("ffmpeg").analyze(str(FIXTURES / "audio" / name))
                return FAIL, {"actual": f"竟然出结果 bpm={result.bpm}",
                              "expected": f"报错含 {want_msg!r}"}
            except Exception as exc:
                return expect(want_msg.lower() in str(exc).lower(), str(exc)[:120],
                              f"报错含 {want_msg!r}")
        return fn

    def mixed_case():
        def fn():
            from app.services.timeline_beat_analysis import BeatAnalyzer
            result = BeatAnalyzer("ffmpeg").analyze(
                str(FIXTURES / "audio" / "beat_mixed_120to150_20s.wav"))
            # 变速轨：不崩溃，且不得把两段真值（120/150）当整体真值
            return expect(result.bpm < 100, f"bpm={result.bpm}",
                          "不崩溃且 bpm<100（不得报 120/150；实测 74.9 半频谐波）")
        return fn

    def guarded(fn):
        def wrapper():
            try:
                from app.services.timeline_beat_analysis import BeatAnalyzer  # noqa: F401
            except Exception as exc:
                return SKIP, {"reason": f"无法导入 BeatAnalyzer（需 apps/api 依赖）：{exc}",
                              "hint": "cd apps/api && uv run python ../../test-materials/tools/run_tests.py"}
            return fn()
        return wrapper

    for i, (name, windows) in enumerate(BEAT_WINDOWS.items(), 1):
        cases.append(Case(f"BT-{i:02d}", "beats", f"节拍检测真值 {name}",
                          guarded(bpm_case(name, windows))))
    cases.append(Case("BT-06", "beats", "变速轨不崩溃且不误报真值", guarded(mixed_case())))
    cases.append(Case("BT-07", "beats", "过短轨报 too_short（<2s 下限）",
                      guarded(error_case("beat_tooshort_1s.wav", "2 seconds"))))
    cases.append(Case("BT-08", "beats", "静音轨报无稳定节拍",
                      guarded(error_case("beat_silent_10s.wav", "steady beat"))))
    return cases


# ---------------------------------------------------------------- suite: api-replica

# teardown 用例 →（素材 id, brief 单元文件，fast 子集, 断言）
TEARDOWN_SPECS = [
    ("RT-01", "fastcut", "replica-fastcut", "brief.txt", True,
     {"shots": (5, 7), "avg": (2.0, 3.2), "text_any": ["BUY NOW"]}),
    ("RT-02", "luxury", "replica-luxury", "brief.txt", False,
     {"shots": (3, 5), "avg": (6.0, 9.0), "text_any": ["TIMELESS"]}),
    ("RT-03", "dialogue", "replica-dialogue", "brief.txt", False,
     {"shots": (4, 6), "avg": (3.2, 4.8)}),
    ("RT-04", "textonly", "replica-textonly", "brief.txt", True,
     {"shots": (3, 5), "avg": (2.0, 3.2), "text_any": ["轮到你了"]}),
    ("RT-05", "action", "replica-action", "brief.txt", False,
     {"shots": (6, 9), "avg": (1.0, 2.0)}),
    ("RT-06", "beatsync", "replica-beatsync", "brief.txt", True,
     {"shots": (12, 20), "avg": (0.6, 1.6)}),
    ("RT-07", "compare", "replica-compare", "brief.txt", False,
     {"shots": (3, 5), "avg": (3.0, 5.0), "text_any": ["BEFORE", "AFTER", "VERDICT"]}),
    ("RT-08", "vlogtour", "replica-vlogtour", "brief.txt", False,
     {"shots": (5, 7), "avg": (2.2, 3.8)}),
    ("RT-09", "tutorial", "replica-tutorial", "brief.txt", False,
     {"shots": (3, 5), "text_any": ["STEP"]}),
    ("RT-10", "silent", None, None, False, {}),
    ("RT-11", "edge4", None, None, False, {}),
]

FAST_IDS = {spec[0] for spec in TEARDOWN_SPECS if spec[4]}


def teardown_case(base_url: str, video_path: str, brief: tuple[str, str] | None,
                  checks: dict):
    def fn():
        fields = {"num_frames": "8"}
        if brief:
            fields["user_description"] = brief_text(brief[0], brief[1])
        path = MATERIALS / video_path
        status, body, _ = http_full(
            "POST", base_url + "/api/v1/replica/teardown", fields=fields,
            files=[("file", path.name, path.read_bytes(), "video/mp4")],
            timeout=420,
        )
        if status != 200:
            detail = {"error": error_texts(status, body)}
            if looks_env_related(body):
                return SKIP, detail
            return FAIL, detail
        report = body.get("report", {})
        shots = report.get("shots", [])
        texts = " ".join(
            " ".join(str(s.get(k, "")) for k in ("on_screen_text", "subject_action", "note"))
            for s in shots
        )
        actual = {"shots": len(shots),
                  "avg_shot": report.get("rhythm", {}).get("avg_shot_seconds"),
                  "beats": len(report.get("beats", [])),
                  "reading_len": len(report.get("whole_piece_reading", "")),
                  "texts": texts[:160]}
        if not shots:
            return FAIL, {"actual": actual, "expected": "报告含镜头表"}
        if "avg" in checks and not (checks["avg"][0] <= (actual["avg_shot"] or 0) <= checks["avg"][1]):
            return FAIL, {"actual": actual, "expected": f"avg_shot 在 {checks['avg']}"}
        if "shots" in checks and not checks["shots"][0] <= len(shots) <= checks["shots"][1]:
            return FAIL, {"actual": actual, "expected": f"镜头数在 {checks['shots']}"}
        if "text_any" in checks and not any(t.lower() in texts.lower() for t in checks["text_any"]):
            return FAIL, {"actual": actual, "expected": f"屏上文字含 {'/'.join(checks['text_any'])}"}
        return PASS, {"actual": actual}
    return fn


def overlong_case(base_url: str):
    def fn():
        path = MATERIALS / "fixtures/videos/rep_overlong_16x9_61s.mp4"
        status, body, _ = http_full(
            "POST", base_url + "/api/v1/replica/teardown", fields={"num_frames": "8"},
            files=[("file", path.name, path.read_bytes(), "video/mp4")],
            timeout=60,
        )
        ok = status == 400 and bool(body.get("error_type") or body.get("detail"))
        return expect(ok, error_texts(status, body)[:160], "HTTP 400 + 结构化 error_type（>60s 拒绝）")
    return fn


def _import_blueprint_from_file(base_url: str, name: str) -> dict:
    text = (TEXT / "adreplica" / name).read_text(encoding="utf-8")
    status, body, _ = http_full("POST", base_url + "/api/v1/replica/blueprint/import",
                                json_body={"adreplica": text}, timeout=60)
    if status != 200:
        raise RuntimeError(f"import {name} 失败：{error_texts(status, body)[:200]}")
    return body["blueprint"]


def api_import_case(base_url: str):
    def fn():
        out = {}
        for name, want_applied in [("valid_luxury_16x9.adreplica", 3),
                                   ("valid_textonly_1x1.adreplica", 0),
                                   ("valid_dialogue_cjk_anchors.adreplica", 2)]:
            bp = _import_blueprint_from_file(base_url, name)
            applied = sum(1 for s in bp.get("slots", []) if s.get("replace_with"))
            out[name] = {"slots": len(bp.get("slots", [])), "applied": applied}
            if len(bp.get("slots", [])) < 5 or applied != want_applied:
                return FAIL, {"actual": out, "expected": f"slots>=5 applied={want_applied}"}
        return PASS, {"actual": out}
    return fn


def api_variants_case(base_url: str):
    def fn():
        bp = _import_blueprint_from_file(base_url, "valid_luxury_16x9.adreplica")
        payload = {"blueprint": bp, "n": 3, "mix_size": 1}
        status1, body1, _ = http_full("POST", base_url + "/api/v1/replica/blueprint/style-variants",
                                      json_body=payload, timeout=60)
        status2, body2, _ = http_full("POST", base_url + "/api/v1/replica/blueprint/style-variants",
                                      json_body=payload, timeout=60)
        if status1 != 200 or status2 != 200:
            return SKIP if looks_env_related(body1) else FAIL, {"error": error_texts(status1, body1)[:200]}
        v1, v2 = body1.get("variants", []), body2.get("variants", [])
        if not v1:
            return FAIL, {"actual": "variants 为空", "expected": "至少 1 个候选"}
        deterministic = json.dumps(v1, sort_keys=True) == json.dumps(v2, sort_keys=True)
        if not deterministic:
            return FAIL, {"actual": "两次调用结果不同", "expected": "同参确定性（seed 可复现）"}
        return PASS, {"actual": {"count": len(v1), "first": str(v1[0])[:120]}}
    return fn


def api_direct_execute_case(base_url: str):
    """纯字幕蓝图直出门：镜头步骤应归入零模型费；台词 TTS 属必须生成环节
    （feasible=false 是对额度/依赖的诚实判定），断言只锁「分类正确 + 无阻塞」。"""
    def fn():
        bp = _import_blueprint_from_file(base_url, "valid_textonly_1x1.adreplica")
        status, body, _ = http_full("POST", base_url + "/api/v1/replica/blueprint/direct-execute-plan",
                                    json_body={"blueprint": bp}, timeout=60)
        if status != 200:
            detail = {"error": error_texts(status, body)[:200]}
            return (SKIP if looks_env_related(body) else FAIL), detail
        actual = {"feasible": body.get("feasible"),
                  "zero_model_steps": len(body.get("zero_model_steps", [])),
                  "generation_steps": [str(s.get("kind", s.get("type", s)))[:40]
                                       for s in body.get("generation_steps", [])],
                  "blockers": body.get("blockers", [])}
        ok = (not body.get("blockers")
              and len(body.get("zero_model_steps", [])) >= 3)
        return expect(ok, actual,
                      "blockers 为空且 >=3 个零模型费步骤（4 个纯文字镜头的剪辑分类）；"
                      "台词 TTS 计入 generation_steps 属正确行为")
    return fn


def api_chain_case(base_url: str):
    """报告→蓝图→导出→手改→导入 全链（1 次 teardown，约 1-3 分钟 LLM）。"""
    def fn():
        status, td, _ = http_full(
            "POST", base_url + "/api/v1/replica/teardown",
            fields={"user_description": brief_text("replica-fastcut"), "num_frames": "8"},
            files=[("file", "rep_fastcut_9x16_15s.mp4",
                    (UNITS / "replica-fastcut" / "rep_fastcut_9x16_15s.mp4").read_bytes(),
                    "video/mp4")],
            timeout=420,
        )
        if status != 200:
            detail = {"error": error_texts(status, td)[:200]}
            return (SKIP if looks_env_related(td) else FAIL), detail
        status, bp_body, _ = http_full(
            "POST", base_url + "/api/v1/replica/blueprint",
            json_body={"report": td["report"], "replica_goal": "换商品不换结构"}, timeout=60)
        if status != 200:
            return FAIL, {"error": error_texts(status, bp_body)[:200]}
        blueprint = bp_body["blueprint"]
        status, ex, _ = http_full("POST", base_url + "/api/v1/replica/blueprint/export",
                                  json_body={"blueprint": blueprint}, timeout=60)
        if status != 200 or "<advideo" not in ex.get("adreplica", ""):
            return FAIL, {"error": error_texts(status, ex)[:200]}
        status, im, _ = http_full("POST", base_url + "/api/v1/replica/blueprint/import",
                                  json_body={"adreplica": ex["adreplica"]}, timeout=60)
        ok = (status == 200
              and im["blueprint"].get("format_name") == blueprint.get("format_name")
              and len(im["blueprint"].get("slots", [])) == len(blueprint.get("slots", [])))
        actual = {"format": im.get("blueprint", {}).get("format_name"),
                  "slots": len(im.get("blueprint", {}).get("slots", [])),
                  "filename": ex.get("filename", "")}
        return expect(ok, actual, "导出文本含 <advideo，重编译后 format/slots 一致")
    return fn


def api_instantiate_case(base_url: str):
    def fn():
        blueprint = _import_blueprint_from_file(base_url, "valid_luxury_16x9.adreplica")
        tag = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
        status, proj, _ = http_full(
            "POST", base_url + "/api/v2/projects",
            json_body={"name": f"test-materials-{tag}", "description": "自动化实例化用例"},
            headers={"Idempotency-Key": f"tm-{tag}-{uuid.uuid4().hex[:6]}"}, timeout=60)
        if status not in (200, 201):
            detail = {"error": error_texts(status, proj)[:200]}
            return (SKIP if looks_env_related(proj) else FAIL), detail
        workflow_id = (proj.get("project") or proj)["workflow_id"]
        status, wf, headers = http_full("GET", base_url + f"/api/v2/workflows/{workflow_id}", timeout=30)
        etag = headers.get("etag", headers.get("ETag", ""))
        status, node_body, _ = http_full(
            "POST", base_url + f"/api/v2/workflows/{workflow_id}/nodes",
            json_body={"node_type": "replica", "creative_role": "replica_blueprint",
                       "role_contract_version": "ad-media-role-v2", "title": "test-materials 蓝图",
                       "summary_prompt": "自动化用例", "generation_prompt": None,
                       "structured_content": blueprint, "model_selection_mode": "default",
                       "model_ref": None, "parameters": {},
                       "position": {"x": 200.0, "y": 120.0}, "source_asset_id": None},
            headers={"If-Match": etag}, timeout=60)
        if status not in (200, 201):
            conflict = isinstance(node_body, dict) and \
                "canvas_node_conflict" in json.dumps(node_body)
            if conflict:
                return FAIL, {
                    "error": error_texts(status, node_body)[:200],
                    "expected": "DB CHECK 约束 ck_agent_canvas_nodes_type 不含 'replica'"
                                "（最新迁移 20260917_01 只放宽到 voice-cast），replica 节点"
                                "INSERT 违反约束被包装成 503——产品缺口，与 v0.2 handover"
                                "『replica 迁移未入库』一致；需补 alembic 迁移",
                }
            detail = {"error": error_texts(status, node_body)[:240]}
            return (SKIP if looks_env_related(node_body) else FAIL), detail
        replica_node_id = (node_body.get("node") or {}).get("node_id", "")
        status, inst, _ = http_full(
            "POST", base_url + "/api/v1/replica/instantiate",
            json_body={"workflow_id": workflow_id, "replica_node_id": replica_node_id,
                       "slot_updates": {"product": "sample_product.png"}}, timeout=60)
        if status != 200:
            detail = {"error": error_texts(status, inst)[:200]}
            return (SKIP if looks_env_related(inst) else FAIL), detail
        script_node_id = inst.get("script_node_id", "")
        status, wf, _ = http_full("GET", base_url + f"/api/v2/workflows/{workflow_id}", timeout=30)
        nodes = {n["node_id"] for n in wf.get("nodes", [])}
        binding_ok = any(
            b.get("source", {}).get("source_node_id") == replica_node_id
            and b.get("target_node_id") == script_node_id
            for b in wf.get("bindings", []))
        ok = script_node_id in nodes and binding_ok and str(inst.get("binding_id", "")).startswith("binding_")
        return expect(ok, {"script_node_in_nodes": script_node_id in nodes,
                           "binding_ok": binding_ok,
                           "binding_id": inst.get("binding_id", "")},
                      "script 节点存在 + replica→script 绑定存在 + binding_id 前缀正确")
    return fn


def api_link_case(base_url: str, url: str):
    def fn():
        status, body, _ = http_full("POST", base_url + "/api/v1/replica/ingest-link",
                                    json_body={"url": url}, timeout=300)
        if status != 200:
            detail = {"error": error_texts(status, body)[:200]}
            if looks_env_related(body) or body.get("error_type") in (
                    "ytdlp_missing", "download_failed", "invalid_url"):
                detail["note"] = "链接下载降级属预期行为，记录 error_type 即可"
                return PASS, detail
            return FAIL, detail
        return expect(bool(body.get("asset_id")), {"asset_id": body.get("asset_id", "")},
                      "下载后走统一存储并返回 asset_id")
    return fn


def build_api_replica_cases(base_url: str, truth: dict, full_matrix: bool,
                            link_url: str | None) -> list[Case]:
    alive = api_alive(base_url)
    skip = {"reason": f"后端不可达：{base_url}",
            "hint": "cd apps/api && uv run python start_backend.py"}
    paths = {v["id"]: v["path"] for v in truth["videos"]}
    cases: list[Case] = [
        Case("RT-IM", "api-replica", "3 正例 .adreplica 经 API 导入", api_import_case(base_url)),
        Case("RT-DE", "api-replica", "纯字幕蓝图直出门分类正确", api_direct_execute_case(base_url)),
        Case("RT-VAR", "api-replica", "风格变体同参确定性", api_variants_case(base_url)),
        Case("RT-CHAIN", "api-replica", "报告→蓝图→导出→重编译全链（LLM×1）", api_chain_case(base_url)),
    ]
    for cid, video_id, unit, brief_file, fast, checks in TEARDOWN_SPECS:
        if not (fast or full_matrix):
            continue
        brief = (unit, brief_file) if unit and brief_file else None
        cases.append(Case(cid, "api-replica", f"teardown 拆解 {video_id}（LLM）",
                          teardown_case(base_url, paths[video_id], brief, checks)))
    cases.append(Case("RT-12", "api-replica", "61s 超长片 teardown 拒绝",
                      overlong_case(base_url)))
    cases.append(Case("RT-INST", "api-replica", "蓝图实例化：项目→节点→script+绑定",
                      api_instantiate_case(base_url)))
    if link_url:
        cases.append(Case("RT-LINK", "api-replica", f"链接下载 {url_short(link_url)}",
                          api_link_case(base_url, link_url)))
    else:
        cases.append(Case("RT-LINK", "api-replica", "链接下载（未提供 --link-url）",
                          lambda: (SKIP, {"reason": "未提供 --link-url，跳过网络下载用例"})))
    if not alive:
        for case in cases:
            case.fn = lambda skip=skip: (SKIP, dict(skip))
    return cases


def url_short(url: str) -> str:
    return url[:60] + ("…" if len(url) > 60 else "")


# ---------------------------------------------------------------- suite: api-scene3d

def s3_upload_case(base_url: str):
    def fn():
        path = UNITS / "replica-fastcut" / "rep_fastcut_9x16_15s.mp4"
        status, body, _ = http_full(
            "POST", base_url + "/api/v1/scene-3d/upload-reference",
            fields={"extract_keyframes": "true", "num_keyframes": "8"},
            files=[("file", path.name, path.read_bytes(), "video/mp4")],
            timeout=120)
        if status != 200:
            detail = {"error": error_texts(status, body)[:200]}
            return (SKIP if looks_env_related(body) else FAIL), detail
        dur = (body.get("metadata") or {}).get("duration_seconds", 0)
        return expect(bool(body.get("asset_id")) and dur > 14,
                      {"asset_id": body.get("asset_id", ""), "duration": dur},
                      "返回 asset_id 且时长>14s")
    return fn


def s3_analyze_image_case(base_url: str, images: list[str], want_pano: bool,
                          want_count: int):
    def fn():
        status, body, _ = http_full(
            "POST", base_url + "/api/v1/scene-3d/analyze-image",
            fields={"scene_name": f"tm-{images[0].split('.')[0]}", "duration_seconds": "6"},
            files=[("files", name, (FIXTURES / "images" / name).read_bytes(), "image/png")
                   for name in images],
            timeout=300)
        if status != 200:
            detail = {"error": error_texts(status, body)[:200]}
            return (SKIP if looks_env_related(body) else FAIL), detail
        pano_idx = body.get("panorama_image_indices", [])
        analyzed = body.get("analyzed_image_count", 0)
        ok = body.get("error") is None and analyzed == want_count \
            and (bool(pano_idx) if want_pano else True)
        return expect(ok, {"analyzed": analyzed, "panorama_indices": pano_idx,
                           "warnings": body.get("warnings", [])},
                      f"error=None analyzed={want_count}" + (" 全景分支触发" if want_pano else ""))
    return fn


def s3_analyze_reference_case(base_url: str):
    def fn():
        path = FIXTURES / "videos" / "s3d_refroom_16x9_8s.mp4"
        status, body, _ = http_full(
            "POST", base_url + "/api/v1/scene-3d/analyze-reference",
            fields={"num_frames": "6"},
            files=[("file", path.name, path.read_bytes(), "video/mp4")],
            timeout=360)
        if status != 200:
            detail = {"error": error_texts(status, body)[:200]}
            return (SKIP if looks_env_related(body) else FAIL), detail
        script = body.get("scene_script") or {}
        return expect(bool(script), {"scene_script_keys": list(script)[:8]},
                      "返回非空 SceneScript")
    return fn


def s3_depth_deps_case(base_url: str):
    def fn():
        status, body, _ = http_full("GET", base_url + "/api/v1/scene-3d/depth-dependencies",
                                    timeout=30)
        if status != 200:
            detail = {"error": error_texts(status, body)[:200]}
            return (SKIP if looks_env_related(body) else FAIL), detail
        all_available = body.get("all_available")
        detail = {"all_available": all_available,
                  "deps": {k: body.get(k) for k in ("opencv", "numpy", "timm", "ffmpeg")}}
        if all_available is False:
            detail["note"] = "MiDaS 依赖未装齐，深度提取手动步骤见 plans/3d-previs-plan.md §3"
            return SKIP, detail
        return PASS, detail
    return fn


def build_api_scene3d_cases(base_url: str, with_depth: bool) -> list[Case]:
    alive = api_alive(base_url)
    skip = {"reason": f"后端不可达：{base_url}",
            "hint": "cd apps/api && uv run python start_backend.py"}
    cases = [
        Case("S3-UP", "api-scene3d", "上传参考视频（共用入口，无 LLM）", s3_upload_case(base_url)),
        Case("S3-DEPS", "api-scene3d", "深度依赖探测（MiDaS/timm）", s3_depth_deps_case(base_url)),
        Case("S3-IMG", "api-scene3d", "单图场景分析 room（LLM）",
             s3_analyze_image_case(base_url, ["s3d_room_800x600.png"], False, 1)),
        Case("S3-PANO", "api-scene3d", "全景 2:1 触发立方体切分（LLM）",
             s3_analyze_image_case(base_url, ["s3d_panorama_2048x1024.png"], True, 1)),
        Case("S3-ORBIT", "api-scene3d", "6 图多视角融合（LLM）",
             s3_analyze_image_case(base_url, [f"s3d_orbit_{i}_512x512.png" for i in range(1, 7)],
                                   False, 6)),
        Case("S3-REF", "api-scene3d", "参考视频→SceneScript（LLM，1-2 分钟）",
             s3_analyze_reference_case(base_url)),
    ]
    cases.append(Case("S3-DEPTH", "api-scene3d", "视频深度提取（依赖见 S3-DEPS；手动步骤）",
                      lambda: (SKIP, {"reason": "深度提取留手动步骤，见 plans/3d-previs-plan.md §3"})))
    if not alive:
        for case in cases:
            case.fn = lambda skip=skip: (SKIP, dict(skip))
    return cases


# ---------------------------------------------------------------- 主流程

def write_report(run_dir: Path, results: list[dict], args) -> None:
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "report.json").write_text(
        json.dumps({"generated_at": datetime.now(timezone.utc).isoformat(),
                    "base_url": args.base_url, "results": results},
                   ensure_ascii=False, indent=2), encoding="utf-8")
    counts = {s: sum(1 for r in results if r["status"] == s) for s in (PASS, FAIL, SKIP)}
    lines = [
        f"# 测试运行 {run_dir.name}",
        "",
        f"- 时间：{datetime.now(timezone.utc).isoformat()}",
        f"- 后端：{args.base_url}（local 套件不依赖）",
        f"- 结果：**PASS {counts[PASS]} / FAIL {counts[FAIL]} / SKIP {counts[SKIP]}**",
        f"- 退出码：{'0' if counts[FAIL] == 0 else '1'}",
        "",
        "| 用例 | 套件 | 状态 | 耗时 | 标题 | 说明 |",
        "|---|---|---|---|---|---|",
    ]
    for r in results:
        note = ""
        if r["status"] == FAIL:
            note = str(r["detail"].get("expected") or r["detail"].get("error", ""))[:120]
        elif r["status"] == SKIP:
            note = str(r["detail"].get("reason") or r["detail"].get("error", ""))[:120]
        else:
            note = json.dumps(r["detail"].get("actual", ""), ensure_ascii=False)[:120]
        lines.append(f"| {r['id']} | {r['suite']} | {r['status']} | {r['seconds']}s "
                     f"| {r['title']} | {note} |")
    failed = [r["id"] for r in results if r["status"] == FAIL]
    if failed:
        lines += ["", "## 重跑失败用例", "",
                  "```bash", f"python tools/run_tests.py --only {','.join(failed)}", "```"]
    (run_dir / "summary.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--suite", default="local",
                        help="逗号分隔：media,quality,adreplica,beats,api-replica,api-scene3d 或 local/all")
    parser.add_argument("--only", default="", help="只跑匹配 id（子串）")
    parser.add_argument("--skip", default="", help="排除匹配 id（子串）")
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--full-matrix", action="store_true", help="teardown 全风格矩阵")
    parser.add_argument("--link-url", default=None)
    parser.add_argument("--strict", action="store_true", help="SKIP 也计失败")
    parser.add_argument("--list", action="store_true")
    args = parser.parse_args()

    truth = _load_truth()

    suites = args.suite.split(",")
    if "local" in suites:
        suites = [s for s in suites if s != "local"] + ["media", "quality", "adreplica", "beats"]
    if "all" in suites:
        suites = ["media", "quality", "adreplica", "beats", "api-replica", "api-scene3d"]

    cases: list[Case] = []
    if "media" in suites:
        cases += build_media_cases(truth)
    if "quality" in suites:
        cases += build_quality_cases(truth)
    if "adreplica" in suites:
        cases += build_adreplica_cases()
    if "beats" in suites:
        cases += build_beat_cases(truth)
    if "api-replica" in suites:
        cases += build_api_replica_cases(args.base_url, truth, args.full_matrix, args.link_url)
    if "api-scene3d" in suites:
        cases += build_api_scene3d_cases(args.base_url, with_depth=False)

    if args.only:
        cases = [c for c in cases if any(k in c.id for k in args.only.split(","))]
    if args.skip:
        cases = [c for c in cases if not any(k in c.id for k in args.skip.split(","))]

    if args.list:
        for c in cases:
            print(f"{c.id:<10} [{c.suite:<11}] {c.title}")
        return 0

    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

    results = []
    for case in cases:
        result = case.run()
        results.append(result)
        mark = {"PASS": "✓", "FAIL": "✗", "SKIP": "○"}[result["status"]]
        print(f"{mark} {result['id']:<10} {result['status']:<4} {result['seconds']:>6.1f}s  {result['title']}")
        if result["status"] == FAIL:
            detail = result["detail"]
            print(f"    expected: {detail.get('expected', '')}")
            print(f"    actual:   {str(detail.get('actual', detail.get('error', '')))[:300]}")
        elif result["status"] == SKIP:
            reason = str(result["detail"].get("reason") or result["detail"].get("error", ""))
            print(f"    reason:   {reason[:200]}")

    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    run_dir = RESULTS / f"run-{stamp}"
    write_report(run_dir, results, args)

    counts = {s: sum(1 for r in results if r["status"] == s) for s in (PASS, FAIL, SKIP)}
    print(f"\nPASS {counts[PASS]} / FAIL {counts[FAIL]} / SKIP {counts[SKIP]}"
          f"  →  {run_dir / 'summary.md'}")
    if counts[FAIL]:
        return 1
    if args.strict and counts[SKIP]:
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
