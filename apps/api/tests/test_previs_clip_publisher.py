"""Previs clip publishing orchestration (ADR 0017).

The publisher is pure coordination over injected services, so these tests
lock the contract around that seam: which error code each refusal carries,
what the created node/binding/lineage look like on the happy path, and that
the keyframes recorded in the clip content are the ones the flash
degradation channel will later consume.
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
class FakeNodes:
    created: list = field(default_factory=list)
    patched: list = field(default_factory=list)

    def create(self, workflow_id, request, *, expected_revision):
        node = type(
            "Node",
            (),
            {
                "node_id": "node_newclip",
                "node_type": request.node_type,
                "creative_role": request.creative_role,
                "title": request.title,
                "structured_content": request.structured_content,
                "output_asset_id": request.source_asset_id,
                "status": "ready",
            },
        )()
        self.created.append(node)
        return node

    def patch(self, workflow_id, node_id, request, *, expected_revision):
        self.patched.append((node_id, request.structured_content))
        return node_id


@dataclass
class FakeBindings:
    created: list = field(default_factory=list)

    def create(self, workflow_id, request, *, expected_revision):
        self.created.append(request)
        return type(
            "Binding",
            (),
            {
                "binding_id": "binding_1",
                "source": request.source,
                "target_node_id": request.target_node_id,
                "input_role": request.input_role,
            },
        )()


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


def _publisher(nodes, bindings, assets, roles) -> PrevisClipPublisher:
    return PrevisClipPublisher(
        nodes=nodes, bindings=bindings, assets=assets, role_validation=roles
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
        nodes, bindings, assets, roles = FakeNodes(), FakeBindings(), FakeAssets(), FakeRoleValidation()
        assets.paths["asset_animatic"] = tmp_path / "animatic.mp4"
        publisher = _publisher(nodes, bindings, assets, roles)

        published = publisher.publish(
            workflow_id="wf_1",
            source_node=_source_node(),
            shot_id="s1",
        )

        # Node: video type, previs role, title carries the shot label.
        assert nodes.created[0].node_type == "video"
        assert nodes.created[0].creative_role == "scene_3d_previs_clip"
        assert "异形破土" in nodes.created[0].title
        content = nodes.created[0].structured_content
        assert content["scene_3d_node_id"] == "node_scene3d"
        assert content["shot_id"] == "s1"
        assert content["frame_range"] == [0, 60]
        assert content["duration_seconds"] == 2.0
        assert content["source_asset_id"] == "asset_animatic"
        assert len(content["previs_keyframes"]) == 5

        # Binding: scene-3d → clip, video_reference.
        assert bindings.created[0].source.source_node_id == "node_scene3d"
        assert bindings.created[0].target_node_id == "node_newclip"
        assert bindings.created[0].input_role == "video_reference"

        # Reverse lineage recorded on the scene-3d node.
        patched_node_id, patched_content = nodes.patched[0]
        assert patched_node_id == "node_scene3d"
        assert patched_content["published_previs_clips"][0]["node_id"] == "node_newclip"
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
        publisher = _publisher(FakeNodes(), FakeBindings(), assets, FakeRoleValidation())
        source = _source_node()
        publisher.publish(workflow_id="wf_1", source_node=source, shot_id="s1")
        first = assets.published[0]["node_id"]
        publisher.publish(workflow_id="wf_1", source_node=source, shot_id="s1")
        assert assets.published[2]["node_id"] == first


class TestPublishRefusals:
    def test_non_scene3d_source_is_refused(self, monkeypatch, tmp_path) -> None:
        _patch_media(monkeypatch)
        publisher = _publisher(FakeNodes(), FakeBindings(), FakeAssets(), FakeRoleValidation())
        with pytest.raises(V2PersistenceError) as excinfo:
            publisher.publish(
                workflow_id="wf_1",
                source_node=_source_node(node_type="video"),
                shot_id="s1",
            )
        assert excinfo.value.code == "previs_clip_source_not_scene3d"

    def test_missing_scene_script_is_refused(self, monkeypatch) -> None:
        _patch_media(monkeypatch)
        publisher = _publisher(FakeNodes(), FakeBindings(), FakeAssets(), FakeRoleValidation())
        with pytest.raises(V2PersistenceError) as excinfo:
            publisher.publish(
                workflow_id="wf_1",
                source_node=_source_node(structured_content={}),
                shot_id="s1",
            )
        assert excinfo.value.code == "previs_clip_scene_script_missing"

    def test_unknown_shot_names_the_available_shots(self, monkeypatch) -> None:
        _patch_media(monkeypatch)
        publisher = _publisher(FakeNodes(), FakeBindings(), FakeAssets(), FakeRoleValidation())
        with pytest.raises(V2PersistenceError) as excinfo:
            publisher.publish(workflow_id="wf_1", source_node=_source_node(), shot_id="s9")
        assert excinfo.value.code == "previs_clip_shot_not_found"
        assert excinfo.value.details == {"shot_ids": ["s1", "s2"]}

    def test_unrendered_animatic_tells_the_operator_what_to_do(self, monkeypatch) -> None:
        _patch_media(monkeypatch)
        publisher = _publisher(FakeNodes(), FakeBindings(), FakeAssets(), FakeRoleValidation())
        with pytest.raises(V2PersistenceError) as excinfo:
            publisher.publish(
                workflow_id="wf_1",
                source_node=_source_node(output_asset_id=None),
                shot_id="s1",
            )
        assert excinfo.value.code == "scene3d_animatic_missing"
