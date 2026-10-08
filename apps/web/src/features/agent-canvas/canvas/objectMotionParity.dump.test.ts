import { writeFileSync } from "node:fs";

import { describe, it } from "vitest";

import {
  DOOR_SWING_SECONDS,
  MOTION_STRIDE_METRES,
  CONTINUOUS_CYCLE_SECONDS,
  cyclePhaseForFrame,
  objectMotionAt,
} from "./objectMotion";

/**
 * Dumps the preview's object-motion output as the fixture the Python converter is
 * compared against. Only runs when asked, for the same reason the pose fixture only
 * runs when asked: a test that rewrites its own fixture every run makes it
 * unfalsifiable.
 */
const CASES: { action: string; phases: number[] }[] = [
  { action: "door_swing_open", phases: [0, 0.1, 0.25, 0.5, 0.75, 1, 1.4] },
  { action: "spin", phases: [0, 0.125, 0.3, 0.5, 0.9, 1, 1.25] },
  { action: "drive", phases: [0, 0.25, 0.5, 1, 1.5] },
  { action: "flyover", phases: [0, 0.4, 0.8, 1, 2.2] },
  { action: "stand", phases: [0, 0.5] },
];

describe("dump", () => {
  it.skipIf(!process.env.REGENERATE_SCENE_POSE_PARITY)("writes the object-motion fixture", () => {
    const payload = {
      note:
        "Sampled from the PREVIEW's objectMotion.ts so the converter's Python module " +
        "can be compared against it phase by phase. Regenerate with " +
        "REGENERATE_SCENE_POSE_PARITY=1 npx vitest run <this file>.",
      cases: CASES.map(({ action, phases }) => ({
        action,
        samples: phases.map((phase) => {
          const motion = objectMotionAt(action, phase);
          return {
            phase,
            rotation: motion.rotation ?? null,
            translation: motion.translation ?? null,
          };
        }),
      })),
      derived: {
        driveStrideMetres: MOTION_STRIDE_METRES.drive,
        flyoverStrideMetres: MOTION_STRIDE_METRES.flyover,
        doorSwingSeconds: DOOR_SWING_SECONDS,
        continuousCycleSeconds: CONTINUOUS_CYCLE_SECONDS,
        phaseAtFrame30Fps20: cyclePhaseForFrame("spin", 20, 30),
        phaseAtFrame30Fps60: cyclePhaseForFrame("door_swing_open", 60, 30),
      },
    };
    writeFileSync(
      "../api/tests/fixtures/object_motion_parity.json",
      JSON.stringify(payload, null, 2) + "\n",
      "utf8",
    );
    // eslint-disable-next-line no-console
    console.log("wrote the object-motion parity fixture");
  });
});