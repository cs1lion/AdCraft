"""Unit tests for the reference-link ingestion (hypit `media fetch` 同款).

Covers: URL validation, structured degradation when yt-dlp is missing or the
download fails, the same-validation-as-upload contract (long downloads are
rejected via UploadError semantics), and the endpoint contract. No network:
the downloader boundary is injected.

Design rationale: docs/plans/hypit-replica-research.md §2.3 (E3 链接入口)
and engineering-standards §4 (observable degradation).
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.services.replica import ingest as ing


# ---------------------------------------------------------------------------
# URL 校验
# ---------------------------------------------------------------------------


def test_invalid_scheme_rejected() -> None:
    for bad in ["ftp://x", "javascript:alert(1)", "file:///c:/v.mp4", "   "]:
        with pytest.raises(ing.IngestError, match="Unsupported URL scheme"):
            ing.ingest_reference_link(bad, downloader=lambda u, p: None)


def test_url_is_trimmed_and_normalized(tmp_path, monkeypatch) -> None:
    captured: dict = {}

    monkeypatch.setattr(
        ing,
        "save_reference_video",
        lambda **kw: type("R", (), {"asset_id": "ref_x", "file_name": "x.mp4"})(),
    )

    def downloader(url: str, output: Path) -> None:
        captured["url"] = url
        output.write_bytes(b"fake")

    result = ing.ingest_reference_link(
        "  https://example.com/v?id=1  ",
        downloader=downloader,
        upload_dir=tmp_path,
    )
    assert result.asset_id == "ref_x"
    assert captured["url"] == "https://example.com/v?id=1"


# ---------------------------------------------------------------------------
# 降级路径（每一条都结构化可查询）
# ---------------------------------------------------------------------------


def test_ytdlp_missing_degrades(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(ing, "_resolve_ytdlp", lambda: None)

    def downloader(url: str, output: Path) -> None:
        ing._default_downloader(url, output)  # 走真实实现触发 missing 分支

    with pytest.raises(ing.IngestError) as exc:
        ing.ingest_reference_link(
            "https://example.com/v", downloader=downloader, upload_dir=tmp_path
        )
    assert exc.value.code == ing.REASON_YTDLP_MISSING


def test_download_failure_degrades(tmp_path) -> None:
    def boom(url: str, output: Path) -> None:
        raise ing.IngestError(ing.REASON_DOWNLOAD_FAILED, "site unreachable")

    with pytest.raises(ing.IngestError) as exc:
        ing.ingest_reference_link(
            "https://example.com/v", downloader=boom, upload_dir=tmp_path
        )
    assert exc.value.code == ing.REASON_DOWNLOAD_FAILED


def test_empty_download_artifact_degrades(tmp_path) -> None:
    def empty(url: str, output: Path) -> None:
        output.write_bytes(b"")  # yt-dlp 返回 0 但产物为空

    with pytest.raises(ing.IngestError, match="produced no file"):
        ing.ingest_reference_link(
            "https://example.com/v", downloader=empty, upload_dir=tmp_path
        )


# ---------------------------------------------------------------------------
# 与上传同流：成功路径复用 save_reference_video 的校验/存储
# ---------------------------------------------------------------------------


def test_successful_download_saves_via_upload_pipeline(tmp_path, monkeypatch) -> None:
    """存储契约：走 save_reference_video（与本地上传同一函数）。"""
    class _FakeUploadResult:
        asset_id = "ref_saved12345"
        file_name = "ref_saved12345.mp4"

    captured: dict = {}

    def fake_save(**kwargs):
        captured.update(kwargs)
        return _FakeUploadResult()

    monkeypatch.setattr(ing, "save_reference_video", fake_save)

    def ok(url: str, output: Path) -> None:
        output.write_bytes(b"fake-video-bytes")

    result = ing.ingest_reference_link(
        "https://example.com/v", downloader=ok, upload_dir=tmp_path
    )
    assert result.asset_id.startswith("ref_")
    assert result.source_url == "https://example.com/v"
    # upload_dir 透传给 save_reference_video（与本地上传同一目录约定）
    assert captured["upload_dir"] == tmp_path
    assert captured["file_name"] == "reference.mp4"


def test_overlong_download_rejected_with_upload_semantics(tmp_path, monkeypatch) -> None:
    """下载产物 >60s：沿用上传的 invalid_duration 语义（不静默放行）。"""
    from app.services.scene3d.reference_upload import VideoMetadata

    def ok(url: str, output: Path) -> None:
        output.write_bytes(b"fake-video-bytes")

    monkeypatch.setattr(
        "app.services.scene3d.reference_upload.extract_metadata",
        lambda path: VideoMetadata(
            duration_seconds=300.0,
            width=1080,
            height=1920,
            frame_rate=30.0,
            frame_count=9000,
            codec_name="h264",
            file_size_bytes=1024,
        ),
    )
    with pytest.raises(ing.IngestError) as exc:
        ing.ingest_reference_link(
            "https://example.com/v", downloader=ok, upload_dir=tmp_path
        )
    assert exc.value.code == "invalid_download_invalid_duration"


# ---------------------------------------------------------------------------
# 端点契约
# ---------------------------------------------------------------------------


@pytest.fixture
def ingest_client(monkeypatch, tmp_path):
    from app.api.v1.endpoints import replica as replica_endpoint

    # 端点在函数体内局部 import：patch 源模块属性
    monkeypatch.setattr(
        "app.services.replica.ingest.ingest_reference_link",
        lambda url, **kw: ing.LinkIngestResult(
            asset_id="ref_ingested01",
            file_name="ref_ingested01.mp4",
            source_url=url,
        ),
    )
    app = FastAPI()
    app.include_router(replica_endpoint.router)
    return TestClient(app)


def test_ingest_link_endpoint(ingest_client) -> None:
    response = ingest_client.post(
        "/replica/ingest-link", json={"url": "https://example.com/v"}
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["success"] is True
    assert body["asset_id"] == "ref_ingested01"
    assert body["source_url"] == "https://example.com/v"


def test_ingest_link_endpoint_surfaces_degradation(monkeypatch) -> None:
    from app.api.v1.endpoints import replica as replica_endpoint
    from app.services.replica.ingest import IngestError

    monkeypatch.setattr(
        "app.services.replica.ingest.ingest_reference_link",
        lambda url, **kw: (_ for _ in ()).throw(
            IngestError(ing.REASON_YTDLP_MISSING, "yt-dlp is not installed on the server")
        ),
    )
    app = FastAPI()
    app.include_router(replica_endpoint.router)
    client = TestClient(app)
    response = client.post(
        "/replica/ingest-link", json={"url": "https://example.com/v"}
    )
    assert response.status_code == 422, response.text
    detail = response.json()["detail"]
    assert detail["error_type"] == "ytdlp_missing"
