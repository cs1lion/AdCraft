import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { SceneShot } from "../../../types/scene-script";
import {
  INSERT_SHOT_MIN_SECONDS,
  ShotStrip,
  shotBars,
  shotTransitionRelations,
  transitionIntentLabel,
} from "./ShotStrip.tsx";

afterEach(cleanup);

const shots: SceneShot[] = [
  { id: "s1", camera: "cam1", start_frame: 0, end_frame: 59 },
  {
    id: "s2",
    camera: "cam2",
    start_frame: 60,
    end_frame: 149,
    transition_intent: "sound_bridge",
  },
  {
    id: "s3",
    camera: "cam3",
    start_frame: 150,
    end_frame: 179,
    transition_intent: "llm_overhead_match_cut",
  },
];

describe("transitionIntentLabel (V0.2 §13 第 5 问)", () => {
  it("reads the six canonical readings in the author's language", () => {
    expect(transitionIntentLabel("continuous_motion")).toBe("连续运动");
    expect(transitionIntentLabel("gaze_closeup")).toBe("视线特写");
    expect(transitionIntentLabel("sound_bridge")).toBe("声音桥");
    expect(transitionIntentLabel("cut_after_line")).toBe("说完再切");
    expect(transitionIntentLabel("time_jump")).toBe("时间跳跃");
    expect(transitionIntentLabel("angle_switch")).toBe("视角切换");
  });

  it("shows a machine-proposed id verbatim (hiding it would make the label lie)", () => {
    expect(transitionIntentLabel("llm_overhead_match_cut")).toBe("llm_overhead_match_cut");
  });

  it("treats nothing declared as no relation (a first shot has no entry)", () => {
    expect(transitionIntentLabel(null)).toBeNull();
    expect(transitionIntentLabel(undefined)).toBeNull();
    expect(transitionIntentLabel("   ")).toBeNull();
  });
});

describe("ShotStrip", () => {
  it("marks the boundary a declared reading enters through", () => {
    render(
      <ShotStrip
        shots={shots}
        totalFrames={180}
        currentFrame={70}
        onSeekFrame={() => {}}
        onInsertAfter={() => {}}
      />,
    );
    const marker = screen.getByTestId("shot-strip-intent-s2");
    expect(marker.textContent).toBe("声音桥");
    expect(marker.getAttribute("data-intent")).toBe("sound_bridge");
    // The machine's own reading is visible too.
    expect(screen.getByTestId("shot-strip-intent-s3").textContent).toBe(
      "llm_overhead_match_cut",
    );
  });

  it("leaves a shot that declares nothing unmarked", () => {
    render(
      <ShotStrip
        shots={shots}
        totalFrames={180}
        currentFrame={10}
        onSeekFrame={() => {}}
        onInsertAfter={() => {}}
      />,
    );
    expect(screen.queryByTestId("shot-strip-intent-s1")).toBeNull();
  });

  it("names the entry reading in the bar's tooltip (the relation is queryable)", () => {
    render(
      <ShotStrip
        shots={shots}
        totalFrames={180}
        currentFrame={70}
        onSeekFrame={() => {}}
        onInsertAfter={() => {}}
      />,
    );
    // The tooltip lives on the button (the marker inside repeats it so the
    // wedge is self-describing when it is too narrow to show the text).
    const bar = screen.getByTitle(/^s2：帧 60–149/);
    expect(bar.getAttribute("title")).toContain("入镜读法：声音桥");
  });

  it("keeps seek and insert working with markers present", () => {
    const onSeekFrame = vi.fn();
    const onInsertAfter = vi.fn();
    render(
      <ShotStrip
        shots={shots}
        totalFrames={180}
        currentFrame={70}
        onSeekFrame={onSeekFrame}
        onInsertAfter={onInsertAfter}
      />,
    );
    // The marker must not swallow the click that seeks to the shot.
    fireEvent.click(screen.getByTitle(/^s2：帧 60–149/));
    expect(onSeekFrame).toHaveBeenCalledWith(60);
    fireEvent.click(screen.getByTestId("shot-strip-insert-s2"));
    expect(onInsertAfter).toHaveBeenCalledWith("s2");
  });

  it("states the insert minimum it will honour", () => {
    render(
      <ShotStrip
        shots={shots}
        totalFrames={180}
        currentFrame={10}
        onSeekFrame={() => {}}
        onInsertAfter={() => {}}
      />,
    );
    const insert = screen.getByTestId("shot-strip-insert-s2");
    expect(insert.getAttribute("title")).toContain(`至少 ${INSERT_SHOT_MIN_SECONDS}s`);
  });

  it("orders the bars by time even when the script does not", () => {
    const reordered = shotBars([...shots].reverse());
    expect(reordered.map((entry) => entry.shot.id)).toEqual(["s1", "s2", "s3"]);
    expect(reordered.map((entry) => entry.startFrame)).toEqual([0, 60, 150]);
  });
});


describe("ShotStrip — revoking a declared reading (V0.2 §12)", () => {
  const shotsWithIntent: SceneShot[] = [
    { id: "s1", camera: "cam1", start_frame: 0, end_frame: 59 },
    { id: "s2", camera: "cam2", start_frame: 60, end_frame: 149, transition_intent: "sound_bridge" },
  ];

  it("offers a revoke control only where a reading was declared", () => {
    const onClearIntent = vi.fn();
    render(
      <ShotStrip
        shots={shotsWithIntent}
        totalFrames={150}
        currentFrame={70}
        onSeekFrame={() => {}}
        onInsertAfter={() => {}}
        onClearIntent={onClearIntent}
      />,
    );
    expect(screen.getByTestId("shot-strip-clear-intent-s2")).toBeTruthy();
    expect(screen.queryByTestId("shot-strip-clear-intent-s1")).toBeNull();
  });

  it("names the reading being revoked (not a bare ×)", () => {
    render(
      <ShotStrip
        shots={shotsWithIntent}
        totalFrames={150}
        currentFrame={70}
        onSeekFrame={() => {}}
        onInsertAfter={() => {}}
        onClearIntent={vi.fn()}
      />,
    );
    const control = screen.getByTestId("shot-strip-clear-intent-s2");
    expect(control.textContent).toContain("声音桥");
    expect(control.getAttribute("title")).toContain("镜头本身不变");
  });

  it("hands the shot id back so the declaration can be removed", () => {
    const onClearIntent = vi.fn();
    render(
      <ShotStrip
        shots={shotsWithIntent}
        totalFrames={150}
        currentFrame={70}
        onSeekFrame={() => {}}
        onInsertAfter={() => {}}
        onClearIntent={onClearIntent}
      />,
    );
    fireEvent.click(screen.getByTestId("shot-strip-clear-intent-s2"));
    expect(onClearIntent).toHaveBeenCalledWith("s2");
  });

  it("offers no revoke control when no callback is wired", () => {
    render(
      <ShotStrip
        shots={shotsWithIntent}
        totalFrames={150}
        currentFrame={70}
        onSeekFrame={() => {}}
        onInsertAfter={() => {}}
      />,
    );
    // The marker stays visible (the relation is still stated); only the
    // editorial control is absent.
    expect(screen.queryByTestId("shot-strip-clear-intent-s2")).toBeNull();
    expect(screen.getByTestId("shot-strip-intent-s2")).toBeTruthy();
  });
});


describe("shotTransitionRelations (V0.2 §13 第 5 问: 哪一镜以何种读法接入)", () => {
  it("names the relation as a pair, from the predecessor into each shot", () => {
    const relations = shotTransitionRelations(shots);
    expect(relations).toEqual([
      { fromShotId: "s1", toShotId: "s2", readingId: "sound_bridge", label: "声音桥" },
      { fromShotId: "s2", toShotId: "s3", readingId: "llm_overhead_match_cut", label: "llm_overhead_match_cut" },
    ]);
  });

  it("drops the first shot (it has no predecessor to enter from)", () => {
    expect(shotTransitionRelations(shots.slice(0, 1))).toEqual([]);
    expect(shotTransitionRelations([])).toEqual([]);
  });

  it("reports an unclaimed boundary rather than skipping it", () => {
    const withBare = [
      ...shots.slice(0, 1),
      { ...shots[1], transition_intent: undefined },
      shots[2],
    ];
    const relations = shotTransitionRelations(withBare);
    expect(relations[0].readingId).toBeNull();
    expect(relations[0].label).toBeNull();
  });

  it("orders by time even when the script's array does not", () => {
    const relations = shotTransitionRelations([...shots].reverse());
    expect(relations.map((relation) => relation.toShotId)).toEqual(["s2", "s3"]);
  });
});

describe("ShotStrip — the boundary row names the relation", () => {
  it("labels each boundary with its reading", () => {
    render(
      <ShotStrip
        shots={shots}
        totalFrames={180}
        currentFrame={70}
        onSeekFrame={() => {}}
        onInsertAfter={() => {}}
      />,
    );
    const s1s2 = screen.getByTestId("shot-strip-relation-s1-s2");
    expect(s1s2.textContent).toContain("s1 → s2");
    expect(s1s2.textContent).toContain("声音桥");
    expect(s1s2.getAttribute("data-reading")).toBe("sound_bridge");
  });

  it("marks an unclaimed boundary as 未登记 (a fact, not a missing label)", () => {
    const bare = [shots[0], { ...shots[1], transition_intent: undefined }];
    render(
      <ShotStrip
        shots={bare}
        totalFrames={150}
        currentFrame={70}
        onSeekFrame={() => {}}
        onInsertAfter={() => {}}
      />,
    );
    const boundary = screen.getByTestId("shot-strip-relation-s1-s2");
    expect(boundary.textContent).toContain("未登记");
    expect(boundary.className).toContain("is-unclaimed");
    expect(boundary.getAttribute("data-reading")).toBe("");
  });

  it("gives the first shot no boundary label (nothing to enter from)", () => {
    render(
      <ShotStrip
        shots={shots}
        totalFrames={180}
        currentFrame={10}
        onSeekFrame={() => {}}
        onInsertAfter={() => {}}
      />,
    );
    // s3 has no successor, so no boundary STARTS at s3.
    expect(screen.queryByTestId("shot-strip-relation-s3-s4")).toBeNull();
    expect(screen.getByTestId("shot-strip-relation-s1-s2")).toBeTruthy();
  });
});
