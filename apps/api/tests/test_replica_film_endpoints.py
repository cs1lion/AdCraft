"""Regression contracts: complete film replies and assembly projection; no provider calls."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace as NS
from unittest.mock import Mock

import pytest
from fastapi import BackgroundTasks

from app.api.v1.endpoints import replica
from app.schemas.agent_canvas_ad_media import ReplicaBlueprintContentV2
from app.services.replica.film import plan_film_shots

pytestmark = pytest.mark.integration


def blueprint(count):
    return ReplicaBlueprintContentV2(
        shots=[
            {
                "index": i,
                "start_seconds": (i - 1) * 5,
                "end_seconds": i * 5,
                "subject_action": f"action {i}",
            }
            for i in range(1, count + 1)
        ]
    )


@pytest.mark.parametrize("old_count,new_count", [(0, 2), (2, 2), (2, 3), (3, 1)])
def test_generate_film_returns_complete_current_plan(monkeypatch, old_count, new_count):
    current_blueprint = blueprint(new_count)
    root = NS(
        node_id="replica",
        node_type="replica",
        structured_content=current_blueprint.model_dump(),
        position=NS(x=0, y=0),
    )
    plans = plan_film_shots(blueprint(old_count))
    nodes = [root] + [
        NS(
            node_id=f"old-{i}",
            node_type="video",
            title=p.title,
            parameters={"replica_node_id": "replica"},
            generation_prompt=p.generation_prompt,
            structured_content=p.segment,
            status="ready" if i == 1 else "working",
            output_asset_id=f"asset-{i}",
            latest_attempt=NS(status="succeeded"),
            model_ref=None,
        )
        for i, p in enumerate(plans, 1)
    ]
    workflow = NS(nodes=nodes, revision=1)
    repository = NS(get_workflow=lambda _id: workflow, get_node=lambda *_: root)

    def create(_wf, request, **_kw):
        node = NS(node_id=f"new-{len(nodes)}", title=request.title, model_ref=None)
        nodes.append(node)
        workflow.revision += 1
        return node

    service = NS(create=create, patch=Mock())
    monkeypatch.setattr(replica, "_canvas_node_service", lambda: (service, repository))
    monkeypatch.setattr("app.core.config.get_settings", lambda: NS())
    start = Mock(return_value=NS(execution_id="execution"))
    runtime = NS(
        run_service=NS(start_or_extend=start),
        accepted_background=NS(run=Mock()),
        scheduler=NS(resume=Mock()),
    )
    monkeypatch.setattr(
        "app.api.v2.endpoints.agent_canvas.create_agent_canvas_runtime", lambda *_a, **_k: runtime
    )
    result = asyncio.run(
        replica.generate_replica_film(
            replica.FilmGenerateRequest(workflow_id="wf", replica_node_id="replica"),
            BackgroundTasks(),
        )
    )
    assert [s.shot_index for s in result.shots] == list(range(1, new_count + 1))
    assert len({s.node_id for s in result.shots}) == new_count
    assert [s.title for s in result.shots] == [p.title for p in plan_film_shots(current_blueprint)]
    if old_count:
        assert result.shots[0].node_id == "old-1"
    if new_count <= old_count:
        assert not start.called  # Ready + working still returned, but neither rerun.
    else:
        assert start.called
        run_request = start.call_args.args[1]
        assert set(run_request.node_ids).issubset({s.node_id for s in result.shots})
        assert len(run_request.node_ids) == new_count - old_count
