from pathlib import Path

import pytest

from app.core.config import Settings
from app.schemas.front_desk import FrontDeskChatRequest, FrontDeskChatResponse
from app.services.front_desk import FrontDeskError, FrontDeskService
from app.services.v2_structured_generation_runtime import StructuredGenerationRuntimeError
from app.services.workflow_v2 import WorkflowV2Error, WorkflowV2Service


def _settings(data_dir: Path) -> Settings:
    return Settings(agent_runtime_mode="real", media_data_dir=data_dir)


def test_front_desk_maps_structured_runtime_unavailability_without_internal_details(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = FrontDeskService(_settings(tmp_path / "data"))

    def fail_run(*args: object, **kwargs: object) -> None:
        del args, kwargs
        raise StructuredGenerationRuntimeError(
            "structured_generation_unavailable",
            "agent_skill_digest_mismatch at /private/skills/example/SKILL.md",
        )

    monkeypatch.setattr(service._structured_runtime, "run", fail_run)

    with pytest.raises(FrontDeskError) as exc_info:
        service.chat(
            FrontDeskChatRequest(
                message="Create a fictional phone advertisement.",
                workflow_schema_version=2,
            )
        )

    assert exc_info.value.code == "agent_runtime_unavailable"
    assert exc_info.value.retryable is True
    assert str(exc_info.value) == "Agent runtime is temporarily unavailable."
    assert "digest" not in str(exc_info.value)
    assert "SKILL.md" not in str(exc_info.value)


def test_workflow_service_preserves_typed_front_desk_failure_without_persistence(
    tmp_path: Path,
) -> None:
    data_dir = tmp_path / "data"
    service = WorkflowV2Service(_settings(data_dir))

    class UnavailableFrontDesk:
        def chat(self, request: FrontDeskChatRequest) -> FrontDeskChatResponse:
            del request
            raise FrontDeskError(
                code="agent_runtime_unavailable",
                message="Agent runtime is temporarily unavailable.",
                retryable=True,
            )

    with pytest.raises(WorkflowV2Error) as exc_info:
        service.plan_from_chat(
            FrontDeskChatRequest(
                message="Create a fictional phone advertisement.",
                workflow_schema_version=2,
            ),
            front_desk_service=UnavailableFrontDesk(),
        )

    assert exc_info.value.code == "agent_runtime_unavailable"
    assert str(exc_info.value) == "Agent runtime is temporarily unavailable."
    assert exc_info.value.details == {"retryable": True}
    assert not (data_dir / "v2" / "workflows").exists()
    assert not (data_dir / "v2" / "runs").exists()
    assert not (data_dir / "assets").exists()


def test_successful_front_desk_conversation_contract_is_unchanged(tmp_path: Path) -> None:
    service = WorkflowV2Service(_settings(tmp_path / "data"))

    class ConversationFrontDesk:
        def chat(self, request: FrontDeskChatRequest) -> FrontDeskChatResponse:
            del request
            return FrontDeskChatResponse(
                intent="conversation",
                reply="Please provide the product details.",
            )

    response = service.plan_from_chat(
        FrontDeskChatRequest(
            message="Hello.",
            workflow_schema_version=2,
        ),
        front_desk_service=ConversationFrontDesk(),
    )

    assert response.workflow is None
    assert response.front_desk.intent == "conversation"
    assert response.front_desk.reply == "Please provide the product details."
