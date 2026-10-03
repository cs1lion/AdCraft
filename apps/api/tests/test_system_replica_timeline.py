"""System timeline saves retain version guards and never overwrite user edits."""

from types import SimpleNamespace as NS
from unittest.mock import Mock

import pytest

from app.schemas.workflow_v2 import WorkflowV2Timeline
from app.services.v2_final_composition_timeline import (
    V2FinalCompositionTimelineService,
    V2FinalCompositionTimelineError,
)

pytestmark = pytest.mark.integration


def service(current):
    instance = object.__new__(V2FinalCompositionTimelineService)
    instance._load_workflow = Mock(return_value=NS())
    instance._final_item_and_slot = Mock(return_value=(NS(), NS()))
    instance._load_timeline = Mock(return_value=current)
    instance._write_timeline = Mock()
    instance._validate_timeline = Mock()
    instance._source_selection_hash = Mock(return_value="hash")
    instance._project_compatibility_timeline = Mock()
    instance._commit_semantic_workflow = Mock(return_value=NS())
    instance._emit_timeline_updated = Mock()
    instance._runtime_snapshot = Mock(return_value=NS(model_dump=lambda **_: {}))
    return instance


def test_user_edited_timeline_is_preserved_before_any_write():
    current = WorkflowV2Timeline(timeline_id="t", version=3, metadata={"edit_mode": "user_edited"})
    instance = service(current)
    with pytest.raises(V2FinalCompositionTimelineError):
        instance.save_system_timeline("wf", current, expected_version=3)
    instance._write_timeline.assert_not_called()


def test_stale_version_is_rejected_and_system_save_is_not_user_edit():
    current = WorkflowV2Timeline(timeline_id="t", version=3)
    instance = service(current)
    with pytest.raises(V2FinalCompositionTimelineError):
        instance.save_system_timeline("wf", current, expected_version=2)
    instance._write_timeline.assert_not_called()
    result = instance.save_system_timeline("wf", current, expected_version=3)
    assert result.timeline.version == 4
    assert result.timeline.metadata["edit_mode"] == "system_default"
    assert result.timeline.metadata["source_selection_hash"] == "hash"


def test_replica_plan_does_not_get_default_rebuilt_on_render_reconcile():
    from test_replica_composition_plan import plan

    incoming = plan().timeline
    incoming.metadata["source_selection_hash"] = "same"
    instance = object.__new__(V2FinalCompositionTimelineService)
    assert not instance._system_default_needs_reconcile(incoming, "same")
    # Mutation reproduces the saved-version invalidation found by real browser export.
    incoming.metadata.pop("resolution_source")
    assert instance._system_default_needs_reconcile(incoming, "same")
