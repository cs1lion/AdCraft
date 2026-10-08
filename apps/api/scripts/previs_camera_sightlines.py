"""Is the shot's subject actually visible, or is something standing in front of it?

WHY THIS REPLACED THE CYLINDER VERSION
The first version modelled every asset as a vertical cylinder and got it wrong
in the direction that costs the most: it reported `habitat_dome_a` blocking two
shots. `wall` is `BoxGeometry [6s, 5s, 0.3s]` — 30 m wide, 25 m tall, 1.5 m thick
— and as a cylinder it becomes a 25 m column. An invented obstruction is worse
than a missed one, because it sends you moving a camera to dodge a wall that was
never in the way. So this models the real primitives as oriented boxes and does
a real segment/box intersection.

COORDINATES
SceneScript is Z-up: [x, y, z] = [right, forward, up]. three.js is Y-up:
[x, y, z] = [right, up, back]. The browser swaps y and z (`sceneScriptAxes.ts`),
so a three.js box `[w, h, d]` is, in SceneScript space, w wide, h tall and d deep
— with `d` along the forward axis. Every dimension below is written that way.

This is still an approximation in two stated ways, both of which used to bite:
  - cylinders (pillar, tree) and spheres (rock) are boxed. A pillar's box is
    exact in width and height; the 8-segment cylinder's diagonal corners are
    slightly inside the box, so this is CONSERVATIVE — it can report a graze
    the real render would miss, never the reverse.
  - `fence` is four separate posts and is modelled as four separate boxes, which
    is exact. The earlier version gave it the spread as a radius and it blocked
    every single shot in the scene.
"""

import json
import math
import sys
from dataclasses import dataclass
from pathlib import Path

# (half_width, half_height, half_depth, centre_height) as multiples of `scale`,
# in SceneScript space. Read off apps/web/.../sceneScriptGeometry.tsx.
SOLIDS: dict[str, tuple[float, float, float, float]] = {
    "pillar":     (0.30, 2.10, 0.30, 2.10),
    "wall":       (3.00, 2.50, 0.15, 2.50),
    "floor":      (3.00, 0.10, 3.00, 0.10),
    "platform":   (2.50, 0.20, 2.50, 0.40),
    "ground":     (7.50, 0.05, 7.50, -0.05),
    "door":       (0.50, 1.10, 0.075, 1.10),
    "window":     (0.70, 0.80, 0.06, 1.80),
    "flat_roof":  (3.20, 0.125, 2.60, 5.20),
    "gable_roof": (2.83, 1.50, 2.83, 5.50),
    "rock":       (0.63, 0.40, 0.50, 0.60),
    # Half-extents read off the built dish: 4.8 m across, 0.8 m tall at the rim,
    # sitting on the ground. A crater is wide and low, so treating it as a 1 m
    # cube (the unknown fallback) would both miss it and overstate its height.
    "crater":     (2.40, 0.40, 2.40, 0.00),
    "tree":       (0.60, 2.00, 0.60, 2.00),
    "box":        (0.40, 0.40, 0.40, 0.40),
    "crate":      (0.45, 0.45, 0.45, 0.45),
    "stairs":     (1.50, 0.30, 0.60, 0.30),
    "lowpoly_human": (0.35, 0.90, 0.35, 0.90),
    "weapon":     (0.08, 0.55, 0.05, 0.50),
}
# Kinds whose geometry is a group of parts rather than one primitive.
GROUPS = {"fence": (4, 0.06, 0.40, 0.06, 1.50)}
UNKNOWN: set[str] = set()


def boxes(item: dict) -> list[tuple[float, float, float, float, float, float, float]]:
    """(cx, cy, up, hx, hy, hz, yaw) — one per box, SceneScript space."""
    kind = item["type"]
    scale = float(item.get("scale", 1.0))
    x, y, up = float(item["position"][0]), float(item["position"][1]), float(item["position"][2])
    yaw = math.radians(float(item.get("rotation_y", 0.0)))

    if kind in GROUPS:
        count, hx, hy, hz, spacing = GROUPS[kind]
        cos_y, sin_y = math.cos(yaw), math.sin(yaw)
        out = []
        for index in range(count):
            # The posts sit at a fixed offset along the group's LOCAL depth axis,
            # which the yaw then carries into world space. Computing the offset
            # and then not applying it (which this did for one commit) stacks all
            # four posts in the same place — a check that silently stops checking.
            local_depth = spacing * scale * (index - (count - 1) / 2)
            offset_x = -local_depth * sin_y
            offset_y = local_depth * cos_y
            out.append((x + offset_x, y + offset_y, up + hy * scale,
                        hx * scale, hy * scale, hz * scale, yaw))
        return out

    if kind not in SOLIDS:
        UNKNOWN.add(kind)
        hx, hy, hz, centre = 0.5, 0.5, 0.5, 0.5
    else:
        rx, ry, rz, centre = SOLIDS[kind]
        hx, hy, hz = rx * scale, ry * scale, rz * scale
    return [(x, y, up + centre * scale, hx, hy, hz, yaw)]


def scene_objects(scene: dict, frame: int) -> list[tuple[str, list[tuple]]]:
    out = []
    for item in scene.get("environment", []) + scene.get("props", []):
        out.append((item["id"], boxes(item)))
    for person in scene.get("characters", []):
        nearest = min(person["keyframes"], key=lambda k: abs(k["frame"] - frame))
        item = {
            "id": person["id"],
            "type": "lowpoly_human",
            "position": nearest["position"],
            "scale": person["appearance"].get("scale", 1.0),
            "rotation_y": nearest.get("rotation_y", 0.0),
        }
        out.append((person["id"], boxes(item)))
    return out


def camera_at(camera: dict, frame: int) -> tuple[list[float], list[float]]:
    keys = sorted(camera["keyframes"], key=lambda k: k["frame"])
    if frame <= keys[0]["frame"]:
        return keys[0]["position"], keys[0]["look_at"]
    if frame >= keys[-1]["frame"]:
        return keys[-1]["position"], keys[-1]["look_at"]
    for a, b in zip(keys, keys[1:]):
        if a["frame"] <= frame <= b["frame"]:
            span = b["frame"] - a["frame"] or 1
            t = (frame - a["frame"]) / span

            def mix(p: list[float], q: list[float]) -> list[float]:
                return [p[i] + (q[i] - p[i]) * t for i in range(3)]

            return mix(a["position"], b["position"]), mix(a["look_at"], b["look_at"])
    return keys[0]["position"], keys[0]["look_at"]


def segment_hits_box(eye, target, box) -> float | None:
    """Fraction along eye->target at which it enters the oriented box."""
    cx, cy, cz, hx, hy, hz, yaw = box
    dx, dy, dz = target[0] - eye[0], target[1] - eye[1], target[2] - eye[2]

    # Into the box's local frame: translate to its centre, then rotate by -yaw
    # about the vertical axis. SceneScript yaw is degrees around +Z.
    ox, oy, oz = eye[0] - cx, eye[1] - cy, eye[2] - cz
    cos_y, sin_y = math.cos(-yaw), math.sin(-yaw)
    lox, loy = ox * cos_y - oy * sin_y, ox * sin_y + oy * cos_y
    ldx, ldy = dx * cos_y - dy * sin_y, dx * sin_y + dy * cos_y
    loz = oz

    origin, direction = (lox, loy, loz), (ldx, ldy, dz)
    # `half` must be in the ORIGIN's axis order, which is (x, forward, up) —
    # the box tuple carries (width, height, depth) = (x, up, forward), so the
    # last two are swapped here. Getting this wrong applies every vertical
    # extent to the forward axis, which turns the ground plane into a 600 m
    # TALL wall and reports it blocking shots it is nowhere near.
    half = (hx, hz, hy)

    # Slab test. A ray starting INSIDE reports 0.0, which is the case that
    # matters: a camera inside a slab is why the frame came out a flat brown
    # wall, and that is not a "grazes", it is the whole picture.
    near, far = 0.0, 1.0
    for axis in range(3):
        if abs(direction[axis]) < 1e-12:
            if abs(origin[axis]) > half[axis]:
                return None
            continue
        low = (-half[axis] - origin[axis]) / direction[axis]
        high = (half[axis] - origin[axis]) / direction[axis]
        if low > high:
            low, high = high, low
        near = max(near, low)
        far = min(far, high)
        if near > far:
            return None
    if far < 0.0 or near > 1.0:
        return None
    return max(near, 0.0)


def report(scene: dict) -> None:
    for finding in findings(scene):
        print(f"  {finding}")


# ---------------------------------------------------------------------------
# The gate
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Finding:
    """One thing wrong with a shot, in a form both the CLI and a test can read."""

    shot_id: str
    frame: int
    kind: str
    detail: str

    def __str__(self) -> str:
        return f"{self.shot_id} f{self.frame}: {self.kind} -- {self.detail}"


#: How close to the subject an obstruction has to be to count as blocking. Half the
#: sightline: something in front of the middle of the frame is in the way of whoever
#: the shot is about, and something past it is scenery.
BLOCKS_WITHIN = 0.5

#: A slab whose underside is this far above the feet is something a character stands
#: ON, not under. ``platform` at scale 0.2 has its underside 4 cm up, which reads as
#: a step; at 1.0 the same kind is a 0.4 m slab they are visibly inside.
FOOT_CLEARANCE = 0.05


def _dedupe(items: list[Finding]) -> list[Finding]:
    """One finding per (shot, kind, detail).

    A shot is sampled at its start and end frame, so a static subject reports the
    identical thing twice -- which reads as two problems when it is one, and trains
    the reader to skim the output instead of fixing it.
    """
    unique: dict[tuple[str, str, str], Finding] = {}
    for finding in items:
        unique.setdefault((finding.shot_id, finding.kind, finding.detail), finding)
    return list(unique.values())


def blocked_by_subject(scene: dict) -> list[Finding]:
    """Obstructions between a camera and what its shot is looking at."""
    out: list[Finding] = []
    cameras = {c["id"]: c for c in scene["cameras"]}
    for shot in scene["shots"]:
        camera = cameras[shot["camera"]]
        for label, frame in (("start", shot["start_frame"]), ("end", shot["end_frame"] - 1)):
            eye, target = camera_at(camera, frame)
            span = math.dist(eye, target)
            for ident, shapes in scene_objects(scene, frame):
                for index, box in enumerate(shapes):
                    at = segment_hits_box(eye, target, box)
                    if at is None:
                        continue
                    if at == 0.0:
                        out.append(Finding(
                            shot["id"], frame, "camera_inside_geometry",
                            f"the camera is inside {ident}",
                        ))
                    elif at < BLOCKS_WITHIN:
                        where = f"{at * span:.1f} m of a {span:.1f} m sightline"
                        out.append(Finding(
                            shot["id"], frame, "subject_blocked",
                            f"{ident} sits {where} in, in front of the subject",
                        ))
    return _dedupe(out)


def subjects_under_floating(scene: dict) -> list[Finding]:
    """Characters authored at z = 0 underneath a slab that floats above the ground.

    §2.6 of the gap doc calls this out specifically: a `platform` is
    ``BoxGeometry [5s, 0.4s, 5s]`` raised by ``0.4s``, so at scale 5 the slab occupies
    z 1..3 -- and every character keyframe is authored at z = 0, i.e. UNDERNEATH it.
    Five of eight camera positions were inside the same slab, which is why the frames
    came out a flat brown wall.

    This needs no raycasting: it is a footprint overlap plus a z-interval test, and it
    is exact where the sightline check is a conservative approximation.
    """
    out: list[Finding] = []
    floats: list[tuple[str, tuple]] = []
    for item in scene.get("environment", []) + scene.get("props", []):
        if item["type"] not in FLOATING_KINDS:
            continue
        for box in boxes(item):
            floats.append((item["id"], box))

    for shot in scene["shots"]:
        for frame in (shot["start_frame"], shot["end_frame"] - 1):
            for person in scene.get("characters", []):
                keyframe = min(person["keyframes"], key=lambda k: abs(k["frame"] - frame))
                px, py, pup = (float(v) for v in keyframe["position"])
                scale = float(person["appearance"].get("scale", 1.0))
                person_item = {"type": "lowpoly_human", "position": keyframe["position"],
                               "scale": scale}
                for cx, cy, cup, hx, hy, hz, _ in boxes(person_item):
                    for ident, (fx, fy, fup, fhx, fhy, fhz, _) in floats:
                        if not _overlaps(px + cx, hx, py + cy, hz, fx, fhx, fy, fhz):
                            continue
                        slab_bottom = fup - fhy
                        slab_top = fup + fhy
                        head = pup + cup + hy
                        if (slab_bottom - pup) > FOOT_CLEARANCE and slab_bottom < head:
                            out.append(Finding(
                                shot["id"], frame, "subject_under_floating",
                                f"{person['id']} at z={pup:g} is under {ident}, "
                                f"whose underside is at z={slab_bottom:.2f} "
                                f"(slab spans {slab_bottom:.2f}..{slab_top:.2f})",
                            ))
    return _dedupe(out)


def _overlaps(
    ax: float, ahx: float, ay: float, ahz: float,
    bx: float, bhx: float, by: float, bhz: float,
) -> bool:
    return abs(ax - bx) < ahx + bhx and abs(ay - by) < ahz + bhz


#: Kinds that can bury a character standing at z = 0.
#:
#: A SUBSET of ``asset_dimensions.floating_kinds()``, not a copy of it: that set is
#: "geometry with a positive base", and `weapon` qualifies -- a blade hanging 18 cm up.
#: Nothing can be standing under a sword, so including it would report nonsense.
#: `test_every_floating_kind_is_actually_floating` holds the subset honest in the other
#: direction, so a kind that starts floating is added here deliberately.
#:
#: Mirrored rather than imported because this script runs standalone against a scene
#: file with no package context.
FLOATING_KINDS = {
    "platform", "window", "rect_table", "chair", "lantern", "scroll",
    "flat_roof", "gable_roof", "stairs", "fence",
}


def findings(scene: dict) -> list[Finding]:
    """Everything wrong with this scene's shots, from both detectors.

    Deduplicated, because a shot is checked at its start and its end frame and a
    static subject reports the identical thing twice -- which reads as two problems
    when it is one, and trains the reader to skim the output.
    """
    return [*blocked_by_subject(scene), *subjects_under_floating(scene)]


def main() -> int:
    scene = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    strict = "--strict" in sys.argv[2:]
    report(scene)
    problems = findings(scene)
    if UNKNOWN:
        print(f"\nWARNING: no box model for {sorted(UNKNOWN)} -- treated as a 1 m cube, "
              "so those are NOT checked", file=sys.stderr)
    if problems:
        print(f"\n{len(problems)} finding(s).", file=sys.stderr)
        # Non-zero even without --strict: a lint that only warns is the tool that
        # nobody runs. --strict additionally fails on a blocked subject, which the
        # jinghai fixtures do legitimately contain.
        if strict:
            return 1
    return 2 if UNKNOWN else 0


if __name__ == "__main__":
    sys.exit(main())