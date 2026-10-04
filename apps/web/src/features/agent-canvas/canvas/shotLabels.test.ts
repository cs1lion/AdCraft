import { describe, expect, it } from "vitest";

import type { SceneCamera, SceneScriptRoot } from "../../../types/scene-script";
import {
  CAMERA_LABEL_SEPARATOR,
  cameraLabel,
  cameraLabelsById,
  cameraForShot,
  formatTimecode,
  shotDurationSeconds,
  shotForFrame,
  shotLabel,
} from "./shotLabels";

function camera(id: string, displayName?: string | null): SceneCamera {
  return {
    id,
    shot_type: "medium",
    keyframes: [{ frame: 0, position: [0, 0, 0], look_at: [0, 0, 1] }],
    ...(displayName === undefined ? {} : { display_name: displayName }),
  };
}

function script(cameras: SceneCamera[], shots: SceneScriptRoot["shots"]): SceneScriptRoot {
  return {
    scene: { name: "lab", environment: "indoor", lighting: "cool", duration: 10, frame_rate: 30 },
    characters: [],
    props: [],
    environment: [],
    cameras,
    shots,
    speech_bindings: [],
  };
}

describe("cameraLabel", () => {
  it("shows the ordinal when no name is authored", () => {
    // The pre-schema state: every camera is a machine id, and a reviewer must
    // not be shown `cam_1` where a shot name belongs.
    expect(cameraLabel(camera("cam_1"), 0)).toBe("机位01");
    expect(cameraLabel(camera("cam_1"), 11)).toBe("机位12");
  });

  it("joins an authored name with the ordinal", () => {
    expect(cameraLabel(camera("cam_5", "飞船俯瞰"), 4)).toBe(
      `机位05${CAMERA_LABEL_SEPARATOR}飞船俯瞰`,
    );
  });

  it("treats a blank name as un-authored", () => {
    // An LLM that emits "" where a name belongs must not produce "机位05 | ".
    expect(cameraLabel(camera("cam_1", "   "), 0)).toBe("机位01");
    expect(cameraLabel(camera("cam_1", null), 0)).toBe("机位01");
  });

  it("pads past ten so labels sort and read consistently", () => {
    const labels = [0, 1, 8, 9, 10].map((index) => cameraLabel(camera(`c${index}`), index));
    expect(labels).toEqual(["机位01", "机位02", "机位09", "机位10", "机位11"]);
  });
});

describe("cameraLabelsById", () => {
  it("resolves a label per camera without scanning per lookup", () => {
    const labels = cameraLabelsById(
      script([camera("cam_a", "双人全景"), camera("cam_b")], []),
    );
    expect(labels).toEqual({ cam_a: "机位01 | 双人全景", cam_b: "机位02" });
  });

  it("is empty for a script with no cameras", () => {
    expect(cameraLabelsById(script([], []))).toEqual({});
  });
});

describe("shotForFrame", () => {
  const shots: SceneScriptRoot["shots"] = [
    { id: "shot_1", camera: "cam_1", start_frame: 0, end_frame: 89 },
    { id: "shot_2", camera: "cam_2", start_frame: 90, end_frame: 179 },
  ];

  it("finds the shot covering the playhead", () => {
    const value = script([camera("cam_1"), camera("cam_2")], shots);
    expect(shotForFrame(value, 0)?.id).toBe("shot_1");
    expect(shotForFrame(value, 89)?.id).toBe("shot_1");
    expect(shotForFrame(value, 90)?.id).toBe("shot_2");
    expect(shotForFrame(value, 179)?.id).toBe("shot_2");
  });

  it("falls back to the first shot inside a gap rather than blanking", () => {
    // sceneScriptConsistency flags gap-leaving shots; scrubbing through the gap
    // must still resolve a shot so the picker and the viewport stay populated.
    const gapped = script(
      [camera("cam_1"), camera("cam_2")],
      [
        { id: "shot_1", camera: "cam_1", start_frame: 0, end_frame: 50 },
        { id: "shot_2", camera: "cam_2", start_frame: 120, end_frame: 179 },
      ],
    );
    expect(shotForFrame(gapped, 80)?.id).toBe("shot_1");
  });

  it("returns null when the script has no shots", () => {
    expect(shotForFrame(script([], []), 0)).toBeNull();
  });
});

describe("cameraForShot", () => {
  it("resolves the shot's camera", () => {
    const value = script([camera("cam_1"), camera("cam_2")], [
      { id: "shot_2", camera: "cam_2", start_frame: 0, end_frame: 10 },
    ]);
    expect(cameraForShot(value, value.shots[0])?.id).toBe("cam_2");
  });

  it("returns null when the shot is null or its reference dangles", () => {
    const value = script([camera("cam_1")], [
      { id: "shot_1", camera: "ghost", start_frame: 0, end_frame: 10 },
    ]);
    expect(cameraForShot(value, null)).toBeNull();
    expect(cameraForShot(value, value.shots[0])).toBeNull();
  });
});

describe("shotLabel", () => {
  it("names the shot through its camera", () => {
    const value = script([camera("cam_1", "双人全景"), camera("cam_2", "飞船俯瞰")], [
      { id: "shot_1", camera: "cam_1", start_frame: 0, end_frame: 89 },
      { id: "shot_2", camera: "cam_2", start_frame: 90, end_frame: 179 },
    ]);
    expect(shotLabel(value, 10)).toBe("机位01 | 双人全景");
    expect(shotLabel(value, 100)).toBe("机位02 | 飞船俯瞰");
  });

  it("returns null when no shot resolves", () => {
    expect(shotLabel(script([], []), 0)).toBeNull();
  });
});

describe("formatTimecode", () => {
  it("renders m:ss and floors the seconds", () => {
    expect(formatTimecode(0)).toBe("00:00");
    expect(formatTimecode(8.9)).toBe("00:08");
    expect(formatTimecode(25)).toBe("00:25");
    expect(formatTimecode(65)).toBe("01:05");
  });

  it("clamps junk input to zero instead of printing NaN", () => {
    expect(formatTimecode(Number.NaN)).toBe("00:00");
    expect(formatTimecode(-5)).toBe("00:00");
    expect(formatTimecode(Number.POSITIVE_INFINITY)).toBe("00:00");
  });
});

describe("shotDurationSeconds", () => {
  it("uses the script's own frame rate", () => {
    const shot: SceneScriptRoot["shots"][number] = {
      id: "s",
      camera: "c",
      start_frame: 0,
      end_frame: 134,
    };
    // Frames 0..134 inclusive = 135 frames = 4.5s at 30fps, 5.625s at 24fps.
    expect(shotDurationSeconds(shot, 30)).toBeCloseTo(4.5);
    expect(shotDurationSeconds(shot, 24)).toBeCloseTo(5.625);
  });

  it("agrees with the shot strip's span for the same shot", () => {
    // One shot, two readouts — the strip's bar width and this card's timecode.
    // If they disagreed about how long a shot is, the author would be reading
    // two different numbers for the same cut.
    const shot: SceneScriptRoot["shots"][number] = {
      id: "s",
      camera: "c",
      start_frame: 150,
      end_frame: 299,
    };
    const stripSpanFrames = shot.end_frame - shot.start_frame + 1;
    expect(shotDurationSeconds(shot, 30) * 30).toBe(stripSpanFrames);
  });
});
