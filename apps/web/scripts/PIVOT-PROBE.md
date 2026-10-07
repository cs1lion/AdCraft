# Rotation pivot regression check

`PropMesh` builds a keyframed prop's geometry at the local origin and rotates it
with a wrapping group, so the point that group turns about is the group origin.
Left alone that origin is the prop's authored `position`, which for nearly every
kind is the object's **base**. A keyframed rotation then sweeps the whole object
around that base instead of turning it on itself.

The visible symptom is that the object orbits its own footprint. Measured on a
`crate` turning 360 deg: with the pivot on the base its silhouette centre wanders
**123 px** vertically and lifts off the floor; with the pivot on the crate's own
midpoint it drifts **8 px**, which is just the cube's silhouette growing as
`|cos| + |sin|`. `door` is the case that shows this cannot be a centroid rule --
it turns about a vertical edge at floor level, off to one side and below its own
middle.

## Running it

Needs a built `dist/` and the backend venv (it reads PNGs, so `Pillow`):

```bash
cd apps/web && npm run build
cd ../api && uv run python ../web/scripts/pivot-probe.py <frame-dir>
```

Produce the frames first:

```bash
cd apps/web
node scripts/render-frames.mjs \
  --script ../../test-materials/pivot_scene.json \
  --out <frame-dir> --frames 0,4,15,19,29
```

Exit 0 means the prop turns about its own extent. Exit 2 means it sweeps.

## Why it measures the way it does

Three earlier versions of this check were wrong in ways worth recording, because
each looked green:

- **Cropping the frame.** A 200 px crop reported `bot=199` on every frame and read
  the crop's own edge as the object's bottom edge. Clipping is now detected and
  reported, and the HUD is excluded by frame fraction rather than by cropping.
- **Comparing only equal-sized silhouettes.** Seemed the rigorous choice -- a cube
  at 0 deg and 180 deg is the same square, so its centre cannot move. But over a
  360 deg turn the 0 deg and 360 deg frames always match *and always sit in the
  same place*, so a visibly tumbling prop was reported PASS at 0.0 px drift
  because those were the only two frames compared. Drift is now measured across
  all frames.
- **Guessing the threshold.** `NOISE_FLOOR_PX` and `BASE_PIVOT_TRAVEL_PX` are both
  measured, from the fixed build and from a build with `crate`'s pivot forced back
  to `[0, 0, 0]`. The threshold sits an order of magnitude clear of each.

A check that cannot fail is not a check. If you change `KIND_ROTATION_PIVOT` or
`PropMesh`'s rotation group, re-run the mutant case to confirm the check still
catches the bug, not just the fix.