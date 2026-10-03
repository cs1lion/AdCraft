"""Previs clip publishing orchestration (ADR 0017).

The publisher is pure coordination over injected services, so these tests
lock the contract around that seam: which error code each refusal carries,
what the created node/binding/lineage look like on the happy path (one
atomic ``add_node_with_bindings`` revision carrying a ready node with its
output asset), and that the keyframes recorded in the clip content are the
ones the flash degradation channel will later consume.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import pytest

from app.persistence.errors import V2PersistenceError
from app.schemas.agent_canvas import CanvasPositionV2, ProjectAssetV2
from app.services.scene3d import previs_clip_publisher as module
from app.services.scene3d.previs_clip_publisher import PrevisClipPublisher


def _scene_script() -> dict:
    return {
        "scene": {"name": "lunar-base", "environment": "outdoor", "duration": 4.0, "frame_rate": 30},
        "characters": [
            {
                "id": "char_a",
                "type": "lowpoly_human",
                "appearance": {"color": "#E74C3C"},
                "keyframes": [
                    {"frame": 0, "position": [0, 0, 0], "rotation_y": 0, "action": "stand"},
                ],
            }
        ],
        "cameras": [
            {
                "id": "cam1",
                "shot_type": "wide",
                "keyframes": [{"frame": 0, "position": [5, -6, 2.6], "look_at": [0, 0, 1.2]}],
            },
        ],
        "shots": [
            {"id": "s1", "camera": "cam1", "start_frame": 0, "end_frame": 60, "description": "异形破土"},
            {"id": "s2", "camera": "cam1", "start_frame": 61, "end_frame": 120, "description": "还击"},
        ],
    }


@dataclass
class FakeWorkflows:
    """原子 add_node_with_bindings：一次 revision 落节点+绑定。"""

    revision: int = 7
    added: list = field(default_factory=list)

    def add_node_with_bindings(self, node, bindings, *, expected_revision):
        if expected_revision != self.revision:
            raise AssertionError("stale expected_revision passed to repository")
        self.added.append((node, tuple(bindings)))
        self.revision += 1
        return type("Workflow", (), {"revision": self.revision})()


@dataclass
class FakeNodes:
    patched: list = field(default_factory=list)

    def patch(self, workflow_id, node_id, request, *, expected_revision):
        self.patched.append((node_id, request.structured_content, expected_revision))
        return node_id


@dataclass
class FakeAssets:
    paths: dict = field(default_factory=dict)
    published: list = field(default_factory=list)
    next_asset_id: int = 1

    def resolve_asset_path(self, asset_id):
        return self.paths[asset_id]

    def publish_generated_bytes(self, workflow_id, **kwargs):
        self.published.append(kwargs)
        asset = ProjectAssetV2(
            asset_id=f"asset_k{self.next_asset_id}",
            version_id=f"version_asset_k{self.next_asset_id}",
            media_type="video" if kwargs["mime_type"] == "video/mp4" else "image",
            source_type="derived",
            display_name=kwargs["filename"],
            mime_type=kwargs["mime_type"],
            status="ready",
            checksum="c" * 64,
        )
        self.next_asset_id += 1
        return asset

    def validate_asset_backed_node(self, asset_id, node_type):
        assert node_type == "video"


@dataclass
class FakeRoleValidation:
    calls: list = field(default_factory=list)

    def validate(self, *, node_type, semantic_role, structured_content):
        self.calls.append((node_type, semantic_role))


def _publisher(workflows, nodes, assets, roles) -> PrevisClipPublisher:
    return PrevisClipPublisher(
        workflows=workflows, nodes=nodes, assets=assets, role_validation=roles
    )


def _source_node(**overrides):
    node = type(
        "Node",
        (),
        {
            "node_id": "node_scene3d",
            "node_type": "scene-3d",
            "title": "月面基地",
            "structured_content": {"scene_script": _scene_script()},
            "output_asset_id": "asset_animatic",
            "position": CanvasPositionV2(x=100.0, y=100.0),
        },
    )()
    for key, value in overrides.items():
        setattr(node, key, value)
    return node


def _patch_media(monkeypatch, *, keyframe_count=5):
    def fake_trim(source_path, output_path, *, start_seconds, end_seconds):
        from pathlib import Path

        Path(output_path).write_bytes(b"clip-bytes")
        return type("R", (), {"success": True, "output_path": str(output_path), "error": None})()

    def fake_keyframes(clip_path, *, duration_seconds, count=5):
        return [
            type("K", (), {"offset_seconds": i * duration_seconds / 4, "png_bytes": b"kf"})()
            for i in range(min(keyframe_count, count))
        ]

    monkeypatch.setattr(module, "trim_previs_clip", fake_trim)
    monkeypatch.setattr(module, "extract_keyframes", fake_keyframes)


class TestPublishHappyPath:
    def test_creates_clip_node_binding_and_lineage(self, monkeypatch, tmp_path) -> None:
        _patch_media(monkeypatch)
        workflows, nodes, assets, roles = (
            FakeWorkflows(),
            FakeNodes(),
            FakeAssets(),
            FakeRoleValidation(),
        )
        assets.paths["asset_animatic"] = tmp_path / "animatic.mp4"
        publisher = _publisher(workflows, nodes, assets, roles)

        published = publisher.publish(
            workflow_id="wf_1",
            source_node=_source_node(),
            shot_id="s1",
            take_id=None,
            expected_revision=7,
        )

        # Node: video type, previs role, ready with the clip as its output
        # (a ready video node must carry an output asset — schema invariant).
        added_node, added_bindings = workflows.added[0]
        assert added_node.node_type == "video"
        assert added_node.creative_role == "scene_3d_previs_clip"
        assert added_node.status == "ready"
        assert added_node.output_asset_id == published.clip_asset.asset_id
        assert added_node.title == "预演片段 · 异形破土"
        content = added_node.structured_content
        assert content["scene_3d_node_id"] == "node_scene3d"
        assert content["shot_id"] == "s1"
        assert content["frame_range"] == [0, 60]
        assert content["duration_seconds"] == 2.0
        assert content["source_asset_id"] == "asset_animatic"
        assert len(content["previs_keyframes"]) == 5

        # Binding: scene-3d → clip, video_reference, one atomic revision.
        assert len(added_bindings) == 1
        assert added_bindings[0].source.source_node_id == "node_scene3d"
        assert added_bindings[0].target_node_id == added_node.node_id
        assert added_bindings[0].input_role == "video_reference"

        # Reverse lineage recorded on the scene-3d node with the revision the
        # atomic add produced.
        patched_node_id, patched_content, patched_revision = nodes.patched[0]
        assert patched_revision == 8
        assert patched_node_id == "node_scene3d"
        assert patched_content["published_previs_clips"][0]["node_id"] == added_node.node_id
        assert patched_content["published_previs_clips"][0]["shot_id"] == "s1"
        # The scene script survives the merge — a patch that dropped it would
        # strip the director console of its own scene.
        assert "scene_script" in patched_content

        # Role registry was consulted before creation.
        assert roles.calls == [("video", "scene_3d_previs_clip")]
        # Clip asset published as derived with the previs role.
        clip_publication = assets.published[0]
        assert clip_publication["source_type"] == "derived"
        assert clip_publication["source_semantic_role"] == "scene_3d_previs_clip"
        assert published.clip_asset.media_type == "video"
        assert len(published.keyframe_asset_ids) == 5

    def test_publish_is_deterministic_per_shot(self, monkeypatch, tmp_path) -> None:
        _patch_media(monkeypatch)
        assets = FakeAssets()
        assets.paths["asset_animatic"] = tmp_path / "animatic.mp4"
        workflows = FakeWorkflows()
        publisher = _publisher(workflows, FakeNodes(), assets, FakeRoleValidation())
        source = _source_node()
        publisher.publish(
            workflow_id="wf_1", source_node=source, shot_id="s1", take_id=None,
            expected_revision=workflows.revision,
        )
        first = assets.published[0]["node_id"]
        publisher.publish(
            workflow_id="wf_1", source_node=source, shot_id="s1", take_id=None,
            expected_revision=workflows.revision,
        )
        # 每次发布 = 1 clip + 5 关键帧；第二次发布的 clip 在索引 6
        assert assets.published[6]["node_id"] == first


class TestPublishRefusals:
    def test_non_scene3d_source_is_refused(self, monkeypatch) -> None:
        _patch_media(monkeypatch)
        publisher = _publisher(FakeWorkflows(), FakeNodes(), FakeAssets(), FakeRoleValidation())
        with pytest.raises(V2PersistenceError) as excinfo:
            publisher.publish(
                workflow_id="wf_1",
                source_node=_source_node(node_type="video"),
                shot_id="s1",
                take_id=None,
                expected_revision=7,
            )
        assert excinfo.value.code == "previs_clip_source_not_scene3d"

    def test_missing_scene_script_is_refused(self, monkeypatch) -> None:
        _patch_media(monkeypatch)
        publisher = _publisher(FakeWorkflows(), FakeNodes(), FakeAssets(), FakeRoleValidation())
        with pytest.raises(V2PersistenceError) as excinfo:
            publisher.publish(
                workflow_id="wf_1",
                source_node=_source_node(structured_content={}),
                shot_id="s1",
                take_id=None,
                expected_revision=7,
            )
        assert excinfo.value.code == "previs_clip_scene_script_missing"

    def test_unknown_shot_names_the_available_shots(self, monkeypatch) -> None:
        _patch_media(monkeypatch)
        publisher = _publisher(FakeWorkflows(), FakeNodes(), FakeAssets(), FakeRoleValidation())
        with pytest.raises(V2PersistenceError) as excinfo:
            publisher.publish(
                workflow_id="wf_1", source_node=_source_node(), shot_id="s9", take_id=None, expected_revision=7
            )
        assert excinfo.value.code == "previs_clip_shot_not_found"
        assert excinfo.value.details == {"shot_ids": ["s1", "s2"]}

    def test_unrendered_animatic_tells_the_operator_what_to_do(self, monkeypatch) -> None:
        _patch_media(monkeypatch)
        publisher = _publisher(FakeWorkflows(), FakeNodes(), FakeAssets(), FakeRoleValidation())
        with pytest.raises(V2PersistenceError) as excinfo:
            publisher.publish(
                workflow_id="wf_1",
                source_node=_source_node(output_asset_id=None),
                shot_id="s1",
                take_id=None,
                expected_revision=7,
            )
        assert excinfo.value.code == "scene3d_animatic_missing"
