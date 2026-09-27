"""拉片复刻 · 参考片链接下载（hypit ``media fetch`` 同款入口）。

支持粘贴视频链接（B 站/YouTube 等 yt-dlp 支持的站点），服务端下载后走
与上传完全相同的校验与存储（``save_reference_video``：格式/大小/时长
≤60s + 抽帧 + asset_id）——链接是上传的另一种来源，不是旁路。

依赖策略（engineering-standards §4）：yt-dlp 是可选外部工具（子进程调用
PATH 上的可执行文件，未安装/失败都**显式降级**——结构化原因返回给前端，
绝不静默）。下载是网络操作：超时与失败都有界。

    链接 ──yt-dlp──▶ 临时视频 ──save_reference_video──▶ asset_id（同上传）
         └─ 不可用/失败 ──▶ IngestError(code, message)（observable）
"""

from __future__ import annotations

import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from app.services.scene3d.reference_upload import (
    UploadError,
    UploadResult,
    save_reference_video,
)

_YTDLP_TIMEOUT_SECONDS = 300

REASON_YTDLP_MISSING = "ytdlp_missing"
REASON_DOWNLOAD_FAILED = "download_failed"
REASON_INVALID_URL = "invalid_url"

_ALLOWED_URL_SCHEMES = {"http", "https"}


class IngestError(Exception):
    """链接下载不可用/失败（code 供前端与约束显式展示）。"""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class LinkIngestResult:
    """链接下载结果：与上传同构的 asset 信息。"""

    asset_id: str
    file_name: str
    source_url: str


def _resolve_ytdlp() -> str | None:
    """PATH 上的 yt-dlp 可执行文件；找不到返回 None（显式降级）。"""
    return shutil.which("yt-dlp")


def _validate_url(url: str) -> str:
    url = (url or "").strip()
    scheme = url.split(":", 1)[0].lower() if ":" in url else ""
    if scheme not in _ALLOWED_URL_SCHEMES:
        raise IngestError(
            REASON_INVALID_URL,
            f"Unsupported URL scheme: {scheme or '(empty)'} (expected http/https)",
        )
    return url


def _default_downloader(url: str, output_path: Path) -> None:
    executable = _resolve_ytdlp()
    if executable is None:
        raise IngestError(
            REASON_YTDLP_MISSING,
            "yt-dlp is not installed on the server (pip install yt-dlp)",
        )
    command = [
        executable,
        "--no-playlist",
        # 拉片面向 ≤60s 短片：限制高度控制体积，格式回退到最差可用
        "-f",
        "best[height<=1080]/best",
        "-o",
        str(output_path),
        "--no-progress",
        url,
    ]
    try:
        completed = subprocess.run(
            command,
            capture_output=True,
            text=True,
            check=False,
            timeout=_YTDLP_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired as exc:
        raise IngestError(
            REASON_DOWNLOAD_FAILED, f"yt-dlp timed out after {_YTDLP_TIMEOUT_SECONDS}s"
        ) from exc
    except OSError as exc:
        raise IngestError(REASON_DOWNLOAD_FAILED, f"yt-dlp failed to run: {exc}") from exc
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout or "").strip()[-300:]
        raise IngestError(
            REASON_DOWNLOAD_FAILED, f"yt-dlp failed: {detail or 'unknown error'}"
        )


def ingest_reference_link(
    url: str,
    *,
    upload_dir: Path | None = None,
    downloader: Callable[[str, Path], None] = _default_downloader,
) -> LinkIngestResult:
    """链接 → yt-dlp 下载 → 与上传相同的校验/存储 → asset_id。

    Raises:
        IngestError: URL 非法 / yt-dlp 不可用 / 下载失败（结构化 code）。
        UploadError: 下载产物未通过上传校验（超长/超大/非视频）。
    """
    validated_url = _validate_url(url)
    with tempfile.TemporaryDirectory(prefix="replica_ingest_") as tmp_dir:
        # yt-dlp 依据扩展名选择输出容器：先给 mp4 占位
        output_path = Path(tmp_dir) / "reference.mp4"
        downloader(validated_url, output_path)
        if not output_path.exists() or output_path.stat().st_size == 0:
            raise IngestError(
                REASON_DOWNLOAD_FAILED,
                "yt-dlp produced no file (unsupported site or geo-block?)",
            )
        try:
            result: UploadResult = save_reference_video(
                file_bytes=output_path.read_bytes(),
                file_name="reference.mp4",
                upload_dir=upload_dir,
            )
        except UploadError as exc:
            # 下载成功但产物不合格（>60s 等）：沿用上传的错误语义
            raise IngestError(
                f"invalid_download_{exc.error_type}", str(exc)
            ) from exc
    return LinkIngestResult(
        asset_id=result.asset_id,
        file_name=result.file_name,
        source_url=validated_url,
    )
