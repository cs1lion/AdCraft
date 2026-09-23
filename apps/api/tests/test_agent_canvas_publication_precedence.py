"""Payload metadata outranks the frozen catalog projection (voice-cast stamping).

``generated_asset_publication_metadata`` projects the *catalog* model a node
resolved.  For node types that resolve none -- voice-cast, scene-3d -- that
projection is null, and an asset published straight from it reads as "no
provider, no model" even though a real StepFun / Fish Audio engine produced the
bytes.  ``publish_generated_bytes`` copies ``provenance["provider"]`` and
``provenance["model_id"]`` onto first-class asset-row columns, so the executor
has to be able to state the vendor in its payload metadata and have it win.

That precedence is a dict-unpacking *order*, which is the kind of thing a later
refactor silently inverts.  These tests pin it in the one helper both
publication call sites share.

The second half pins the *other* projection helper,
``project_canvas_publication_metadata``, which the provider-task recovery path
uses instead.  It used to apply the frozen projection *last*, so an executor
that routed a node away from the model it resolved published under the resolved
model's name: a ``bgm`` node resolves the catalog ``audio`` default
(``tianpuyue:TemPolor-i3``) and then builds the configured BGM adapter
(``stepfun_music``), and the asset row said ``tianpuyue`` while the nested
``provider_asset`` said ``stepfun_music``.
"""

from __future__ import annotations

from datetime import datetime, timezone

from app.schemas.agent_canvas import CanvasNodeV2
from app.schemas.agent_canvas_runtime import ResolvedModelExecutionV2
from app.services.agent_canvas_node_execution import (
    NodeExecutionContext,
    NodeExecutionOutcome,
)
from app.services.agent_canvas_output_preparation import (
    _declared_vendor_metadata,
)
from app.services.agent_canvas_publication_metadata import (
    asset_publication_metadata,
    generated_asset_publication_metadata,
    project_canvas_publication_metadata,
)


def _node(node_type: str = "voice-cast", role: str = "voice_cast") -> CanvasNodeV2:
    return CanvasNodeV2(
        node_id="node-voice",
        workflow_id="wf_voice",
        node_type=node_type,  # type: ignore[arg-type]
        creative_role=role,  # type: ignore[arg-type]
        title="Voice node",
        status="draft",
        generation_prompt="speak the line",
        structured_content={},
        position={"x": 0.0, "y": 0.0},
        revision=1,
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )


def _context(
    *,
    provider_id: str | None = None,
    model_id: str | None = None,
    model_resolution: ResolvedModelExecutionV2 | None = None,
) -> NodeExecutionContext:
    """A voice-cast context: no catalog model is resolved for this node type.

    ``provider_id`` / ``model_id`` are separate context fields, not derived from
    ``model_resolution``, so a node type that resolves no catalog model leaves
    them unset -- and the projection drops the resulting ``None`` values.
    """

    return NodeExecutionContext(
        execution_id="exec-voice",
        node=_node(),
        inputs=(),
        provider_id=provider_id,
        model_id=model_id,
        model_resolution=model_resolution,
    )


def _bgm_context(resolution: ResolvedModelExecutionV2) -> NodeExecutionContext:
    """A bgm context as provider-task recovery builds it.

    ``agent_canvas_provider_recovery.py`` sets ``provider_id`` / ``model_id``
    from the frozen ``model_resolution``, so the catalog default is what the
    projection sees until an executor declares otherwise.
    """

    return NodeExecutionContext(
        execution_id="exec-bgm",
        node=_node("audio", "bgm"),
        inputs=(),
        provider_id=resolution.provider_id,
        model_id=resolution.provider_model_id,
        model_resolution=resolution,
    )


class TestPayloadOutranksProjection:
    def test_a_null_catalog_projection_does_not_erase_the_real_vendor(self) -> None:
        # The actual voice-cast shape: the node resolves no catalog model, so the
        # frozen provenance carries no provider key at all.  The executor's
        # payload is the only place the real vendor is known, and it has to reach
        # the merged mapping.
        merged = asset_publication_metadata(
            _context(),
            {"provider": "stepfun", "model_id": "stepaudio-2.5-tts"},
        )
        assert merged["provider"] == "stepfun"
        assert merged["model_id"] == "stepaudio-2.5-tts"

    def test_the_payload_also_overrides_a_resolved_catalog_model(self) -> None:
        # Precedence must not depend on the projection being absent, or the
        # behaviour would differ between node types for no reason the caller can
        # see.  An executor that names its own vendor wins either way.
        merged = asset_publication_metadata(
            _context(provider_id="stepfun", model_id="stepaudio-2.5-tts"),
            {"provider": "fish_audio", "model_id": "fish-speech-1.5"},
        )
        assert merged["provider"] == "fish_audio"
        assert merged["model_id"] == "fish-speech-1.5"

    def test_absent_payload_keys_leave_the_projection_standing(self) -> None:
        # The image/video path stamps its own provider too, but a payload that
        # says nothing about the vendor must not blank the catalog projection.
        merged = asset_publication_metadata(
            _context(provider_id="stepfun", model_id="stepaudio-2.5-tts"),
            {"unrelated": "value"},
        )
        assert merged["provider"] == "stepfun"
        assert merged["model_id"] == "stepaudio-2.5-tts"
        assert merged["unrelated"] == "value"

    def test_no_payload_at_all_keeps_the_frozen_provenance(self) -> None:
        context = _context(provider_id="stepfun", model_id="stepaudio-2.5-tts")
        assert asset_publication_metadata(context, None) == (
            generated_asset_publication_metadata(context)
        )

    def test_a_node_with_no_catalog_model_and_no_payload_stays_unstamped(self) -> None:
        # The bug this precedence fixes: without a payload the merged mapping has
        # no provider key, and publish_generated_bytes would write a null one.
        merged = asset_publication_metadata(_context(), None)
        assert "provider" not in merged
        assert "model_id" not in merged

    def test_the_merged_mapping_is_a_copy(self) -> None:
        # Mutating the merged result must not reach back into the frozen
        # provenance, which the caller may reuse for a second publication.
        context = _context(provider_id="stepfun", model_id="stepaudio-2.5-tts")
        frozen = generated_asset_publication_metadata(context)
        merged = asset_publication_metadata(context, {"provider": "fish_audio"})
        merged["provider"] = "mutated"
        assert frozen["provider"] == "stepfun"


class TestProviderTaskRecoveryProjection:
    """The recovery path's projection must not rename the vendor either.

    A provider-task descriptor states the vendor as ``provider`` /
    ``provider_model`` -- the executor's own spelling -- so
    ``_declared_vendor_metadata`` normalizes it into the ``model_id`` key the
    projection understands before projecting.
    """

    @staticmethod
    def _resolution() -> ResolvedModelExecutionV2:
        return ResolvedModelExecutionV2(
            model_ref="tianpuyue:TemPolor-i3",
            provider_id="tianpuyue",
            provider_model_id="TemPolor-i3",
            capability="audio",
            provider_protocol="tianpuyue_audio",
            credential_revision=1,
            catalog_revision=3,
            adapter_id="tianpuyue-legacy-adapter-v1",
            transport_kind="pi_native_openai_compatible",
            capability_revision="catalog-3",
            adapter_revision="tianpuyue-legacy-adapter-v1",
            requested_parameter_fingerprint="sha256:" + "a" * 64,
            effective_parameter_fingerprint="sha256:" + "a" * 64,
        )

    @staticmethod
    def _outcome(
        descriptor: dict[str, object],
        *,
        provider: str | None = "stepfun_music",
        provider_task_id: str | None = "task_bgm",
    ) -> NodeExecutionOutcome:
        return NodeExecutionOutcome(
            media=type("M", (), {"metadata": descriptor})(),  # type: ignore[arg-type]
            provider=provider,
            provider_task_id=provider_task_id,
        )

    def test_a_routed_node_publishes_under_the_vendor_that_made_the_bytes(self) -> None:
        # The measured bgm shape: the catalog `audio` default is a TTS model, the
        # configured BGM provider is stepfun_music, and the descriptor names it.
        context = _bgm_context(self._resolution())
        descriptor = {
            "media_type": "audio",
            "provider": "stepfun_music",
            "provider_model": "stepaudio-3-music-preview",
        }
        projected = project_canvas_publication_metadata(
            context, None, _declared_vendor_metadata(self._outcome(descriptor))
        )
        assert projected["provider"] == "stepfun_music"
        assert projected["model_id"] == "stepaudio-3-music-preview"
        assert projected["provider_task_id"] == "task_bgm"

    def test_the_frozen_resolution_is_not_overwritten(self) -> None:
        # Precedence over the *vendor keys only*: model_resolution records what
        # the node asked for, and provider recovery asserts it still matches the
        # frozen submission intent.
        context = _bgm_context(self._resolution())
        descriptor = {
            "provider": "stepfun_music",
            "provider_model": "stepaudio-3-music-preview",
        }
        projected = project_canvas_publication_metadata(
            context, None, _declared_vendor_metadata(self._outcome(descriptor))
        )
        assert projected["model_resolution"]["provider_id"] == "tianpuyue"
        assert projected["model_resolution"]["provider_model_id"] == "TemPolor-i3"

    def test_both_publication_helpers_agree_on_the_vendor(self) -> None:
        # The defect was that they disagreed: whichever call site fired decided
        # whether the asset row told the truth about the vendor.
        context = _bgm_context(self._resolution())
        descriptor = {
            "provider": "stepfun_music",
            "provider_model": "stepaudio-3-music-preview",
        }
        merged = asset_publication_metadata(context, descriptor)
        projected = project_canvas_publication_metadata(
            context, None, _declared_vendor_metadata(self._outcome(descriptor))
        )
        assert merged["provider"] == projected["provider"] == "stepfun_music"

    def test_an_executor_that_says_nothing_leaves_the_projection_standing(self) -> None:
        # No vendor statement anywhere -- not in the descriptor, not in the
        # outcome -- must not blank the frozen catalog projection.
        context = _bgm_context(self._resolution())
        projected = project_canvas_publication_metadata(
            context,
            None,
            _declared_vendor_metadata(
                self._outcome({"media_type": "audio"}, provider=None, provider_task_id=None)
            ),
        )
        assert projected["provider"] == "tianpuyue"
        assert projected["model_id"] == "TemPolor-i3"
        assert "provider_task_id" not in projected

    def test_the_descriptor_outranks_the_outcome_provider(self) -> None:
        # Both name a vendor; the descriptor is the per-result statement, so it
        # wins over the task-level one recorded at submit time.
        context = _bgm_context(self._resolution())
        descriptor = {"provider": "tianpuyue", "provider_model": "TemPolor-i3"}
        projected = project_canvas_publication_metadata(
            context, None, _declared_vendor_metadata(self._outcome(descriptor))
        )
        assert projected["provider"] == "tianpuyue"
        assert projected["model_id"] == "TemPolor-i3"

    def test_the_normalized_payload_is_a_copy(self) -> None:
        descriptor = {"provider": "stepfun_music", "provider_model": "m-1"}
        normalized = _declared_vendor_metadata(self._outcome(descriptor))
        normalized["provider"] = "mutated"
        assert descriptor["provider"] == "stepfun_music"
        assert "model_id" not in descriptor
