"""The generator prompt is the only place the model learns what `scale` means.

So it is asserted, not trusted. Two things were wrong and both were invisible:

- The prompt spelled out SEVEN of thirteen prop kinds and FIVE of thirteen
  environment kinds by hand. More than half the vocabulary did not exist as far
  as the model was concerned, and only a prompt edit could ever change that.
- `scale` was not explained at all. The model wrote `scale: 4.5` for a `pillar`
  without knowing that is a 19 m column beside a 1.75 m person, and `scale: 5`
  for a `platform` without knowing that is a 25 m slab whose top sits a metre up
  — so every character, authored at z = 0, ended up underneath it.

Nothing caught either. The renderer produced an empty frame, so there was nothing
to look at and no way to tell a plausible prompt from a correct one. These
assertions exist so that "the prompt is right" is a checkable claim.

The sizes themselves are checked against the real geometry elsewhere, by
`sceneScriptGeometry.dimensions.test.ts`; what is asserted here is that the prompt
actually carries them.
"""

from __future__ import annotations

from typing import get_args

from app.schemas.scene_script import EnvironmentType, PropType
from app.services.scene3d import asset_dimensions
from app.services.scene3d.scene_script_generator import _SCENE_SCRIPT_SYSTEM_PROMPT


class TestVocabulary:
    def test_every_declared_kind_reaches_the_model(self):
        # A kind the schema accepts but the prompt never names is a kind the
        # model cannot pick, and the only symptom is a scene that quietly lacks
        # it.
        for kind in get_args(PropType):
            assert f'"{kind}"' in _SCENE_SCRIPT_SYSTEM_PROMPT, f"prop kind {kind} missing"
        for kind in get_args(EnvironmentType):
            assert f'"{kind}"' in _SCENE_SCRIPT_SYSTEM_PROMPT, f"environment kind {kind} missing"


class TestScaleIsExplained:
    def test_every_kind_states_what_scale_one_measures(self):
        # The defect this whole change exists for: a `scale` with no unit. The
        # model cannot size a scene against a bare multiplier.
        for kind in asset_dimensions.kinds():
            assert f"{kind}" in _SCENE_SCRIPT_SYSTEM_PROMPT
        assert "scale 1.0" in _SCENE_SCRIPT_SYSTEM_PROMPT

    def test_the_reference_height_is_named(self):
        # Without a reference the numbers are just numbers. `pillar` at 4.5 is
        # unremarkable until you know a person is 1.75 m and that is 19 m.
        assert str(asset_dimensions.REFERENCE_PERSON_HEIGHT) in _SCENE_SCRIPT_SYSTEM_PROMPT

    def test_the_floating_geometry_trap_is_called_out(self):
        # `platform` is a deck, not a room: characters authored at z = 0 end up
        # UNDERNEATH it, which is invisible in the prompt and obvious in a
        # render. Say it in the prompt, where it can still do something.
        assert "platform" in _SCENE_SCRIPT_SYSTEM_PROMPT
        lowered = _SCENE_SCRIPT_SYSTEM_PROMPT.lower()
        assert "deck" in lowered
        assert "underneath" in lowered or "under it" in lowered


class TestAxes:
    def test_z_is_up_is_stated(self):
        # The old prompt said characters stand at "y = 0", which is wrong: the
        # renderer is Z-up and the converter maps SceneScript [x, y, z] to
        # [right, forward, up]. Told y = 0, a model puts characters at the wrong
        # height and the camera looks at the wrong place.
        assert "Z is UP" in _SCENE_SCRIPT_SYSTEM_PROMPT
        assert "[x, y, z] is [right, forward, up]" in _SCENE_SCRIPT_SYSTEM_PROMPT

    def test_camera_height_is_given_in_the_right_axis(self):
        assert "z = 1.6" in _SCENE_SCRIPT_SYSTEM_PROMPT