"""Flash-specific documented lookup and size contract, without network calls."""

from urllib.parse import parse_qs, urlsplit

import pytest

from app.core.config import Settings
from app.services.provider_model_catalog import _TRUSTED_MANIFESTS
from app.tools.seedance_adapter import VolcengineSeedanceAdapter, _video_generation_task_url

pytestmark = pytest.mark.integration


def test_flash_catalog_only_offers_documented_720p():
    # Mutation: offering 480p/1080p would permit requests the provider rejects.
    flash = next(m for m in _TRUSTED_MANIFESTS if m.provider_model_id == "agnes-video-2.5-flash")
    regular = next(m for m in _TRUSTED_MANIFESTS if m.provider_model_id == "agnes-video-2.5")
    assert flash.capability_metadata["supported_resolutions"] == ["720p"]
    assert regular.capability_metadata["supported_resolutions"] == ["480p", "720p", "1080p"]


def test_flash_lookup_carries_model_and_encodes_untrusted_task_id():
    adapter = VolcengineSeedanceAdapter(
        Settings(
            video_generation_endpoint="https://api.agnes-ai.cn/v1/videos",
            video_generation_model="agnes-video-2.5-flash",
        )
    )
    url = urlsplit(adapter.task_url("task&mode=other"))
    assert url.path == "/agnesapi"
    assert parse_qs(url.query) == {
        "video_id": ["task&mode=other"],
        "model_name": ["agnes-video-2.5-flash"],
    }


def test_non_agnes_lookup_keeps_existing_path_contract():
    assert (
        _video_generation_task_url(
            "https://ark.example/api/tasks", "task id", "agnes-video-2.5-flash"
        )
        == "https://ark.example/api/tasks/task%20id"
    )


def test_missing_model_keeps_backwards_compatible_lookup():
    assert (
        _video_generation_task_url("https://api.agnes-ai.cn/v1/videos", "task")
        == "https://api.agnes-ai.cn/agnesapi?video_id=task"
    )
