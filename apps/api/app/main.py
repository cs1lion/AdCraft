import asyncio
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
import logging
import urllib.error
import urllib.request

from fastapi import FastAPI, Request, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from starlette.middleware.base import BaseHTTPMiddleware

from app.api.v1.router import api_router as api_v1_router
from app.api.internal.router import router as internal_agent_router
from app.api.v2.persistence import v2_persistence_exception_handler
from app.api.v2.router import api_router as api_v2_router
from app.api.v2.endpoints.agent_canvas import AgentCanvasRuntime, create_agent_canvas_runtime
from app.core.config import Settings, get_settings
from app.persistence.errors import V2PersistenceError
from app.schemas.v2_persistence import PersistenceBootstrapFailure
from app.services.persistence_bootstrap import PersistenceBootstrapService
from app.persistence.asset_library_repository import V2AssetLibraryRepository
from app.persistence.database import create_v2_database
from app.services.v2_asset_catalog import V2AssetCatalogService
from app.services.v2_asset_catalog_coordinator import V2AssetCatalogCoordinator
from app.services.agent_canvas_execution_state import AgentCanvasExecutionStateMachine
from app.services.agent_model_trace_sessions import (
    agent_model_trace_session_from_environment,
)
from app.services.agent_model_replay_policy import AgentModelReplayPolicyService

logger = logging.getLogger(__name__)


def _probe_agent_runtime(settings: Settings) -> str:
    """Probe the Node agent runtime once at startup ("reachable"/"unreachable"/"disabled").

    The runtime is a separate service that is easy to forget in local
    development; every chat turn then fails with agent_runtime_unavailable.  An
    early warning (and the health-endpoint field) makes the gap visible.
    """

    if settings.agent_runtime_mode == "fake":
        return "disabled"
    probe = urllib.request.Request(
        settings.agent_runtime_base_url.rstrip("/") + "/internal/v1/health",
        headers={
            "Authorization": "Bearer " + (settings.agent_runtime_internal_token or "")
        },
    )
    try:
        with urllib.request.urlopen(probe, timeout=2.0):
            return "reachable"
    except urllib.error.HTTPError:
        # Any HTTP response, including auth failures, proves the process is up.
        return "reachable"
    except Exception:
        return "unreachable"
AgentCanvasRuntimeFactory = Callable[[Settings], AgentCanvasRuntime]


def _new_agent_canvas_runtime(
    settings: Settings,
    runtime_factory: AgentCanvasRuntimeFactory | None,
) -> AgentCanvasRuntime:
    """Build a runtime for one background recovery cycle.

    Model policy is seeded once per startup by ``PersistenceBootstrapService``
    (``main.py:164``), before the recovery calls and poll tasks that follow it.
    The request path already relies on that same seeding -- see
    ``get_agent_canvas_runtime``, which passes ``bootstrap_model_policy=False``
    with the comment "HTTP requests consume the policy initialized by
    PersistenceBootstrapService."

    Re-running the full bootstrap on every poll tick rewrites every catalog row
    against the SQLite file, which is wasted work at best; under a OneDrive sync
    stall it turned a transient ``disk I/O error`` into a failed recovery cycle.
    A supplied test factory is honoured as-is, since tests may depend on the
    bootstrap running.
    """

    if runtime_factory is not None:
        return runtime_factory(settings)
    return create_agent_canvas_runtime(settings, bootstrap_model_policy=False)


class AccessTokenMiddleware(BaseHTTPMiddleware):
    """Optional API access token middleware.

    When settings.api_access_token is set, all requests to /api/v1 and /api/v2
    must include a valid Authorization: Bearer <token> header.
    Internal routes (/internal, /media, /docs, /openapi.json) are exempt.
    """

    def __init__(self, app, access_token: str | None):
        super().__init__(app)
        self.access_token = access_token

    async def dispatch(self, request: Request, call_next):
        # Skip auth if no token is configured (local development default)
        if not self.access_token:
            return await call_next(request)

        # Exempt CORS preflight requests (OPTIONS) - critical for browser clients
        if request.method == "OPTIONS":
            return await call_next(request)

        # Exempt paths: internal routes, media, docs, health, root
        path = request.url.path
        exempt_prefixes = ("/internal", "/media", "/docs", "/openapi.json", "/health")
        if path == "/" or any(path == prefix or path.startswith(prefix + "/") for prefix in exempt_prefixes):
            return await call_next(request)

        # Only enforce auth on API routes
        if not path.startswith("/api/"):
            return await call_next(request)

        # Check Authorization header
        auth_header = request.headers.get("Authorization", "")
        if not auth_header.startswith("Bearer "):
            raise HTTPException(status_code=401, detail="Missing or invalid Authorization header")

        token = auth_header[7:]  # Remove "Bearer " prefix
        if token != self.access_token:
            raise HTTPException(status_code=401, detail="Invalid access token")

        return await call_next(request)


def create_app(
    settings: Settings | None = None,
    *,
    agent_canvas_runtime_factory: AgentCanvasRuntimeFactory | None = None,
) -> FastAPI:
    """Construct the HTTP application without touching persistence or media data."""

    resolved_settings = settings or get_settings()
    application = FastAPI(
        title=resolved_settings.app_name,
        version=resolved_settings.app_version,
        lifespan=_lifespan(
            resolved_settings,
            runtime_factory=agent_canvas_runtime_factory,
        ),
    )
    trace_session = agent_model_trace_session_from_environment()
    if trace_session is not None:
        application.state.agent_model_trace_session = trace_session

    # CORS: use configured origins (defaults to localhost), "*" only if explicitly set
    cors_origins = list(resolved_settings.cors_allowed_origins)
    application.add_middleware(
        CORSMiddleware,
        allow_origins=cors_origins,
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=["ETag"],
    )

    # Optional API access token middleware
    application.add_middleware(AccessTokenMiddleware, access_token=resolved_settings.api_access_token)

    if settings is not None:
        application.dependency_overrides[get_settings] = lambda: resolved_settings
    application.mount(
        "/media",
        StaticFiles(directory=resolved_settings.media_data_dir, check_dir=False),
        name="media",
    )
    application.add_exception_handler(V2PersistenceError, v2_persistence_exception_handler)
    application.include_router(api_v1_router, prefix="/api/v1")
    application.include_router(api_v2_router, prefix="/api/v2")
    application.include_router(internal_agent_router)
    return application


def _lifespan(
    settings: Settings,
    *,
    runtime_factory: AgentCanvasRuntimeFactory | None = None,
) -> Callable[[FastAPI], AsyncIterator[None]]:
    """Build a lifespan hook that gates V2 recovery on verified persistence."""

    @asynccontextmanager
    async def lifespan(application: FastAPI) -> AsyncIterator[None]:
        try:
            application.state.v2_persistence_state = PersistenceBootstrapService(
                settings
            ).bootstrap()
            trace_session = getattr(application.state, "agent_model_trace_session", None)
            if getattr(trace_session, "mode", None) == "replay":
                bundle = getattr(trace_session, "replay_bundle", None)
                if bundle is None:
                    raise RuntimeError("acceptance_model_trace_invalid")
                application.state.agent_model_replay_policy = AgentModelReplayPolicyService(
                    settings
                ).prepare(bundle)
        except V2PersistenceError as error:
            application.state.v2_persistence_state = PersistenceBootstrapFailure(
                code=error.code,
                message=str(error),
                stage=error.stage,
            )
            logger.error(
                "V2 persistence bootstrap failed: code=%s stage=%s",
                error.code,
                error.stage,
            )
            yield
            return

        coordinator = _create_asset_catalog_coordinator(settings)
        application.state.v2_asset_catalog_coordinator = coordinator
        coordinator.ensure_indexed()
        application.state.agent_runtime_status = _probe_agent_runtime(settings)
        if application.state.agent_runtime_status == "unreachable":
            logger.warning(
                "Agent runtime is unreachable at %s; chat turns will fail until "
                "it is started (npm start in apps/api/agent).",
                settings.agent_runtime_base_url,
            )
        try:
            recovery_kwargs = (
                {"runtime_factory": runtime_factory} if runtime_factory is not None else {}
            )
            _recover_agent_canvas_chat_turns(settings, **recovery_kwargs)
            _recover_agent_canvas_continuations(settings, **recovery_kwargs)
            _recover_agent_canvas_executions(settings, **recovery_kwargs)
            _recover_agent_canvas_editing_exports(settings, **recovery_kwargs)
            provider_poll_stop = asyncio.Event()
            provider_poll_task = asyncio.create_task(
                _poll_agent_canvas_provider_tasks(
                    settings,
                    provider_poll_stop,
                    **recovery_kwargs,
                )
            )
            continuation_poll_stop = asyncio.Event()
            continuation_poll_task = asyncio.create_task(
                _poll_agent_canvas_continuations(
                    settings,
                    continuation_poll_stop,
                    **recovery_kwargs,
                )
            )
            guided_media_resume_poll_stop = asyncio.Event()
            guided_media_resume_poll_task = asyncio.create_task(
                _poll_agent_canvas_guided_media_resumes(
                    settings,
                    guided_media_resume_poll_stop,
                    **recovery_kwargs,
                )
            )
            try:
                yield
            finally:
                provider_poll_stop.set()
                continuation_poll_stop.set()
                guided_media_resume_poll_stop.set()
                await provider_poll_task
                await continuation_poll_task
                await guided_media_resume_poll_task
        finally:
            coordinator.shutdown()

    return lifespan


def _recover_agent_canvas_chat_turns(
    settings: Settings,
    *,
    runtime_factory: AgentCanvasRuntimeFactory | None = None,
) -> None:
    """Resume durable queued Agent Canvas turns after process restart."""

    runtime = _new_agent_canvas_runtime(settings, runtime_factory)
    try:
        runtime.commands.recover_applying_plans()
        runtime.conversations.recover_pending_turns()
    finally:
        runtime.database.dispose()


def _recover_agent_canvas_executions(
    settings: Settings,
    *,
    runtime_factory: AgentCanvasRuntimeFactory | None = None,
) -> None:
    """Resume persisted non-terminal Agent Canvas scheduler memberships."""

    runtime = _new_agent_canvas_runtime(settings, runtime_factory)
    stale_timeout = timedelta(minutes=30)
    now = datetime.now(timezone.utc)
    try:
        runtime.provider_recovery.recover_due_tasks()
        runtime.post_ready_effects.run_once()
        state_machine = AgentCanvasExecutionStateMachine()
        for execution in runtime.runtime_repository.list_active_executions():
            state_machine.reconcile(
                runtime.runtime_repository,
                execution.execution_id,
                now=execution.updated_at,
                workflows=runtime.workflows,
            )
        for execution in runtime.runtime_repository.list_active_executions():
            # Cancel stale executions that have not been updated within the timeout window.
            # This handles the case where the backend was restarted while an execution
            # was running, leaving it in a stuck "running" state with no active worker.
            if execution.status in {"running", "waiting"} and execution.updated_at < now - stale_timeout:
                logger.warning(
                    "Cancelling stale execution %s (status=%s, updated_at=%s, age=%s)",
                    execution.execution_id,
                    execution.status,
                    execution.updated_at.isoformat(),
                    now - execution.updated_at,
                )
                try:
                    runtime.scheduler.cancel(
                        execution.execution_id,
                        reason="Stale execution cancelled during startup recovery (no heartbeat for 30+ minutes)",
                    )
                except Exception:
                    logger.exception("Failed to cancel stale execution %s", execution.execution_id)
            else:
                runtime.scheduler.resume(execution.execution_id)
    finally:
        runtime.database.dispose()


async def _poll_agent_canvas_continuations(
    settings: Settings,
    stop: asyncio.Event,
    *,
    runtime_factory: AgentCanvasRuntimeFactory | None = None,
) -> None:
    interval = max(1, settings.v2_provider_task_poll_interval_seconds)
    while not stop.is_set():
        try:
            await asyncio.wait_for(stop.wait(), timeout=interval)
            continue
        except asyncio.TimeoutError:
            pass
        try:
            if runtime_factory is None:
                await asyncio.to_thread(_recover_agent_canvas_continuations, settings)
            else:
                await asyncio.to_thread(
                    _recover_agent_canvas_continuations,
                    settings,
                    runtime_factory=runtime_factory,
                )
        except Exception:  # noqa: BLE001 - later poll cycles must remain available.
            logger.exception("Agent Canvas continuation polling cycle failed.")


def _recover_agent_canvas_continuations(
    settings: Settings,
    *,
    runtime_factory: AgentCanvasRuntimeFactory | None = None,
) -> None:
    runtime = _new_agent_canvas_runtime(settings, runtime_factory)
    try:
        prompt_preparation_worker = getattr(runtime, "prompt_preparation_worker", None)
        if prompt_preparation_worker is not None:
            prompt_preparation_worker.run_once()
        runtime.continuation_worker.run_once()
        runtime.auto_run_dispatcher.run_once()
    finally:
        runtime.database.dispose()


async def _poll_agent_canvas_guided_media_resumes(
    settings: Settings,
    stop: asyncio.Event,
    *,
    runtime_factory: AgentCanvasRuntimeFactory | None = None,
) -> None:
    """Recover durable media-confirmation resumes without delaying startup."""

    interval = max(1, settings.v2_provider_task_poll_interval_seconds)
    while not stop.is_set():
        try:
            if runtime_factory is None:
                await asyncio.to_thread(_recover_agent_canvas_guided_media_resumes, settings)
            else:
                await asyncio.to_thread(
                    _recover_agent_canvas_guided_media_resumes,
                    settings,
                    runtime_factory=runtime_factory,
                )
        except Exception:  # noqa: BLE001 - later poll cycles must remain available.
            logger.exception("Agent Canvas guided media resume polling cycle failed.")
        try:
            await asyncio.wait_for(stop.wait(), timeout=interval)
        except asyncio.TimeoutError:
            continue


def _recover_agent_canvas_guided_media_resumes(
    settings: Settings,
    *,
    runtime_factory: AgentCanvasRuntimeFactory | None = None,
) -> None:
    runtime = _new_agent_canvas_runtime(settings, runtime_factory)
    try:
        runtime.guided_media_resume_worker.run_once()
    finally:
        runtime.database.dispose()


async def _poll_agent_canvas_provider_tasks(
    settings: Settings,
    stop: asyncio.Event,
    *,
    runtime_factory: AgentCanvasRuntimeFactory | None = None,
) -> None:
    interval = max(1, settings.v2_provider_task_poll_interval_seconds)
    while not stop.is_set():
        try:
            await asyncio.wait_for(stop.wait(), timeout=interval)
            continue
        except asyncio.TimeoutError:
            pass
        try:
            if runtime_factory is None:
                await asyncio.to_thread(_recover_agent_canvas_provider_tasks, settings)
            else:
                await asyncio.to_thread(
                    _recover_agent_canvas_provider_tasks,
                    settings,
                    runtime_factory=runtime_factory,
                )
        except Exception:  # noqa: BLE001 - later poll cycles must remain available.
            logger.exception("Agent Canvas provider polling cycle failed.")


def _recover_agent_canvas_provider_tasks(
    settings: Settings,
    *,
    runtime_factory: AgentCanvasRuntimeFactory | None = None,
) -> None:
    runtime = _new_agent_canvas_runtime(settings, runtime_factory)
    try:
        runtime.provider_recovery.recover_due_tasks()
        runtime.post_ready_effects.run_once()
        for execution in runtime.runtime_repository.list_active_executions():
            runtime.scheduler.resume(execution.execution_id)
    finally:
        runtime.database.dispose()


def _recover_agent_canvas_editing_exports(
    settings: Settings,
    *,
    runtime_factory: AgentCanvasRuntimeFactory | None = None,
) -> None:
    """Resume persisted non-terminal Agent Canvas Editing exports."""

    runtime = _new_agent_canvas_runtime(settings, runtime_factory)
    try:
        runtime.editing_exports.resume_active()
    finally:
        runtime.database.dispose()


def _create_asset_catalog_coordinator(settings: Settings) -> V2AssetCatalogCoordinator:
    """Create the local-catalog coordinator once for the application lifespan."""

    return V2AssetCatalogCoordinator(
        V2AssetCatalogService(
            data_dir=settings.media_data_dir,
            repository=V2AssetLibraryRepository(create_v2_database(settings.media_data_dir)),
            catalog_root=settings.v2_recommended_catalog_root,
        )
    )


app = create_app()
