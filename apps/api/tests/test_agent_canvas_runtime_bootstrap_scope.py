"""Background recovery cycles must not re-bootstrap model policy.

Every ``_recover_agent_canvas_*`` helper used to build its runtime with the
default ``bootstrap_model_policy=True`` -- a full provider-model catalog
reconciliation (credential metadata sync, retired-model reconciliation, and one
``UPDATE`` per catalog row against the SQLite file) on **every poll tick**,
forever.  ``PersistenceBootstrapService`` already seeds the policy at startup,
*before* the recovery calls and poll tasks that consume it, and the request path
already relies on that seeding (``get_agent_canvas_runtime`` passes
``bootstrap_model_policy=False``), so the repeat work buys nothing -- and under a
OneDrive sync stall it turned a transient ``disk I/O error`` into a failed
recovery cycle.

The one-positional-argument shape of ``AgentCanvasRuntimeFactory`` is what makes
this awkward: a keyword cannot be threaded through
``(runtime_factory or create_agent_canvas_runtime)(settings)`` without breaking
every test-supplied factory.  So the branching lives in
``_new_agent_canvas_runtime``, and both halves are pinned here.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.core.config import Settings
from app.main import _new_agent_canvas_runtime


def _settings(tmp_path: Path) -> Settings:
    return Settings(agent_runtime_mode="fake", media_data_dir=tmp_path / "data")


class TestBackgroundRuntimeSkipsPolicyBootstrap:
    def test_the_default_background_runtime_opts_out_of_the_bootstrap(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        # The regression: startup already seeded the policy, so a poll tick
        # re-running the catalog reconciliation is pure repeated writes.
        seen: list[dict[str, object]] = []

        def fake_factory(settings: Settings, **kwargs: object) -> object:
            seen.append(dict(kwargs))
            return object()

        monkeypatch.setattr("app.main.create_agent_canvas_runtime", fake_factory)
        _new_agent_canvas_runtime(_settings(tmp_path), None)
        assert seen == [{"bootstrap_model_policy": False}]

    def test_a_supplied_factory_still_receives_the_settings_alone(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        # ``AgentCanvasRuntimeFactory`` takes a single positional argument, so a
        # one-arg test factory must keep working.  If someone "simplifies" the
        # helper back into ``(runtime_factory or default)(settings,
        # bootstrap_model_policy=False)``, every such factory breaks -- this is
        # the constraint that forced the branch to exist.
        settings = _settings(tmp_path)
        received: list[Settings] = []
        sentinel = object()

        def factory(only: Settings) -> object:
            received.append(only)
            return sentinel

        def unused_default(*args: object, **kwargs: object) -> object:
            raise AssertionError("the default factory must not be consulted")

        monkeypatch.setattr("app.main.create_agent_canvas_runtime", unused_default)
        assert _new_agent_canvas_runtime(settings, factory) is sentinel
        assert received == [settings]
