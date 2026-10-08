import { writeFileSync } from "node:fs";

import { describe, it } from "vitest";

import {
  segmentPoseAt,
  walkLegAmplitude,
  walkStrideMetres,
} from "./characterPose";

/**
 * Dumps the preview's pose output as the fixture the Python converter is compared
 * against. Temporary: run once whenever the curve changes, then delete.
 */
const CASES: { action: string; legLengthMetres: number; phases: number[] }[] = [
  { action: "walk", legLengthMetres: 0.925, phases: [0, 0.1, 0.25, 0.4, 0.5, 0.7, 0.85, 0.95] },
  { action: "stand", legLengthMetres: 0.925, phases: [0, 0.37] },
  { action: "talk", legLengthMetres: 0.925, phases: [0, 0.62] },
  { action: "gesture", legLengthMetres: 0.925, phases: [0, 0.8] },
  { action: "sit", legLengthMetres: 0.925, phases: [0, 0.5] },
  { action: "walk", legLengthMetres: 0.55, phases: [0, 0.3, 0.6] },
];

describe("dump", () => {
  // Writes a checked-in file, so it only runs when asked:
  //   REGENERATE_SCENE_POSE_PARITY=1 npx vitest run <this file>
  // A test that rewrites its own fixture on every run would make the fixture
  // unfalsifiable -- the numbers would follow the code instead of gating it.
  it.skipIf(!process.env.REGENERATE_SCENE_POSE_PARITY)("writes the parity fixture", () => {
    const cases = CASES.map(({ action, legLengthMetres, phases }) => ({
      action,
      legLengthMetres,
      samples: phases.map((phase) => {
        const pose = segmentPoseAt(action, phase, { legLengthMetres });
        return {
          phase,
          legL: pose.legL ?? 0,
          legR: pose.legR ?? 0,
          armL: pose.armL ?? 0,
          armR: pose.armR ?? 0,
          bob: pose.bob ?? 0,
          torso: pose.torso ?? 0,
          head: pose.head ?? 0,
        };
      }),
    }));
    const payload = {
      note:
        "Sampled from the PREVIEW's characterPose.ts so the converter's Python curve " +
        "can be compared against it phase by phase. Regenerate with " +
        "`npx vitest run src/features/agent-canvas/canvas/poseParityFixture.dump.test.ts`.",
      cases,
      derived: {
        strideForReferenceLeg: walkStrideMetres(0.925),
        strideForShortLeg: walkStrideMetres(0.55),
        amplitudeForReferenceLeg: walkLegAmplitude(0.925),
        amplitudeForShortLeg: walkLegAmplitude(0.55),
      },
    };
    writeFileSync(
      // Relative to apps/web, which is the working directory vitest runs in.
      "../api/tests/fixtures/scene_pose_parity.json",
      JSON.stringify(payload, null, 2) + "\n",
      "utf8",
    );
    // eslint-disable-next-line no-console
    console.log("wrote the parity fixture");
  });
});