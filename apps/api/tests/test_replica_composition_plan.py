"""One clock and honest authored captions; mutations reject invalid sound windows."""

from types import SimpleNamespace as NS

import pytest
from pydantic import ValidationError

from app.schemas.agent_canvas_ad_media import ReplicaBlueprintContentV2
from app.services.creation.film_assembly import plan_assembly
from app.services.creation.replica_composition import (
    ReplicaAudioPlacementV1,
    plan_replica_composition,
)

pytestmark = pytest.mark.integration


def plan(**kwargs):
    nodes = [
        NS(
            node_type="video",
            node_id=f"n{i}",
            title=f"镜头{i}",
            output_asset_id=f"a{i}",
            output_asset_version_id=f"v{i}",
            structured_content={"duration_seconds": 4},
        )
        for i in (1, 2)
    ]
    blueprint = ReplicaBlueprintContentV2(
        shots=[
            dict(
                index=i,
                start_seconds=(i - 1) * 0.5,
                end_seconds=i * 0.5,
                on_screen_text=f"caption {i}",
            )
            for i in (1, 2)
        ],
        beats=[
            dict(
                beat_id="old",
                line="reference words",
                start_seconds=0,
                end_seconds=1,
                words=[dict(text="reference", start_seconds=0, end_seconds=0.1)],
            )
        ],
    )
    return plan_replica_composition(
        plan_assembly("video", nodes), replica_node_id="r", blueprint=blueprint, **kwargs
    )


def test_captions_follow_shot_identity_not_blueprint_array_order():
    nodes = [
        NS(
            node_type="video",
            node_id="n2",
            title="shot2",
            output_asset_id="a2",
            output_asset_version_id="v2",
            structured_content={"duration_seconds": 4},
        )
    ]
    assembly = plan_assembly("video", nodes)
    blueprint = ReplicaBlueprintContentV2(
        shots=[
            dict(index=2, start_seconds=0, end_seconds=4, on_screen_text="second"),
            dict(index=1, start_seconds=4, end_seconds=8, on_screen_text="first"),
        ]
    )
    result = plan_replica_composition(assembly, replica_node_id="r", blueprint=blueprint)
    assert next(c for c in result.timeline.clips if c.clip_type == "subtitle").text == "second"


def test_one_clock_does_not_copy_reference_word_windows():
    result = plan()
    captions = [c for c in result.timeline.clips if c.clip_type == "subtitle"]
    assert [(c.start_time, c.duration, c.text) for c in captions] == [
        (0, 4, "caption 1"),
        (4, 4, "caption 2"),
    ]
    assert result.timeline.duration_seconds == 8
    assert result.timeline.metadata["requires_timeline_editor"]
    assert all(c.metadata["timing_quality"] == "authored_shot" for c in captions)
    assert all("words" not in c.metadata for c in captions)


def test_role_version_and_ducking_are_explicit_and_hashed():
    audio = ReplicaAudioPlacementV1(
        role="bgm", asset_id="music", asset_version_id="mv", duration_seconds=8, volume=0.3
    )
    result = plan(audio_clips=[audio], ducking=True)
    clip = next(c for c in result.timeline.clips if c.clip_type == "audio")
    assert clip.metadata["audio_role"] == "bgm"
    assert clip.source_version_id == "mv"
    assert clip.audio.volume == 0.3
    assert result.plan_hash != plan(audio_clips=[audio], ducking=False).plan_hash


def test_mutating_sound_outside_picture_is_rejected():
    audio = ReplicaAudioPlacementV1(
        role="sfx", asset_id="x", asset_version_id="v", start_seconds=7, duration_seconds=2
    )
    with pytest.raises(ValueError, match="fit the picture"):
        plan(audio_clips=[audio])
    with pytest.raises(ValidationError):
        ReplicaAudioPlacementV1(
            role="sfx", asset_id="x", asset_version_id="v", duration_seconds=float("nan")
        )


def test_mutating_caption_changes_plan_but_disabling_does_not_create_false_words():
    enabled = plan()
    disabled = plan(include_captions=False)
    assert enabled.plan_hash != disabled.plan_hash
    assert all(c.clip_type != "subtitle" for c in disabled.timeline.clips)
