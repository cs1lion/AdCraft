"""Startup seeding for trusted provider catalog entries and installation defaults."""

from __future__ import annotations

from dataclasses import dataclass
from threading import Lock
from urllib.parse import urlsplit
import hashlib

from app.core.config import PROJECT_ROOT, Settings
from app.persistence.provider_model_repository import ProviderModelRepository
from app.services.provider_credentials import (
    DotenvCredentialStore,
    ProviderConnectionService,
    ProviderCredentialRegistry,
)
from app.services.provider_model_catalog import ProviderModelCatalogService


_BOOTSTRAP_LOCK = Lock()
_ARK_MINI_TEXT_MODEL_REF = "volcengine_ark:doubao-seed-2-0-mini-260428"
_ARK_PRO_TEXT_MODEL_REF = "volcengine_ark:doubao-seed-2-1-pro-260628"
_STEPFUN_IMAGE_MODEL_REF = "stepfun:step-image-edit-2"
_AGNES_IMAGE_MODEL_REF = "agnes:agnes-image-2.5-flash"
# Image refs that can no longer be reached: the four Seedream rows answer 404 on
# the configured image gateway, and ``volcengine_ark:step-image-edit-2`` is a
# StepFun model that used to be filed under the Volcengine provider id.
_STALE_IMAGE_MODEL_REFS = frozenset(
    {
        "volcengine_ark:step-image-edit-2",
        "volcengine_ark:doubao-seedream-4-0-250828",
        "volcengine_ark:doubao-seedream-4-5-251128",
        "volcengine_ark:doubao-seedream-5-0-lite-260128",
        "volcengine_ark:doubao-seedream-5-0-pro-260628",
    }
)
#: The StepFun image refs, which are what an installation's ``image`` default
#: holds before it is pointed at Agnes.  Listed separately from
#: ``_STALE_IMAGE_MODEL_REFS`` because these models are *not* broken -- they are
#: simply not the one the endpoint is configured against, and a default pointing
#: at them would keep sending nodes to a vendor the operator routed away from.
_STEPFUN_IMAGE_MODEL_REFS = frozenset(
    {
        "stepfun:step-image-edit-2",
        "stepfun:step-2x-large",
    }
)


def _image_endpoint_provider_id(endpoint: str) -> str:
    """The catalog provider id that owns ``IMAGE_GENERATION_ENDPOINT``.

    The image capability has one setting pair but two possible vendors, and the
    connection row the catalog reads availability from has to be written under
    the vendor the request will actually reach.
    """

    lowered = (endpoint or "").casefold()
    if "agnes-ai.cn" in lowered:
        return "agnes"
    if "stepfun" in lowered:
        return "stepfun"
    return "volcengine_ark"


@dataclass(frozen=True)
class ProviderModelBootstrapResult:
    seeded_providers: tuple[str, ...]
    seeded_defaults: tuple[str, ...]


class ProviderModelBootstrapService:
    """Seed missing model policy without replacing existing catalog or defaults."""

    def __init__(self, settings: Settings, repository: ProviderModelRepository) -> None:
        self._settings = settings
        self._repository = repository

    def bootstrap(self, *, now: str) -> ProviderModelBootstrapResult:
        with _BOOTSTRAP_LOCK:
            return self._bootstrap(now=now)

    def _bootstrap(self, *, now: str) -> ProviderModelBootstrapResult:
        catalog = ProviderModelCatalogService(self._repository)
        catalog.ensure_no_retired_defaults()
        registry = ProviderCredentialRegistry()
        connection_service = ProviderConnectionService(
            registry=registry,
            dotenv_store=DotenvCredentialStore(
                PROJECT_ROOT,
                allowed_fields={
                    field
                    for provider_id in registry.provider_ids
                    for binding in registry.get(provider_id).bindings.values()
                    for field in (
                        binding.dotenv_field,
                        binding.endpoint_dotenv_field,
                    )
                    if field is not None
                },
            ),
            metadata_repository=self._repository,
            settings_loader=lambda: self._settings,
        )
        connection_service.synchronize_metadata(updated_at=now)
        self._synchronize_configured_image_capability(updated_at=now)
        catalog.reconcile_retired_models(now=now)
        seeded_providers: list[str] = []
        for provider_id in (
            "siliconflow",
            "volcengine_ark",
            "tianpuyue",
            "openrouter",
            "minimax",
            "fake",
            # Registered late: stepfun is where the only reachable image models
            # live, and it was missing from this list entirely -- so its
            # manifests were never reconciled and no stepfun image row existed.
            "stepfun",
            # Agnes is the fallback image vendor (see the manifest comment in
            # ``provider_model_catalog``).  Same omission, same consequence:
            # without this tuple entry its manifests never reach the database
            # and no node can select the model that actually answers.
            "agnes",
        ):
            had_models = bool(self._repository.list_models(provider_id=provider_id))
            catalog.reconcile_trusted_models(provider_id, now=now)
            if not had_models:
                seeded_providers.append(provider_id)

        existing = catalog.get_default_records()
        candidates = {
            key: model_ref
            for key, model_ref in self._recognized_defaults().items()
            if key not in existing
        }
        valid_candidates: dict[str, str] = {}
        for key, model_ref in candidates.items():
            try:
                model = self._repository.get_model(model_ref)
            except ValueError:
                continue
            if model.availability != "available":
                continue
            valid_candidates[key] = model_ref
        migrated_defaults: dict[str, str] = {}
        try:
            ark_pro = catalog.get_model(_ARK_PRO_TEXT_MODEL_REF)
        except ValueError:
            ark_pro = None
        if ark_pro is not None and ark_pro.availability == "available":
            migrated_defaults = {
                key: _ARK_PRO_TEXT_MODEL_REF
                for key in ("agent", "text")
                if existing.get(key) is not None
                and existing[key].model_ref == _ARK_MINI_TEXT_MODEL_REF
            }
        # ``candidates`` only covers keys that are absent, so a stale image
        # default would otherwise survive forever.  Move it once the
        # replacement is actually available, mirroring the text migration above.
        #
        # Two separate migrations, because "stale" means two different things
        # here: the retired Seedream rows are unreachable, while the StepFun rows
        # are reachable but are not the vendor ``IMAGE_GENERATION_ENDPOINT``
        # points at any more.  Leaving the second case alone would keep sending
        # every image node to a provider the operator routed away from, with no
        # visible error -- the node would simply fail against the old vendor.
        image_default = existing.get("image")
        if image_default is not None:
            replacement: str | None = None
            if image_default.model_ref in _STALE_IMAGE_MODEL_REFS and self._stepfun_image_is_selectable(
                catalog
            ):
                replacement = _STEPFUN_IMAGE_MODEL_REF
            elif image_default.model_ref in _STEPFUN_IMAGE_MODEL_REFS and self._agnes_image_is_selectable(
                catalog
            ):
                replacement = _AGNES_IMAGE_MODEL_REF
            if replacement is not None:
                migrated_defaults = {**migrated_defaults, "image": replacement}
        default_updates = {**migrated_defaults, **valid_candidates}
        if default_updates:
            catalog.set_defaults(default_updates, now=now)
        return ProviderModelBootstrapResult(
            seeded_providers=tuple(seeded_providers),
            seeded_defaults=tuple(valid_candidates),
        )

    def _synchronize_configured_image_capability(self, *, updated_at: str) -> None:
        """Record image readiness for the provider the endpoint actually points at.

        ``ProviderConnectionService`` only writes the providers listed in
        ``ProviderCredentialRegistry``, which is Volcengine-shaped
        (llm/image/video) and has neither a stepfun nor an agnes definition at
        all -- so nothing ever writes an ``image`` entry for either, and
        ``_repository_capability_available`` then reports their image models as
        ``unavailable`` with ``provider_credentials_missing`` even though
        ``IMAGE_GENERATION_ENDPOINT`` is set and the gateway is demonstrably
        reachable.

        Mirror what ``synchronize_metadata`` does for registry providers, but
        only for the one capability the configured image endpoint actually owns,
        and only when the projection differs -- ``upsert_connection`` bumps
        ``credential_revision`` on every call, so writing unconditionally would
        spin the counter on every boot.

        The provider is derived from the endpoint host rather than hardcoded,
        because ``IMAGE_GENERATION_ENDPOINT`` has pointed at two different
        vendors and the row has to follow it: a stale ``stepfun`` row would keep
        reporting ``configured`` after a switch to Agnes, and no row would exist
        for Agnes at all.
        """

        settings = self._settings
        api_key = (settings.image_generation_credential or "").strip()
        endpoint = (settings.image_generation_endpoint or "").strip()
        provider_id = _image_endpoint_provider_id(endpoint)
        try:
            current = self._repository.get_connection(provider_id)
        except ValueError:
            current = None
        status = dict(current.credential_status) if current is not None else {}
        audio_status = status.get("audio")

        def _endpoint_metadata(value: str) -> dict[str, str | None] | None:
            if not value:
                return None
            try:
                parsed = urlsplit(value)
            except ValueError:
                return None
            return {
                "scheme": parsed.scheme or None,
                "host": parsed.hostname,
                "path": parsed.path or None,
                "fingerprint": hashlib.sha256(value.encode("utf-8")).hexdigest(),
            }

        image_status: dict[str, object] = {
            "configured": bool(api_key and endpoint),
            "endpoint": _endpoint_metadata(endpoint),
            # No secret material ever lands here: only a presence digest, and
            # only when a key is actually configured.
            "fingerprint": (
                hashlib.sha256(api_key.encode("utf-8")).hexdigest() if api_key else None
            ),
            "source": "project_dotenv",
            "test_capability": "minimal_request",
        }
        if audio_status is not None:
            status["audio"] = audio_status
        status["image"] = image_status
        connection_state = "configured" if image_status["configured"] else "unconfigured"
        if (
            current is not None
            and current.connection_state == connection_state
            and current.credential_status == status
        ):
            return
        self._repository.upsert_connection(
            provider_id=provider_id,
            connection_state=connection_state,
            credential_status=status,
            updated_at=updated_at,
        )

    def _stepfun_image_is_selectable(self, catalog: ProviderModelCatalogService) -> bool:
        """True when the StepFun image default exists in the catalog as available."""

        try:
            model = catalog.get_model(_STEPFUN_IMAGE_MODEL_REF)
        except ValueError:
            return False
        return model.availability == "available"

    def _agnes_image_is_selectable(self, catalog: ProviderModelCatalogService) -> bool:
        """True when the Agnes image default exists in the catalog as available.

        Gated on the *configured endpoint* as well as availability: an
        installation whose ``IMAGE_GENERATION_ENDPOINT`` still points at StepFun
        must not be migrated to Agnes just because Agnes happens to be reachable
        with the video key.  The vendor choice belongs to the operator's
        configuration, and this migration only follows it.
        """

        if "agnes-ai.cn" not in (self._settings.image_generation_endpoint or "").casefold():
            return False
        try:
            model = catalog.get_model(_AGNES_IMAGE_MODEL_REF)
        except ValueError:
            return False
        return model.availability == "available"

    def _recognized_defaults(self) -> dict[str, str]:
        text_ref = "fake:deterministic-text"
        if self._settings.agent_runtime_mode != "fake":
            text_ref = (
                "siliconflow:zai-org/GLM-5.2"
                if self._settings.siliconflow_api_key
                else _ARK_PRO_TEXT_MODEL_REF
            )
        if self._settings.media_mode == "mock":
            return {
                "agent": text_ref,
                "text": text_ref,
                "image": "fake:deterministic-image",
                "video": "fake:deterministic-video",
                "audio": "fake:deterministic-audio",
            }
        return {
            "agent": text_ref,
            "text": text_ref,
            "image": self._configured_image_default_ref(),
            "video": "volcengine_ark:doubao-seedance-2-0-fast-260128",
            "audio": "tianpuyue:TemPolor-i3",
        }

    def _configured_image_default_ref(self) -> str:
        """The image ref that matches ``IMAGE_GENERATION_MODEL``.

        Seeding the StepFun ref unconditionally is what would leave a fresh
        Agnes deployment with an image default pointing at the vendor its own
        endpoint does not use, so the configured model decides.
        """

        model = (self._settings.image_generation_model or "").strip()
        if model == "agnes-image-2.5-flash":
            return _AGNES_IMAGE_MODEL_REF
        return _STEPFUN_IMAGE_MODEL_REF
