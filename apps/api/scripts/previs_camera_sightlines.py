"""What is standing between each camera and what it is meant to be looking at?

Computed, not eyeballed. The camera fix made renders real, and the first real
look at jinghai showed every shot dominated by foreground geometry — which
nobody had noticed precisely because nobody COULD look. Guessing at camera moves
without knowing what blocks them wastes renders, so this does the arithmetic:
each asset becomes a vertical cylinder (radius, base height, top height) taken
from the frontend geometry table, and the segment camera->look_at is tested
against every one.

Output is a per-shot report of what intrudes and how close it comes, so a camera
move is a decision rather than a guess.
"""

import json
import math
import sys
from pathlib import Path

# (radius, height, centre offset above the authored position), all multiples of
# `scale`, read off apps/web/src/features/agent-canvas/canvas/sceneScriptGeometry.tsx.
#
# Each asset becomes a VERTICAL CYLINDER, which is exact for pillars, doors,
# crates and people, and an approximation for slabs. The approximation matters:
# the first version modelled `wall` as a 25 m tall column and reported it
# blocking two shots, which was wrong — `wall` is a horizontal slab
# (BoxGeometry [6s, 5s, 0.3s], so it is 1.5 m thick and 30 m wide at scale 5).
# Modelling a slab as a column invents obstructions that are not there, which is
# worse than missing real ones: it sends you moving cameras to dodge a wall that
# was never in the way. Slabs therefore use their THIN half-extent as the height
# and their footprint as the radius, and the report says which it approximated.
SHAPES: dict[str, tuple[float, float, float]] = {
    # exact-ish columns
    "pillar":         (0.30, 4.20, 2.10),
    "tree":           (0.60, 4.00, 2.00),
    "weapon":         (0.08, 1.10, 0.50),
    "lowpoly_human":  (0.35, 1.80, 0.90),
    # thin slabs: radius = footprint, height = thickness
    "wall":           (3.00, 0.30, 2.50),
    "floor":          (3.00, 0.20, 0.10),
    "platform":       (2.50, 0.40, 0.40),
    "ground":         (7.50, 0.10, -0.05),
    "flat_roof":      (3.20, 0.25, 5.20),
    "door":           (0.50, 2.20, 1.10),
    "window":         (0.70, 1.60, 1.80),
    "box":            (0.40, 0.80, 0.40),
    "crate":          (0.45, 0.90, 0.45),
    "rock":           (1.26, 1.00, 0.60),
    "fence":          (0.10, 0.80, 0.40),   # posts only; see NOTE below
    "stairs":         (1.50, 0.60, 0.30),
}


def cylinders(scene: dict, frame: int) -> list[tuple[str, float, float, float]]:
    """(id, x, y, radius, z_bottom, z_top) in SceneScript space (Z-up)."""
    out: list[tuple[str, float, float, float, float, float]] = []

    def put(ident: str, kind: str, pos: list[float], scale: float) -> None:
        radius, height, offset = SHAPES.get(kind, (0.5, 1.0, 0.5))
        r = radius * scale
        if r <= 0:
            return
        centre_z = offset * scale
        out.append((ident, pos[0], pos[1], r, centre_z - height * scale / 2, centre_z + height * scale / 2))

    for item in scene["environment"]:
        put(item["id"], item["type"], item["position"], item.get("scale", 1.0))
    for item in scene["props"]:
        put(item["id"], item["type"], item["position"], item.get("scale", 1.0))
    for person in scene["characters"]:
        # A character at its nearest authored keyframe is a person-shaped
        # obstruction even though nobody shot at it on purpose.
        best = min(person["keyframes"], key=lambda k: abs(k["frame"] - frame))
        put(person["id"], "lowpoly_human", best["position"],
            best.get("position_scale", person["appearance"].get("scale", 1.0)))
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


def blockers(eye: list[float], target: list[float], shapes, ignore: set[str]):
    """What the segment eye->target passes through, nearest first."""
    ex, ey, ez = eye
    tx, ty, tz = target
    dx, dy, dz = tx - ex, ty - ey, tz - ez
    length = math.sqrt(dx * dx + dy * dy + dz * dz) or 1.0
    hits = []
    for ident, x, y, r, z0, z1 in shapes:
        if ident in ignore:
            continue
        # Closest approach of the segment to the cylinder's axis.
        best_t, best_d2 = 0.0, float("inf")
        for k in range(201):
            t = k / 200
            px, py, pz = ex + dx * t, ey + dy * t, ez + dz * t
            if not (z0 <= pz <= z1):
                continue
            d2 = (px - x) ** 2 + (py - y) ** 2
            if d2 < best_d2:
                best_d2, best_t = d2, t
        if best_d2 <= r * r:
            hits.append((best_t * length, ident, math.sqrt(best_d2) - r, r))
    return sorted(hits)


# Known limits of the model, so a "clear" verdict is read with the right amount
# of trust:
#   - `fence` is a LINE of four posts spread over ±2.25*scale metres, not a
#     solid. It is modelled by its posts (radius 0.1), so this test will NOT
#     report a fence crossing the view — the posts are too thin to hit. Giving it
#     the spread as a radius instead invents a 27 m disc that blocks every shot,
#     which is what the first version did. So a fence in shot is a thing to check
#     by eye, not something this report can promise you.
#   - rotation_y is ignored: every asset is treated as axis-aligned. A rotated
#     slab or fence is approximated by its unrotated footprint.
#   - the ground is modelled at its true thickness but its footprint is the
#     inscribed radius, so a camera just outside the plane's corner still reads
#     as clear.


def main() -> int:
    scene = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    cameras = {c["id"]: c for c in scene["cameras"]}

    for shot in scene["shots"]:
        camera = cameras[shot["camera"]]
        for label, frame in (("start", shot["start_frame"]), ("end", shot["end_frame"] - 1)):
            eye, target = camera_at(camera, frame)
            shapes = cylinders(scene, frame)
            hits = blockers(eye, target, shapes, ignore={shot["camera"]})
            span = math.dist(eye, target)
            print(f"\n{shot['id']} [{label}] frame {frame}")
            print(f"  eye={tuple(round(v,1) for v in eye)} -> look_at={tuple(round(v,1) for v in target)}"
                  f"  ({span:.1f}m)")
            if not hits:
                print("  clear line of sight")
            for distance, ident, clearance, radius in hits[:4]:
                where = f"{distance:5.1f}m from camera"
                quality = "BLOCKS" if distance < span * 0.6 else "grazes"
                print(f"  {quality:6} {ident:<18} {where}  clearance={clearance:+.1f}m  r={radius:.1f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())