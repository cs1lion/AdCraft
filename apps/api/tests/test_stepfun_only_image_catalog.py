"""The image catalog, and the two vendors its one setting pair can point at.

Five claims are pinned here, each of which was violated on 2026-09-20:

1. The only image models this deployment can reach are StepFun's
   ``step-image-edit-2`` / ``step-2x-large`` and Agnes'
   ``agnes-image-2.5-flash``.  The four ``doubao-seedream-*`` rows must be
   retired, so they can no longer be advertised as ``available``.
2. ``stepfun`` and ``agnes`` are discoverable providers.  Both were missing
   from the catalog adapter tuple and the bootstrap reconcile tuple, so their
   image manifests could never reach the database at all.
3. A stale image default is migrated forward rather than left pointing at an
   unreachable model.
4. The image capability has one setting pair but two possible vendors, so the
   connection row the catalog reads availability from has to be written under
   whichever vendor ``IMAGE_GENERATION_ENDPOINT`` points at, and the default
   has to follow the operator's endpoint rather than whichever vendor happens
   to be reachable.
5. The serializer keeps the wire shape each vendor expects, and the two are
   not the same shape.
"""

from __future__ import annotations

import dataclasses
from pathlib import Path

import pytest

from app.core.config import Settings
from app.persistence.database import create_v2_database
from app.persistence.provider_model_repository import ProviderModelRepository
from app.persistence.schema import upgrade_v2_schema
from app.services.agnes_image_contract import is_agnes_image_model
from app.services.provider_model_bootstrap import (
    _AGNES_IMAGE_MODEL_REF,
    _STEPFUN_IMAGE_MODEL_REF,
    _STALE_IMAGE_MODEL_REFS,
    ProviderModelBootstrapService,
    _image_endpoint_provider_id,
)
from app.services.provider_model_catalog import (
    _RETIRED_MODEL_REFS,
    _TRUSTED_MANIFESTS,
    ProviderModelCatalogService,
)
from app.services.stepfun_image_contract import is_stepfun_image_model
from app.tools.volcengine_image_generations import (
    _EXECUTABLE_IMAGE_MODEL_IDS,
    _STEPFUN_IMAGE_MODEL_IDS,
    serialize_volcengine_image_generation_request,
)

RETIRED_DOUBAO_IMAGE_REFS = (
    "volcengine_ark:doubao-seedream-4-0-250828",
    "volcengine_ark:doubao-seedream-4-5-251128",
    "volcengine_ark:doubao-seedream-5-0-lite-260128",
    "volcengine_ark:doubao-seedream-5-0-pro-260628",
)
NOW = "2026-09-20T00:00:00+00:00"


@pytest.fixture
def repository(tmp_path: Path) -> ProviderModelRepository:
    (tmp_path / "v2").mkdir(parents=True, exist_ok=True)
    database = create_v2_database(tmp_path)
    try:
        upgrade_v2_schema(database)
        yield ProviderModelRepository(database)
    finally:
        database.dispose()


# ---------------------------------------------------------------------------
# 1. Which image models the catalog advertises
# ---------------------------------------------------------------------------


def _image_manifests() -> tuple[tuple[str, str], ...]:
    return tuple(
        (manifest.provider_id, manifest.provider_model_id)
        for manifest in _TRUSTED_MANIFESTS
        if manifest.capability == "image"
    )


@pytest.mark.parametrize("model_ref", RETIRED_DOUBAO_IMAGE_REFS)
def test_every_doubao_image_model_is_retired(model_ref: str) -> None:
    assert model_ref in _RETIRED_MODEL_REFS


def test_the_two_stepfun_image_models_are_trusted_manifests() -> None:
    manifests = _image_manifests()
    assert ("stepfun", "step-image-edit-2") in manifests
    assert ("stepfun", "step-2x-large") in manifests


def test_stepfun_image_manifests_carry_no_adapter_profile() -> None:
    """An adapter profile would route them into a transport that never exists.

    ``provider_adapter_registry`` builds ``ArkMediaAdapter(profile)`` without
    injecting a transport, so ``_require_transport`` raises
    ``provider_transport_unavailable``.  The models only execute because the
    native path finds no adapter and falls through to the real-media path --
    so a manifest that added one would turn a working model into a dead one.
    """

    stepfun_image = [
        manifest
        for manifest in _TRUSTED_MANIFESTS
        if manifest.provider_id == "stepfun" and manifest.capability == "image"
    ]
    assert stepfun_image, "expected at least one stepfun image manifest"
    for manifest in stepfun_image:
        assert "adapter_profile" not in manifest.capability_metadata
        assert manifest.capability_metadata.get("provider_protocol") == "ark_image"


@pytest.mark.parametrize("model_ref", RETIRED_DOUBAO_IMAGE_REFS)
def test_every_retired_doubao_image_model_still_has_a_manifest(model_ref: str) -> None:
    """Retiring a model needs its manifest, not its deletion.

    ``_project_models`` only rewrites rows it can see in ``_TRUSTED_MANIFESTS``;
    a retired ref whose manifest was deleted would leave its existing
    ``available`` row untouched forever.
    """

    manifests = {
        f"{provider_id}:{provider_model_id}"
        for provider_id, provider_model_id in _image_manifests()
    }
    assert model_ref in manifests


def test_the_mislabelled_stepfun_image_row_is_retired_too() -> None:
    """``volcengine_ark:step-image-edit-2`` must not stay ``available``.

    It has no volcengine_ark manifest, so it can only be rewritten through the
    "previously known but not visible" branch, which requires a retired ref.
    """

    assert "volcengine_ark:step-image-edit-2" in _RETIRED_MODEL_REFS
    manifests = {
        f"{provider_id}:{provider_model_id}"
        for provider_id, provider_model_id in _image_manifests()
    }
    assert "volcengine_ark:step-image-edit-2" not in manifests


# ---------------------------------------------------------------------------
# 2. stepfun is discoverable, so its manifests can reach the database
# ---------------------------------------------------------------------------


def test_stepfun_has_a_static_discovery_adapter(repository) -> None:
    service = ProviderModelCatalogService(repository)
    adapter = service._adapters.get("stepfun")
    assert adapter is not None
    assert set(adapter.discover_model_ids()) == set(_STEPFUN_IMAGE_MODEL_IDS)


def _configure_stepfun_image(repository: ProviderModelRepository) -> None:
    repository.upsert_connection(
        provider_id="stepfun",
        connection_state="configured",
        credential_status={
            "audio": {"configured": True},
            "image": {
                "configured": True,
                "endpoint": {
                    "scheme": "https",
                    "host": "api.stepfun.com",
                    "path": "/step_plan/v1/images/generations",
                    "fingerprint": "0" * 64,
                },
                "fingerprint": "1" * 64,
                "source": "project_dotenv",
                "test_capability": "minimal_request",
            },
        },
        updated_at=NOW,
    )


def test_stepfun_image_models_project_as_available_when_configured(repository) -> None:
    _configure_stepfun_image(repository)
    service = ProviderModelCatalogService(repository)
    service.reconcile_trusted_models("stepfun", now=NOW)

    for model_id in sorted(_STEPFUN_IMAGE_MODEL_IDS):
        record = repository.get_model(f"stepfun:{model_id}")
        assert record.availability == "available", record.model_ref


def test_stepfun_image_models_are_unavailable_without_a_key(repository) -> None:
    """An unconfigured gateway must read as unconfigured, not as available."""

    service = ProviderModelCatalogService(repository)
    service.reconcile_trusted_models("stepfun", now=NOW)

    for model_id in sorted(_STEPFUN_IMAGE_MODEL_IDS):
        record = repository.get_model(f"stepfun:{model_id}")
        assert record.availability == "unavailable", record.model_ref
        assert record.unavailable_reason == "provider_credentials_missing"


def test_retired_doubao_rows_flip_to_deprecated_not_available(repository) -> None:
    """A retired manifest must overwrite a stale ``available`` row.

    ``reconcile_trusted_models`` only projects models it can see in the
    manifests; deleting the doubao entries outright would have left their
    existing ``available`` rows untouched forever.
    """

    repository.upsert_models(
        provider_id="volcengine_ark",
        models=tuple(
            {
                "model_ref": model_ref,
                "provider_model_id": model_ref.split(":", 1)[1],
                "display_name": "Doubao Seedream",
                "capability": "image",
                "capability_metadata": {"provider_protocol": "ark_image"},
                "source": "built_in",
                "availability": "available",
                "unavailable_reason": None,
            }
            for model_ref in RETIRED_DOUBAO_IMAGE_REFS
        ),
        updated_at=NOW,
    )
    service = ProviderModelCatalogService(repository)
    service.reconcile_trusted_models("volcengine_ark", now=NOW)

    for model_ref in RETIRED_DOUBAO_IMAGE_REFS:
        record = repository.get_model(model_ref)
        assert record.availability == "deprecated", record.model_ref
        assert record.unavailable_reason == "model_retired", record.model_ref


def test_list_models_hides_retired_image_models_by_default(repository) -> None:
    repository.upsert_models(
        provider_id="volcengine_ark",
        models=tuple(
            {
                "model_ref": model_ref,
                "provider_model_id": model_ref.split(":", 1)[1],
                "display_name": "Doubao Seedream",
                "capability": "image",
                "capability_metadata": {},
                "source": "built_in",
                "availability": "deprecated",
                "unavailable_reason": "model_retired",
            }
            for model_ref in RETIRED_DOUBAO_IMAGE_REFS
        ),
        updated_at=NOW,
    )
    service = ProviderModelCatalogService(repository)
    visible = {record.model_ref for record in service.list_models(capability="image")}
    for model_ref in RETIRED_DOUBAO_IMAGE_REFS:
        assert model_ref not in visible, model_ref


# ---------------------------------------------------------------------------
# 3. Defaults are migrated forward instead of left on a dead model
# ---------------------------------------------------------------------------


STEPFUN_IMAGE_ENDPOINT = "https://api.stepfun.com/step_plan/v1/images/generations"
AGNES_IMAGE_ENDPOINT = "https://api.agnes-ai.cn/v1/images/generations"


def _settings(
    tmp_path: Path,
    *,
    image_api_key: str | None = "test-key",
    video_api_key: str | None = "video-key",
    endpoint: str = STEPFUN_IMAGE_ENDPOINT,
    image_model: str = "step-image-edit-2",
) -> Settings:
    overrides: dict[str, object] = {
        "media_mode": "real",
        "agent_runtime_mode": "real",
        "siliconflow_api_key": None,
        "image_generation_api_key": image_api_key,
        "image_generation_endpoint": endpoint,
        "image_generation_model": image_model,
        "video_generation_api_key": video_api_key,
        "stepfun_api_key": None,
    }
    return dataclasses.replace(Settings.from_env(), **overrides)


def _seed_model_row(repository: ProviderModelRepository, model_ref: str) -> None:
    provider_id, _, provider_model_id = model_ref.partition(":")
    repository.upsert_models(
        provider_id=provider_id,
        models=(
            {
                "model_ref": model_ref,
                "provider_model_id": provider_model_id,
                "display_name": provider_model_id,
                "capability": "image",
                "capability_metadata": {"provider_protocol": "ark_image"},
                "source": "built_in",
                "availability": "available",
                "unavailable_reason": None,
            },
        ),
        updated_at=NOW,
    )


def test_bootstrap_migrates_a_stale_image_default(repository, tmp_path: Path) -> None:
    """The DB row is frozen, and code defaults only seed absent keys.

    ``volcengine_ark:step-image-edit-2`` is a StepFun model filed under the
    Volcengine provider id -- the shape this deployment actually shipped with.
    """
    _seed_model_row(repository, "volcengine_ark:step-image-edit-2")
    repository.set_defaults(
        {"image": "volcengine_ark:step-image-edit-2"}, updated_at=NOW
    )
    service = ProviderModelBootstrapService(_settings(tmp_path), repository)
    service.bootstrap(now=NOW)

    assert repository.get_defaults()["image"].model_ref == _STEPFUN_IMAGE_MODEL_REF


def test_bootstrap_leaves_an_already_correct_image_default_alone(
    repository, tmp_path: Path
) -> None:
    service = ProviderModelBootstrapService(_settings(tmp_path), repository)
    service.bootstrap(now=NOW)
    repository.set_defaults({"image": _STEPFUN_IMAGE_MODEL_REF}, updated_at=NOW)
    service.bootstrap(now=NOW)

    record = repository.get_defaults()["image"]
    assert record.model_ref == _STEPFUN_IMAGE_MODEL_REF


def test_bootstrap_seeds_stepfun_image_credential_status(
    repository, tmp_path: Path
) -> None:
    """The connection record must gain an ``image`` capability entry.

    ``ProviderConnectionService`` only writes providers listed in
    ``ProviderCredentialRegistry``, which has no stepfun definition -- so
    without this, both stepfun image models report
    ``provider_credentials_missing`` and can never be selected.
    """

    service = ProviderModelBootstrapService(_settings(tmp_path), repository)
    service.bootstrap(now=NOW)

    connection = repository.get_connection("stepfun")
    image_status = connection.credential_status["image"]
    assert image_status["configured"] is True
    assert image_status["endpoint"]["host"] == "api.stepfun.com"
    # Nothing secret-shaped may land in the persisted metadata.
    assert "test-key" not in str(connection.credential_status)
    assert "api_key" not in str(connection.credential_status).lower()


def test_bootstrap_is_idempotent_for_the_connection_record(
    repository, tmp_path: Path
) -> None:
    """``upsert_connection`` bumps the revision every call; guard against spin."""

    service = ProviderModelBootstrapService(_settings(tmp_path), repository)
    service.bootstrap(now=NOW)
    first = repository.get_connection("stepfun").credential_revision
    service.bootstrap(now=NOW)
    second = repository.get_connection("stepfun").credential_revision
    assert second == first


def test_bootstrap_without_image_credentials_reports_unconfigured(
    repository, tmp_path: Path
) -> None:
    settings = _settings(tmp_path, image_api_key=None)
    service = ProviderModelBootstrapService(settings, repository)
    service.bootstrap(now=NOW)

    connection = repository.get_connection("stepfun")
    assert connection.credential_status["image"]["configured"] is False
    assert connection.connection_state == "unconfigured"


def test_stale_image_defaults_cover_the_retired_refs() -> None:
    """The migration list and the retirement list must not drift apart."""

    assert set(RETIRED_DOUBAO_IMAGE_REFS).issubset(_STALE_IMAGE_MODEL_REFS)
    assert _STEPFUN_IMAGE_MODEL_REF not in _STALE_IMAGE_MODEL_REFS


# ---------------------------------------------------------------------------
# 4. One image setting pair, two possible vendors
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("endpoint", "expected"),
    [
        (STEPFUN_IMAGE_ENDPOINT, "stepfun"),
        (AGNES_IMAGE_ENDPOINT, "agnes"),
        ("https://ark.cn-beijing.volces.com/api/v3/images/generations", "volcengine_ark"),
        ("", "volcengine_ark"),
    ],
)
def test_the_connection_row_follows_the_configured_endpoint(
    endpoint: str, expected: str
) -> None:
    """The row has to be filed under the vendor the request will actually reach.

    ``ProviderConnectionService`` has no stepfun or agnes definition, so this
    derivation is the only thing deciding which provider id the image capability
    is written under.  A stale ``stepfun`` row would keep reporting
    ``configured`` after a switch to Agnes, and no row would exist for Agnes at
    all -- which is exactly how the image models ended up projecting as
    ``provider_credentials_missing`` on a deployment whose endpoint was set.
    """

    assert _image_endpoint_provider_id(endpoint) == expected


def test_bootstrap_writes_the_agnes_connection_row(repository, tmp_path: Path) -> None:
    """Agnes' credential is the video key, not the image key.

    ``api.agnes-ai.cn`` answers 401 to the StepFun image key and 200 to the
    video key, so a deployment pointed at Agnes is correctly configured with
    ``IMAGE_GENERATION_API_KEY`` empty -- and must still project ``configured``
    rather than ``provider_credentials_missing``.
    """

    settings = _settings(
        tmp_path,
        image_api_key=None,
        video_api_key="agnes-key",
        endpoint=AGNES_IMAGE_ENDPOINT,
        image_model="agnes-image-2.5-flash",
    )
    service = ProviderModelBootstrapService(settings, repository)
    service.bootstrap(now=NOW)

    connection = repository.get_connection("agnes")
    image_status = connection.credential_status["image"]
    assert image_status["configured"] is True
    assert image_status["endpoint"]["host"] == "api.agnes-ai.cn"
    assert "agnes-key" not in str(connection.credential_status)


def test_bootstrap_does_not_leave_a_stale_stepfun_image_row(
    repository, tmp_path: Path
) -> None:
    """Switching vendors must not leave the old provider reporting configured.

    The row is derived from the endpoint, so an Agnes endpoint must not write a
    ``stepfun`` image capability at all -- otherwise the catalog would keep
    advertising StepFun image models as available on a deployment that can no
    longer reach them.
    """

    settings = _settings(
        tmp_path,
        endpoint=AGNES_IMAGE_ENDPOINT,
        image_model="agnes-image-2.5-flash",
    )
    service = ProviderModelBootstrapService(settings, repository)
    service.bootstrap(now=NOW)

    try:
        stale = repository.get_connection("stepfun")
    except ValueError:
        return
    assert "image" not in stale.credential_status


def test_bootstrap_is_idempotent_for_the_agnes_connection_record(
    repository, tmp_path: Path
) -> None:
    settings = _settings(
        tmp_path,
        endpoint=AGNES_IMAGE_ENDPOINT,
        image_model="agnes-image-2.5-flash",
    )
    service = ProviderModelBootstrapService(settings, repository)
    service.bootstrap(now=NOW)
    first = repository.get_connection("agnes").credential_revision
    service.bootstrap(now=NOW)
    second = repository.get_connection("agnes").credential_revision
    assert second == first


def test_bootstrap_migrates_a_stepfun_default_to_agnes_when_the_endpoint_moves(
    repository, tmp_path: Path
) -> None:
    """The default follows the operator's endpoint, not mere reachability.

    A default left on ``stepfun:step-image-edit-2`` after the endpoint moves to
    Agnes would keep sending every image node to the vendor that was routed
    away from, with no visible error -- the node would simply fail.
    """

    _seed_model_row(repository, _STEPFUN_IMAGE_MODEL_REF)
    repository.set_defaults({"image": _STEPFUN_IMAGE_MODEL_REF}, updated_at=NOW)
    service = ProviderModelBootstrapService(
        _settings(
            tmp_path,
            endpoint=AGNES_IMAGE_ENDPOINT,
            image_model="agnes-image-2.5-flash",
        ),
        repository,
    )
    service.bootstrap(now=NOW)

    assert repository.get_defaults()["image"].model_ref == _AGNES_IMAGE_MODEL_REF


def test_bootstrap_does_not_migrate_to_agnes_when_the_endpoint_is_stepfun(
    repository, tmp_path: Path
) -> None:
    """Agnes being reachable is not consent to switch vendors.

    The migration is gated on ``IMAGE_GENERATION_ENDPOINT`` containing
    ``agnes-ai.cn``.  Without that gate, every installation with a video key
    would silently have its image nodes moved to a different vendor on the
    next boot.
    """

    _seed_model_row(repository, _STEPFUN_IMAGE_MODEL_REF)
    repository.set_defaults({"image": _STEPFUN_IMAGE_MODEL_REF}, updated_at=NOW)
    service = ProviderModelBootstrapService(_settings(tmp_path), repository)
    service.bootstrap(now=NOW)

    assert repository.get_defaults()["image"].model_ref == _STEPFUN_IMAGE_MODEL_REF


def test_bootstrap_seeds_the_ref_that_matches_the_configured_model(
    repository, tmp_path: Path
) -> None:
    """A fresh deployment's image default is the configured model's vendor."""

    service = ProviderModelBootstrapService(
        _settings(
            tmp_path,
            endpoint=AGNES_IMAGE_ENDPOINT,
            image_model="agnes-image-2.5-flash",
        ),
        repository,
    )
    service.bootstrap(now=NOW)

    assert repository.get_defaults()["image"].model_ref == _AGNES_IMAGE_MODEL_REF


def test_bootstrap_seeds_the_stepfun_ref_for_a_stepfun_endpoint(
    repository, tmp_path: Path
) -> None:
    """The mirror of the above, so switching back is not a code change."""

    service = ProviderModelBootstrapService(_settings(tmp_path), repository)
    service.bootstrap(now=NOW)

    assert repository.get_defaults()["image"].model_ref == _STEPFUN_IMAGE_MODEL_REF


def test_agnes_image_models_project_as_available_when_configured(
    repository, tmp_path: Path
) -> None:
    """End of the chain: the manifest, the connection row, and the default agree.

    If any of the three is missing the model projects as ``unavailable`` with
    ``provider_credentials_missing`` and no node can select the model that
    actually answers.
    """

    service = ProviderModelBootstrapService(
        _settings(
            tmp_path,
            endpoint=AGNES_IMAGE_ENDPOINT,
            image_model="agnes-image-2.5-flash",
        ),
        repository,
    )
    service.bootstrap(now=NOW)

    catalog = ProviderModelCatalogService(repository)
    model = catalog.get_model(_AGNES_IMAGE_MODEL_REF)
    assert model.availability == "available"


# ---------------------------------------------------------------------------
# 5. The serializer keeps the wire shape each vendor expects
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("model_id", sorted(_STEPFUN_IMAGE_MODEL_IDS))
def test_executable_models_send_the_disabled_group_generation_flag(model_id: str) -> None:
    """The StepFun gateway answers 400 without this field and 503 with it."""

    body, _audit = serialize_volcengine_image_generation_request(
        model=model_id,
        canonical_prompt="A quiet seaside boardwalk at dusk.",
        size="1024x1024",
        references=[],
        required_reference_asset_ids=[],
    )
    assert body["model"] == model_id
    assert body["sequential_image_generation"] == "disabled"


@pytest.mark.parametrize("model_id", sorted(_EXECUTABLE_IMAGE_MODEL_IDS))
def test_the_executable_set_covers_both_image_vendors(model_id: str) -> None:
    """Every executable model is one this deployment can actually reach.

    The set used to be exactly the StepFun pair.  It is now a union, because
    ``IMAGE_GENERATION_ENDPOINT`` has pointed at two different vendors and the
    serializer has to know the contract for whichever one is configured -- so a
    model appearing here must belong to one of the two contracts, not float free.
    """

    assert is_stepfun_image_model(model_id) or is_agnes_image_model(model_id)
