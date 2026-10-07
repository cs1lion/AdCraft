"""Where does a keyframed prop actually rotate about?

The review question. ``PropMesh`` builds keyframed geometry at the local origin
and lets an outer group carry the pivot, so the pivot it turns about is the prop's
authored ``position`` -- and for most kinds that is the object's BASE, not its
centre. A wheel whose pivot is its contact point with the ground does not roll, it
tumbles: the whole object sweeps an arc of radius (centre - base). A blade sitting
2 m above its origin traces a 2 m circle, swings out of frame and vanishes for
half the turn.

That distinction is invisible in a thumbnail and obvious in a number, so this
measures it.

Method, and why each part is here:

* The subject is found by differing from the frame's own corner colour, so this
  works whatever the scene's palette is.
* The preview's HUD is EXCLUDED BY REGION, never by cropping. Cropping is what
  made this lie: an earlier run reported ``bot=199`` on a 200 px crop and read the
  clipped edge as the object's bottom, which turns "the object moved" into an
  artefact of the crop box. Clipping is now detected and reported instead.
* The pivot assertion compares frames whose SILHOUETTES ARE THE SAME SHAPE. A cube
  at 0 deg and 180 deg is the same square, so any difference in its bounding-box
  centre is pure translation. Comparing a cube at 0 deg against one at 72 deg does
  not work: its silhouette grows and shrinks as |cos| + |sin|, which moves the
  bounding-box centre by ~13 px all on its own.
* Rotation is asserted to have actually HAPPENED, separately from where it
  happened. A prop that silently ignored its keyframes would pass a
  stays-put pivot check perfectly, so the caller also checks that the silhouette
  changed at all.

Run against a rendered frame sequence, not against the source:

    uv run python pivot_probe.py <dir-with-frame_NNNN.png>
"""

import sys
from pathlib import Path

from PIL import Image

# The preview's HUD furniture, as fractions of frame height: the caption strip
# across the top and the transport bar at the bottom. Measured off a 404x540
# render, where they occupy rows 8-29 and 487-531 respectively. Fractions rather
# than pixels because the renderer picks its own output size, and hard-coded
# pixels silently excluded the wrong rows at every other aspect ratio.
HUD_TOP = 0.06
HUD_BOTTOM = 0.90

# Measured, not guessed. On a CORRECT pivot a crate turning 360 deg drifts 8px,
# which is its own silhouette growing as |cos|+|sin| -- that is the noise floor.
# On the same prop with its pivot moved back to the base it drifts 123px. The
# threshold sits between the two by more than an order of magnitude, so the test
# fails on the bug it was written for and passes on the fix.
NOISE_FLOOR_PX = 25.0
BASE_PIVOT_TRAVEL_PX = 60.0


def _in_hud(x, y, width, height):
    return y < HUD_TOP * height or y >= HUD_BOTTOM * height


def silhouette_box(path: Path, tolerance: int = 28):
    """Bounding box of subject pixels, ignoring the HUD. ``None`` if nothing."""
    image = Image.open(path).convert("RGB")
    width, height = image.size
    pixels = image.load()
    br, bg, bb = pixels[0, 0]
    min_x, min_y, max_x, max_y = width, height, -1, -1
    for y in range(height):
        for x in range(width):
            if _in_hud(x, y, width, height):
                continue
            r, g, b = pixels[x, y]
            if abs(r - br) + abs(g - bg) + abs(b - bb) > tolerance:
                min_x, min_y = min(min_x, x), min(min_y, y)
                max_x, max_y = max(max_x, x), max(max_y, y)
    if max_x < 0:
        return None
    clipped = min_x == 0 or min_y == 0 or max_x == width - 1 or max_y == height - 1
    return min_x, min_y, max_x, max_y, max_x - min_x, max_y - min_y, clipped


def report(directory: Path) -> int:
    frames = sorted(directory.glob("frame_*.png"))
    if len(frames) < 2:
        print(f"need >= 2 frames in {directory}, found {len(frames)}")
        return 1
    centres, shapes, sizes = [], set(), []
    any_clipped = False
    for path in frames:
        box = silhouette_box(path)
        if box is None:
            print(f"{path.name}: nothing but background")
            continue
        x0, y0, x1, y1, w, h, clipped = box
        centres.append(((x0 + x1) / 2, (y0 + y1) / 2))
        shapes.add((w, h))
        sizes.append((w, h))
        any_clipped = any_clipped or clipped
        flag = "  CLIPPED -- measurement untrustworthy" if clipped else ""
        print(f"{path.name}: top={y0:3d} bot={y1:3d} w={w:3d} h={h:3d} "
              f"centre=({(x0 + x1) / 2:.1f}, {(y0 + y1) / 2:.1f}){flag}")
    if any_clipped:
        return 1
# Drift is measured across ALL frames, not within groups of equal silhouette.
    #
    # The earlier grouping was worse than useless: it compared only frames whose
    # silhouette happened to match, and for a 360 deg turn the 0 deg and 360 deg
    # frames always match AND always sit in the same place. So a prop with its
    # pivot on the base -- visibly tumbling, centre wandering 269->393 px -- was
    # reported PASS with 0.0px drift, because the only frames it compared were the
    # two that had not moved. A regression test that cannot fail is not a test.
    #
    # All-frames drift still carries the cube's own |cos|+|sin| silhouette growth,
    # measured at ~8px over a full turn on a correct pivot. That is the noise
    # floor; BASE_PIVOT_TRAVEL_PX is the signal, three orders of magnitude above.
    xs = [c[0] for c in centres]
    ys = [c[1] for c in centres]
    drift_x, drift_y = max(xs) - min(xs), max(ys) - min(ys)
    drift = max(drift_x, drift_y)
    print(f"\ndistinct silhouette sizes: {len(shapes)} (1 means rotation never happened)")
    print(f"centre drift across all frames: x {drift_x:.1f}px, y {drift_y:.1f}px")
    ok = True
    if len(shapes) < 2:
        print("FAIL: the silhouette never changed -- the prop ignored its rotation keys")
        ok = False
    if len(centres) < 3:
        print(f"FAIL: only {len(centres)} subject frames; too few to judge drift")
        ok = False
    elif drift > BASE_PIVOT_TRAVEL_PX:
        print(f"FAIL: centre wandered {drift:.1f}px (> {BASE_PIVOT_TRAVEL_PX:.0f}px) "
              "-- the pivot is the prop's BASE, so it sweeps an arc instead of "
              "turning on itself")
        ok = False
    else:
        print(f"OK: drift {drift:.1f}px is within the silhouette-growth noise floor "
              f"({NOISE_FLOOR_PX:.0f}px), so the turn is about its own extent")
    if ok:
        print("PASS: turns on itself and the silhouette does change")
    return 0 if ok else 2


def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__)
        return 1
    return report(Path(sys.argv[1]))


if __name__ == "__main__":
    sys.exit(main())
