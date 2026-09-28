"""拉片复刻 · teardown 拆解报告缓存（G6：省 LLM 额度 + E2E 提速）。

同一参考视频（**内容 hash** 相同，资产身份由内容蕴含）+ 相同抽帧数/复刻
目标/模型/转录模式 → 同一份拆解报告。命中即跳过全部 LLM 调用（逐帧 + 综合
共 N+1 次），且**如实标注** ``cached``——缓存是优化，不是真相源：

- **键的派生**（``teardown_cache_key``）：schema 版本 + 内容 sha256 +
  num_frames + user_description + 模型名 + 转录 (source, reason)。任何一项
  不同都是不同的报告，绝不混用——用 A 视频的报告回答 B 视频是缓存能造的
  最坏事故；
- **存储**：``<media_data_dir>/replica_teardown_cache/<key>.json``（运行时
  数据，不进 git）；
- **只缓存完整成功的分析**：fixture 降级/LLM 失败/校验失败不进缓存（调用方
  决定写不写，本模块不猜）；
- **损坏/漂移的缓存按 miss 处理**（``load_cached_teardown`` 返回 None）——
  缓存不可用退化为全价分析，绝不把坏数据当报告；
- 写盘尽力而为（原子替换）：写失败只意味着下次全价，不影响本次结果。

转录指纹的取舍（诚实记录）：whisperx 启用时，键在**转录之后**派生（转录
source/reason 进键）——命中仍会先跑转录，换取键的精确性；引擎默认关闭时
转录零成本（立即返回 unavailable），无此问题。
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any

#: 缓存 schema 版本：拆解 prompt / normalize 规则发生实质变化时 +1，
#: 旧键自然失效（不同键），不需要清理旧文件。
CACHE_SCHEMA_VERSION = 1

#: media_data_dir 下的缓存目录名（运行时数据，.gitignore 覆盖 uploads/）。
CACHE_DIR_NAME = "replica_teardown_cache"

#: 内容 hash 的读块大小（参考视频 ≤60s，但块读不假设文件大小）。
_HASH_CHUNK_BYTES = 1024 * 1024


def teardown_cache_dir(media_data_dir: Path) -> Path:
    """缓存目录（调用方负责存在性；本模块读写时自建）。"""
    return Path(media_data_dir) / CACHE_DIR_NAME


def file_content_hash(path: Path) -> str:
    """文件内容的 sha256（分块读；同一内容永远同一 hash）。"""
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        while True:
            chunk = handle.read(_HASH_CHUNK_BYTES)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def teardown_cache_key(
    *,
    video_path: Path,
    num_frames: int,
    user_description: str | None,
    model: str,
    transcript_source: str,
    transcript_reason: str | None,
) -> str:
    """派生缓存键：任何影响报告的因素变化 → 不同键。

    ``transcript_source/reason`` 由**本次运行实际拿到的转录状态**决定
    （whisperx 开/关、可用/降级都会改变报告里的 transcript 块），所以键在
    转录之后派生——宁可命中时多跑一次本地转录，也不把"带降级转录的报告"
    发给一个 whisperx 正常的运行。
    """
    header = json.dumps(
        {
            "schema": CACHE_SCHEMA_VERSION,
            "content_hash": file_content_hash(video_path),
            "num_frames": int(num_frames),
            "user_description": (user_description or "").strip(),
            "model": model or "",
            "transcript_source": transcript_source or "",
            "transcript_reason": transcript_reason or "",
        },
        ensure_ascii=False,
        sort_keys=True,
    )
    return hashlib.sha256(header.encode("utf-8")).hexdigest()


def _cache_path(cache_dir: Path, key: str) -> Path:
    return Path(cache_dir) / f"{key}.json"


def load_cached_teardown(cache_dir: Path, key: str) -> dict[str, Any] | None:
    """读取缓存报告；任何损坏/缺失/不可解析都返回 None（按 miss 处理）。

    返回的 payload 形状见 ``save_cached_teardown``。**本函数不校验报告
    语义**——调用方用 schema 复核（漂移的旧格式按 miss 退化为全价分析）。
    """
    path = _cache_path(cache_dir, key)
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError:
        return None
    try:
        payload = json.loads(raw)
    except (ValueError, TypeError):
        return None
    if not isinstance(payload, dict) or payload.get("key") != key:
        return None
    if payload.get("cache_schema") != CACHE_SCHEMA_VERSION:
        return None
    report = payload.get("report")
    if not isinstance(report, dict):
        return None
    return payload


def save_cached_teardown(
    cache_dir: Path,
    key: str,
    payload: dict[str, Any],
) -> bool:
    """原子写入缓存（tmp + replace）；尽力而为，失败返回 False 不抛出。

    写失败 = 下次全价分析，不影响本次结果；静默失败在这里是可接受的
    （缓存不是链路依赖），调用方无需处理。
    """
    path = _cache_path(cache_dir, key)
    tmp_path = path.with_suffix(".json.tmp")
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        os.replace(tmp_path, path)
    except OSError:
        try:
            tmp_path.unlink(missing_ok=True)
        except OSError:
            pass
        return False
    return True
