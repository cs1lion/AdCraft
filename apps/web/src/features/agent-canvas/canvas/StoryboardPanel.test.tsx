import { cleanup, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { StoryboardPanel } from "./StoryboardPanel.tsx";
import type { SceneScriptRoot } from "../../../types/scene-script";

function scene(): SceneScriptRoot {
  return {
    scene: { name: "lab", environment: "indoor", duration: 4, frame_rate: 30 },
    characters: [],
    props: [],
    environment: [],
    cameras: [
      {
        id: "cam1",
        shot_type: "wide",
        keyframes: [{ frame: 0, position: [5, -6, 2.6], look_at: [0, 0, 1.2] }],
      },
    ],
    shots: [
      { id: "s1", camera: "cam1", start_frame: 0, end_frame: 80 },
      { id: "s2", camera: "cam1", start_frame: 90, end_frame: 120 },
    ],
    speech_bindings: [],
  } as unknown as SceneScriptRoot;
}

function stubStoryboard(body: Record<string, unknown>) {
  vi.stubGlobal(
    "fetch",
    vi.fn(async () =>
      new Response(JSON.stringify(body), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      }),
    ),
  );
}

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

describe("StoryboardPanel findings (E3)", () => {
  it("renders advisory findings next to the shot list", async () => {
    stubStoryboard({
      success: true,
      scene_name: "lab",
      total_shots: 2,
      total_frames: 120,
      shots: [
        {
          shot_id: "s1",
          camera_id: "cam1",
          shot_type: "wide",
          start_frame: 0,
          end_frame: 80,
          duration_frames: 80,
          description: "",
          transition_intent: null,
          keyframe_frames: [0, 20, 40, 60, 79],
        },
      ],
      all_keyframe_frames: [0],
      findings: [
        {
          code: "storyboard_shots_leave_gap",
          subject: "s1→s2",
          message: "帧 80..89 没有被任何镜头覆盖，这些帧在分镜里是空的",
        },
        {
          code: "storyboard_shot_keyframes_short",
          subject: "tiny",
          message: "镜头太短，代表关键帧不足 5 张",
        },
      ],
    });

    render(<StoryboardPanel sceneScript={scene()} />);

    // findings 逐条可见（subject + message），且不阻断分镜列表本身
    await waitFor(() =>
      expect(screen.getByTestId("scene-script-3d-storyboard-findings")).toBeTruthy(),
    );
    expect(screen.getByText(/帧 80\.\.89 没有被任何镜头覆盖/)).toBeTruthy();
    expect(screen.getByText(/tiny/)).toBeTruthy();
    expect(screen.getByText(/镜头太短，代表关键帧不足 5 张/)).toBeTruthy();
    expect(screen.getByLabelText("分镜列表")).toBeTruthy();
  });

  it("shows no findings block when the strip is clean", async () => {
    stubStoryboard({
      success: true,
      scene_name: "lab",
      total_shots: 1,
      total_frames: 120,
      shots: [
        {
          shot_id: "s1",
          camera_id: "cam1",
          shot_type: "wide",
          start_frame: 0,
          end_frame: 120,
          duration_frames: 120,
          description: "",
          transition_intent: null,
          keyframe_frames: [0, 30, 60, 90, 119],
        },
      ],
      all_keyframe_frames: [0],
      findings: [],
    });

    render(<StoryboardPanel sceneScript={scene()} />);

    await waitFor(() => expect(screen.getByLabelText("分镜列表")).toBeTruthy());
    expect(screen.queryByTestId("scene-script-3d-storyboard-findings")).toBeNull();
  });
});
