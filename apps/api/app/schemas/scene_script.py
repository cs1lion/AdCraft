"""SceneScript: structured 3D previsualization scene description.

SceneScript is the canonical intermediate format between the LLM parser,
the frontend Three.js preview, and the backend Blender renderer. It is
defined as Pydantic models so that all consumers share a single validated
source of truth.

See: docs/adr/0005-3d-low-fidelity-previs.md
     docs/3d-previs/prompt-engineering-guide.md
"""

from __future__ import annotations

import math
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

ShotType = Literal["wide", "medium", "closeup", "over_shoulder", "pov"]
CharacterAction = Literal["stand", "talk", "walk", "sit", "gesture"]
SpeechMode = Literal["bound", "free"]
EnvironmentKind = Literal["indoor", "outdoor", "mixed"]
LightingPreset = Literal["warm", "cool", "neutral", "dramatic", "soft", "hard"]
CharacterType = Literal["lowpoly_human"]

PropType = Literal[
    "round_table",
    "rect_table",
    "chair",
    "stool",
    "lantern",
    "box",
    "crate",
    "vase",
    "weapon",
    "scroll",
    "book",
    "cup",
]

EnvironmentType = Literal[
    "wall",
    "pillar",
    "floor",
    "gable_roof",
    "flat_roof",
    "door",
    "window",
    "stairs",
    "platform",
    "tree",
    "rock",
    "fence",
    "ground",
]

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_COORD_MIN = -100.0
_COORD_MAX = 100.0
_ROTATION_MAX = 360.0
_RADIAN_THRESHOLD = 2.0 * math.pi  # ~6.28; values below this are likely radians

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _validate_position(value: list[float], field_name: str) -> list[float]:
    if len(value) != 3:
        raise ValueError(f"{field_name} must have exactly 3 elements [x, y, z], got {len(value)}")
    for i, v in enumerate(value):
        if not (_COORD_MIN <= v <= _COORD_MAX):
            raise ValueError(
                f"{field_name}[{i}]={v} is outside realistic range [{_COORD_MIN}, {_COORD_MAX}]; "
                "1 unit = 1 meter"
            )
    return value


def _validate_rotation_y(value: float, field_name: str) -> float:
    if abs(value) > _ROTATION_MAX:
        raise ValueError(f"{field_name}={value} exceeds ±{_ROTATION_MAX} degrees")
    if 0 < abs(value) <= _RADIAN_THRESHOLD:
        raise ValueError(
            f"{field_name}={value} appears to be in radians; use degrees (e.g. 180, not 3.14)"
        )
    return value


# ---------------------------------------------------------------------------
# Sub-models
# ---------------------------------------------------------------------------


class CharacterAppearance(BaseModel):
    """Visual appearance of a low-poly character."""

    model_config = ConfigDict(extra="forbid")

    color: str = Field(default="#8B4513", description="Hex color for the character body")
    height: float = Field(default=1.7, ge=0.5, le=3.0, description="Height in meters")
    scale: float = Field(default=1.0, gt=0, le=5.0, description="Uniform scale multiplier")

    @field_validator("color", mode="before")
    @classmethod
    def _coerce_color(cls, value: object) -> str:
        # LLMs frequently emit a free-text description here; keep the
        # schema strict (color is rendered, not displayed) by defaulting
        # any non-hex value back to the default body color.
        if isinstance(value, str) and value.startswith("#") and len(value) in (4, 7):
            return value
        return "#8B4513"


class CharacterKeyframe(BaseModel):
    """A single character keyframe: position, facing direction, and action."""

    model_config = ConfigDict(extra="forbid")

    frame: int = Field(ge=0, description="Frame number (0-based)")
    position: list[float] = Field(description="[x, y, z] position in meters")
    rotation_y: float = Field(description="Y-axis rotation in degrees (0=facing +Y)")
    action: CharacterAction = Field(default="stand", description="Character action at this keyframe")

    @field_validator("position")
    @classmethod
    def _check_position(cls, v: list[float]) -> list[float]:
        return _validate_position(v, "position")

    @field_validator("rotation_y")
    @classmethod
    def _check_rotation(cls, v: float) -> float:
        return _validate_rotation_y(v, "rotation_y")


class SceneCharacter(BaseModel):
    """A character in the scene with appearance and animation keyframes."""

    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1, max_length=64, description="Unique character identifier")
    type: CharacterType = Field(default="lowpoly_human", description="Character asset type")
    character_asset_id: str | None = Field(default=None, max_length=160, description="Reference to bound character asset (P0, 2026-09-15)")
    appearance: CharacterAppearance = Field(default_factory=CharacterAppearance)
    keyframes: list[CharacterKeyframe] = Field(
        min_length=1, description="At least one keyframe (static characters need frame 0)"
    )

    @field_validator("appearance", mode="before")
    @classmethod
    def _coerce_appearance(cls, value: object) -> object:
        # LLMs frequently emit a free-text description (or a flat "style"
        # string) where the schema expects a color/height/scale object; the
        # renderer only consumes color/height/scale, so any other shape is
        # coerced to the default appearance instead of rejecting the whole
        # scene.  The user-facing description already lives in
        # scene.name / shot.description.
        if isinstance(value, dict):
            return value
        # Accept a pre-validated CharacterAppearance instance (e.g. when the
        # scene is constructed programmatically in Python) and serialise it.
        if isinstance(value, BaseModel):
            return value.model_dump()
        if isinstance(value, str) and not value.strip():
            return {}
        return {}


class SceneProp(BaseModel):
    """A movable/interactive prop in the scene."""

    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1, max_length=64)
    type: PropType
    prop_asset_id: str | None = Field(default=None, max_length=160, description="Reference to bound prop asset (P0, 2026-09-15)")
    position: list[float] = Field(description="[x, y, z] in meters")
    scale: float = Field(default=1.0, gt=0, le=10.0)
    rotation_y: float = Field(default=0.0, description="Y-axis rotation in degrees")

    @field_validator("position")
    @classmethod
    def _check_position(cls, v: list[float]) -> list[float]:
        return _validate_position(v, "position")

    @field_validator("rotation_y")
    @classmethod
    def _check_rotation(cls, v: float) -> float:
        return _validate_rotation_y(v, "rotation_y")


class SceneEnvironmentObject(BaseModel):
    """A fixed environmental structure (walls, pillars, floors, roofs)."""

    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1, max_length=64)
    type: EnvironmentType
    scene_asset_id: str | None = Field(default=None, max_length=160, description="Reference to bound scene asset (P0, 2026-09-15)")
    position: list[float] = Field(description="[x, y, z] in meters")
    scale: float = Field(default=1.0, gt=0, le=50.0)
    rotation_y: float = Field(default=0.0, description="Y-axis rotation in degrees")

    @field_validator("position")
    @classmethod
    def _check_position(cls, v: list[float]) -> list[float]:
        return _validate_position(v, "position")

    @field_validator("rotation_y")
    @classmethod
    def _check_rotation(cls, v: float) -> float:
        return _validate_rotation_y(v, "rotation_y")


class CameraKeyframe(BaseModel):
    """A single camera keyframe: position and look-at target."""

    model_config = ConfigDict(extra="forbid")

    frame: int = Field(ge=0)
    position: list[float] = Field(description="[x, y, z] camera position in meters")
    look_at: list[float] = Field(description="[x, y, z] point the camera looks at")

    @field_validator("position", "look_at")
    @classmethod
    def _check_positions(cls, v: list[float]) -> list[float]:
        return _validate_position(v, "position/look_at")


class SceneCamera(BaseModel):
    """A camera with shot type and animation keyframes."""

    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1, max_length=64)
    shot_type: ShotType = Field(default="medium", description="Cinematographic shot type")
    keyframes: list[CameraKeyframe] = Field(
        min_length=1, description="At least one keyframe (static cameras need frame 0)"
    )


class SceneShot(BaseModel):
    """A shot: a time range bound to a camera."""

    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1, max_length=64)
    camera: str = Field(description="Reference to a camera id")
    start_frame: int = Field(ge=0)
    end_frame: int = Field(description="Must be > start_frame")
    description: str = Field(default="", max_length=500)

    @model_validator(mode="after")
    def _check_frame_range(self) -> SceneShot:
        if self.end_frame <= self.start_frame:
            raise ValueError(
                f"shot '{self.id}': end_frame ({self.end_frame}) must be > "
                f"start_frame ({self.start_frame})"
            )
        return self


class SpeechBinding(BaseModel):
    """Binds a character to a speech audio asset for timing alignment."""

    model_config = ConfigDict(extra="forbid")

    character: str = Field(description="Reference to a character id")
    speech_asset: str = Field(min_length=1, description="Reference to a speech_audio asset")
    mode: SpeechMode = Field(
        default="free",
        description="'bound': speech duration drives shot timing; 'free': independent",
    )


class SceneInfo(BaseModel):
    """Top-level scene metadata."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=200)
    environment: EnvironmentKind = Field(default="indoor")
    lighting: LightingPreset = Field(default="warm")
    duration: float = Field(gt=0, le=600, description="Total duration in seconds")
    frame_rate: int = Field(default=30, ge=1, le=120, description="Frames per second")


# ---------------------------------------------------------------------------
# Root model
# ---------------------------------------------------------------------------


class SceneScriptRoot(BaseModel):
    """Root SceneScript document: the complete 3D previs scene description."""

    model_config = ConfigDict(extra="forbid")

    scene: SceneInfo
    characters: list[SceneCharacter] = Field(default_factory=list)
    props: list[SceneProp] = Field(default_factory=list)
    environment: list[SceneEnvironmentObject] = Field(default_factory=list)
    cameras: list[SceneCamera] = Field(default_factory=list)
    shots: list[SceneShot] = Field(default_factory=list)
    speech_bindings: list[SpeechBinding] = Field(default_factory=list)

    # -- derived properties -------------------------------------------------

    @property
    def total_frames(self) -> int:
        """Total frame count = duration * frame_rate, rounded up."""
        return math.ceil(self.scene.duration * self.scene.frame_rate)

    @property
    def character_ids(self) -> set[str]:
        return {c.id for c in self.characters}

    @property
    def camera_ids(self) -> set[str]:
        return {c.id for c in self.cameras}

    # -- cross-field validators --------------------------------------------

    @model_validator(mode="after")
    def _validate_unique_ids(self) -> SceneScriptRoot:
        """All ids within each collection must be unique."""
        for collection_name, items in [
            ("characters", self.characters),
            ("props", self.props),
            ("environment", self.environment),
            ("cameras", self.cameras),
            ("shots", self.shots),
        ]:
            ids = [item.id for item in items]
            if len(ids) != len(set(ids)):
                dupes = [x for x in ids if ids.count(x) > 1]
                raise ValueError(f"duplicate {collection_name} ids: {sorted(set(dupes))}")
        return self

    @model_validator(mode="after")
    def _validate_camera_references(self) -> SceneScriptRoot:
        """Every shot's camera must reference an existing camera."""
        for shot in self.shots:
            if shot.camera not in self.camera_ids:
                raise ValueError(
                    f"shot '{shot.id}' references camera '{shot.camera}' which does not exist; "
                    f"available: {sorted(self.camera_ids)}"
                )
        return self

    @model_validator(mode="after")
    def _validate_speech_references(self) -> SceneScriptRoot:
        """Every speech_binding's character must reference an existing character."""
        for binding in self.speech_bindings:
            if binding.character not in self.character_ids:
                raise ValueError(
                    f"speech_binding references character '{binding.character}' which does not exist; "
                    f"available: {sorted(self.character_ids)}"
                )
        return self

    @model_validator(mode="after")
    def _validate_shot_ranges(self) -> SceneScriptRoot:
        """Shots must not overlap and must be within total frame count."""
        if not self.shots:
            return self

        total = self.total_frames
        sorted_shots = sorted(self.shots, key=lambda s: s.start_frame)

        for shot in sorted_shots:
            if shot.end_frame > total:
                raise ValueError(
                    f"shot '{shot.id}': end_frame ({shot.end_frame}) exceeds total frames "
                    f"({total}) = duration ({self.scene.duration}s) × frame_rate "
                    f"({self.scene.frame_rate})"
                )

        for i in range(len(sorted_shots) - 1):
            current = sorted_shots[i]
            next_shot = sorted_shots[i + 1]
            if current.end_frame > next_shot.start_frame:
                raise ValueError(
                    f"shots overlap: '{current.id}' (ends frame {current.end_frame}) and "
                    f"'{next_shot.id}' (starts frame {next_shot.start_frame})"
                )
        return self

    @model_validator(mode="after")
    def _validate_keyframe_bounds(self) -> SceneScriptRoot:
        """Character and camera keyframes must be within total frame count."""
        total = self.total_frames
        for char in self.characters:
            for kf in char.keyframes:
                if kf.frame > total:
                    raise ValueError(
                        f"character '{char.id}' keyframe at frame {kf.frame} exceeds "
                        f"total frames ({total})"
                    )
        for cam in self.cameras:
            for kf in cam.keyframes:
                if kf.frame > total:
                    raise ValueError(
                        f"camera '{cam.id}' keyframe at frame {kf.frame} exceeds "
                        f"total frames ({total})"
                    )
        return self

    @model_validator(mode="after")
    def _validate_camera_keyframes_in_shots(self) -> SceneScriptRoot:
        """Camera keyframes should fall within at least one shot that uses that camera.

        This is a soft structural check: a camera with keyframes outside all its
        shots indicates a timing mismatch. We warn by raising only when ALL keyframes
        of a camera are outside its shots.
        """
        if not self.shots:
            return self

        for cam in self.cameras:
            cam_shots = [s for s in self.shots if s.camera == cam.id]
            if not cam_shots:
                continue  # camera exists but unused; not an error
            for kf in cam.keyframes:
                in_any_shot = any(s.start_frame <= kf.frame <= s.end_frame for s in cam_shots)
                if not in_any_shot:
                    raise ValueError(
                        f"camera '{cam.id}' keyframe at frame {kf.frame} is outside all "
                        f"shots using this camera (shots: "
                        f"{[(s.id, s.start_frame, s.end_frame) for s in cam_shots]})"
                    )
        return self
