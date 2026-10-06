/**
 * Safe mutation check.
 *
 * Two fixes over the previous throwaway script:
 *
 * 1. UNIQUENESS. The anchor must appear exactly once. The earlier script used
 *    a blind `replace`, and the file had two `left: 0` lines — so its own
 *    "restore" step silently edited the wrong one and introduced a bug. A
 *    mutation harness that can corrupt the tree is worse than no harness.
 * 2. CWD. `npm` was not on PATH for a Python-spawned subprocess, so the run
 *    failed before the tests executed and the result was meaningless. This
 *    invokes vitest through node by absolute path instead.
 *
 * Run: node scripts/mutation-check.mjs   (from apps/web)
 */

import { execFileSync } from "node:child_process";
import { readFileSync, writeFileSync } from "node:fs";
import { join } from "node:path";

const ROOT = process.cwd();
const VITEST = join(ROOT, "node_modules", "vitest", "vitest.mjs");

const TESTS = [
  "src/features/agent-canvas/timeline/GlobalTimelinePanel.test.tsx",
  "src/features/agent-canvas/canvas/PrevisFilmStage.test.tsx",
  "src/features/agent-canvas/canvas/SceneEditReportPanel.test.tsx",
  "src/features/agent-canvas/canvas/Scene3DPillRow.test.tsx",
  "src/features/agent-canvas/canvas/shotLabels.test.ts",
];

/** Break one guarantee. Each entry names the file, the exact text to break,
 *  and what to break it into. */
const MUTANTS = [
  {
    name: "timeline: clips ignore their start_time (pack in array order)",
    file: "src/features/agent-canvas/timeline/GlobalTimelinePanel.tsx",
    from: `                            left: clip.start_time * PIXELS_PER_SECOND,
                            top: 6,`,
    to: `                            left: 0,
                            top: 6,`,
  },
  {
    name: "film stage: never advances",
    file: "src/features/agent-canvas/canvas/PrevisFilmStage.tsx",
    from: `      const next = value + 1;
      if (next >= reel.length) {
        setPlaying(false);
        return value;
      }
      return next;`,
    to: `      setPlaying(false);
      return value;`,
  },
  {
    name: "edit report: unknown code blanked out",
    file: "src/features/agent-canvas/canvas/SceneEditReportPanel.tsx",
    from: `{shot.changes.map((code) => report.labels[code] ?? code).join(" · ")}`,
    to: `{shot.changes.map((code) => report.labels[code] ?? "").join(" · ")}`,
  },
  {
    name: "shotLabels: duration off by one frame",
    file: "src/features/agent-canvas/canvas/shotLabels.ts",
    from: `return (shot.end_frame - shot.start_frame + 1) / frameRate;`,
    to: `return (shot.end_frame - shot.start_frame) / frameRate;`,
  },
  {
    name: "film stage: ignores the timeline's position for a shot that has one",
    file: "src/features/agent-canvas/canvas/PrevisFilmStage.tsx",
    from: `        const startSeconds = timelineClip
          ? timelineClip.start_time
          :`,
    to: `        const startSeconds = timelineClip
          ? shot.start_frame / frameRate
          :`,
  },
];

let killed = 0;
let survived = 0;
let stale = 0;

for (const mutant of MUTANTS) {
  const path = join(ROOT, mutant.file);
  const original = readFileSync(path, "utf8");

  // (1) Uniqueness: refuse to run a mutation we cannot undo exactly.
  const occurrences = original.split(mutant.from).length - 1;
  if (occurrences !== 1) {
    console.log(`?? ANCHOR x${occurrences} | ${mutant.name} — skipped, not a pass`);
    stale += 1;
    continue;
  }

  writeFileSync(path, original.replace(mutant.from, mutant.to), "utf8");
  let survivedThis = true;
  let summary = "";
  try {
    execFileSync(process.execPath, [VITEST, "run", ...TESTS, "--maxWorkers=2", "--reporter=dot"], {
      cwd: ROOT,
      encoding: "utf8",
      stdio: ["ignore", "pipe", "pipe"],
    });
    summary = "all green";
  } catch (error) {
    survivedThis = false;
    const out = `${error.stdout ?? ""}\n${error.stderr ?? ""}`;
    summary = (out.split("\n").filter((l) => /\d+ (failed|passed)/.test(l)).pop() ?? "").trim();
  } finally {
    // Restore from the bytes we read, so the file is byte-identical afterwards.
    writeFileSync(path, original, "utf8");
  }

  if (survivedThis) survived += 1;
  else killed += 1;
  console.log(`${survivedThis ? "SURVIVED" : "killed  "} | ${mutant.name} | ${summary}`);
}

console.log(`\n${killed} killed, ${survived} survived, ${stale} skipped`);
if (survived > 0) process.exitCode = 1;
