"""Asset version chain: repository ordering, service 404, endpoint wiring.

Backs the version-stack comparison (Frame.io-style "compare with previous
version") in the sync-compare panel: the endpoint returns one asset's
immutable versions oldest-first so the frontend can walk the chain.
Mutation check: flipping the repository ORDER BY to descending makes the
oldest-first assertion red; dropping the empty-chain guard in the service
makes the 404 assertion red.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.v2.endpoints import agent_canvas as endpoint
from app.persistence.asset_library_repository import V2AssetLibraryRepository
from app.persistence.database import create_v2_database
from app.persistence.errors import V2PersistenceError
from app.persistence.schema import upgrade_v2_schema
from app.schemas.v2_asset_library import (
    AssetRecordCreate,
    AssetVersionCreate,
    AssetVersionMetadataV2,
)

pytestmark = pytest.mark.integration


def _asset(asset_id: str) -> AssetRecordCreate:
    return AssetRecordCreate(
        asset_id=asset_id,
        media_type="video",
        source_type="generated",
        display_name="入局 · 预演白模",
    )


def _version(asset_id: str, version_no: int, parent_version_id: str | None) -> AssetVersionCreate:
    return AssetVersionCreate(
        version_id=f"ver_{asset_id}_{version_no}",
        asset_id=asset_id,
        version_no=version_no,
        storage_key=f"generated/{asset_id}/v{version_no}.mp4",
        sha256=f"sha-{asset_id}-{version_no}",
        size_bytes=1024 * version_no,
        mime_type="video/mp4",
        width=1280,
        height=720,
        duration_seconds=15.0,
        source_node_id="node_wm",
        parent_version_id=parent_version_id,
    )


def _repository(tmp_path: Path) -> V2AssetLibraryRepository:
    (tmp_path / "v2").mkdir()
    database = create_v2_database(tmp_path)
    upgrade_v2_schema(database)
    return V2AssetLibraryRepository(database)


def test_list_versions_returns_chain_oldest_first(tmp_path: Path) -> None:
    repository = _repository(tmp_path)
    repository.create_asset_version(_asset("asset_wm"), _version("asset_wm", 1, None))
    repository.create_asset_version(
        _asset("asset_wm"), _version("asset_wm", 2, "ver_asset_wm_1")
    )

    versions = repository.list_versions("asset_wm")

    assert [item.version_no for item in versions] == [1, 2]
    assert versions[0].parent_version_id is None
    assert versions[1].parent_version_id == "ver_asset_wm_1"
    assert all(item.status == "ready" for item in versions)


def test_list_versions_missing_asset_returns_empty(tmp_path: Path) -> None:
    repository = _repository(tmp_path)
    assert repository.list_versions("asset_missing") == ()


class _AssetsStub:
    def __init__(self, versions: tuple[AssetVersionMetadataV2, ...], error: V2PersistenceError | None = None) -> None:
        self._versions = versions
        self._error = error

    def list_versions(self, asset_id: str) -> list[AssetVersionMetadataV2]:
        if self._error is not None:
            raise self._error
        return list(self._versions)


class _RuntimeStub:
    def __init__(self, assets: _AssetsStub) -> None:
        self.assets = assets


def _client(assets: _AssetsStub) -> TestClient:
    app = FastAPI()
    app.include_router(endpoint.router)
    app.dependency_overrides[endpoint.get_agent_canvas_runtime] = lambda: _RuntimeStub(assets)
    return TestClient(app)


def test_endpoint_returns_version_chain_oldest_first() -> None:
    versions = (
        AssetVersionMetadataV2(
            version_id="ver_1",
            asset_id="asset_wm",
            version_no=1,
            storage_key="generated/a/v1.mp4",
            sha256="sha-1",
            size_bytes=1,
            mime_type="video/mp4",
            status="ready",
            created_at="2026-10-11T00:00:00Z",
        ),
        AssetVersionMetadataV2(
            version_id="ver_2",
            asset_id="asset_wm",
            version_no=2,
            storage_key="generated/a/v2.mp4",
            sha256="sha-2",
            size_bytes=2,
            mime_type="video/mp4",
            parent_version_id="ver_1",
            status="ready",
            created_at="2026-10-11T00:01:00Z",
        ),
    )
    response = _client(_AssetsStub(versions)).get("/assets/asset_wm/versions")

    assert response.status_code == 200, response.text
    body = response.json()
    assert [item["version_no"] for item in body["versions"]] == [1, 2]
    assert body["versions"][1]["parent_version_id"] == "ver_1"


def test_endpoint_maps_unknown_asset_to_404() -> None:
    client = _client(
        _AssetsStub(
            (),
            error=V2PersistenceError("asset_not_found", "Asset not found: asset_missing."),
        )
    )

    response = client.get("/assets/asset_missing/versions")

    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "asset_not_found"
