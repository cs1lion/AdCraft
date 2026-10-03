"""Bridge projections stay archived rather than appearing as user projects."""

from types import SimpleNamespace as NS
from unittest.mock import Mock

import pytest

from app.services.creation import canvas_render_bridge as bridge

pytestmark = pytest.mark.integration


def test_bridge_uses_supported_project_update_api(monkeypatch):
    create = Mock()
    runtime = NS(database=NS(), service=NS(create_planned_workflow=create))
    monkeypatch.setattr(
        "app.services.v2_workflow_authoring.create_workflow_authoring_runtime", lambda _: runtime
    )
    monkeypatch.setattr(bridge, "_already_bridged", lambda *_: False)
    update = Mock()
    monkeypatch.setattr(
        "app.persistence.project_repository.ProjectRepository", lambda _: NS(update=update)
    )
    bridge.bridge_canvas_workflow(NS(media_data_dir="unused"), "adwf_v2_demo", None, "film", [])
    update.assert_called_once_with(
        "proj_film_demo", expected_version=1, changes={"status": "archived"}
    )
    create.assert_called_once()
