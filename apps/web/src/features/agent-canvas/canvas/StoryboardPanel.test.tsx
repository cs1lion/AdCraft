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

describe("StoryboardPanel previs clip publishing (ADR 0017)", () => {
  const storyboardBody = {
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
        description: "异形破土",
        transition_intent: null,
        keyframe_frames: [0, 30, 60, 90, 119],
      },
    ],
    all_keyframe_frames: [0],
    findings: [],
  };

  function stubFetchRoutes(routes: { match: (url: string) => boolean; body: Record<string, unknown>; status?: number; etag?: string }[]) {
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL) => {
        const url = String(input);
        for (const route of routes) {
          if (route.match(url)) {
            const headers: Record<string, string> = { "Content-Type": "application/json" };
            if (route.etag) headers["ETag"] = route.etag;
            return new Response(JSON.stringify(route.body), {
              status: route.status ?? 200,
              headers,
            });
          }
        }
        return new Response(JSON.stringify({ detail: "unrouted" }), { status: 500 });
      }),
    );
  }

  it("publishes a shot clip and flips the row to 已发布", async () => {
    const onPublished = vi.fn();
    const publishCalls: string[] = [];
    stubFetchRoutes([
      { match: (url) => url.endsWith("/api/v2/workflows/wf_1"), body: { workflow_id: "wf_1", revision: 1 }, etag: "W/\"7\"" },
      { match: (url) => url.includes("/scene-3d/storyboard"), body: storyboardBody },
      {
        match: (url) => {
          if (url.includes("/previs-clips")) {
            publishCalls.push(url);
            return true;
          }
          return false;
        },
        body: {
          workflow_id: "wf_1",
          revision: 2,
          node: { node_id: "node_clip" },
          binding: { binding_id: "binding_1" },
          clip_asset: { asset_id: "asset_clip" },
          keyframe_asset_ids: [],
        },
      },
    ]);

    render(
      <StoryboardPanel
        sceneScript={scene()}
        workflowId="wf_1"
        nodeId="node_scene3d"
        onPublished={onPublished}
      />,
    );

    const publish = await screen.findByTestId("scene-script-3d-storyboard-publish-0");
    publish.click();
    await screen.findByTestId("scene-script-3d-storyboard-published-0");
    expect(publishCalls).toHaveLength(1);
    expect(publishCalls[0]).toContain(
      "/api/v2/workflows/wf_1/scene-3d-nodes/node_scene3d/previs-clips",
    );
    expect(onPublished).toHaveBeenCalledTimes(1);
    expect(screen.getByTestId("scene-script-3d-published-clips")).toBeTruthy();
  });

  it("marks shots already in publishedClips as published", async () => {
    stubFetchRoutes([
      { match: (url) => url.includes("/scene-3d/storyboard"), body: storyboardBody },
    ]);

    render(
      <StoryboardPanel
        sceneScript={scene()}
        workflowId="wf_1"
        nodeId="node_scene3d"
        publishedClips={[{ node_id: "node_clip", shot_id: "s1", clip_asset_id: "asset_clip", take_id: null }]}
      />,
    );

    await screen.findByTestId("scene-script-3d-storyboard-published-0");
    expect(screen.queryByTestId("scene-script-3d-storyboard-publish-0")).toBeNull();
  });

  it("surfaces a publish failure on the shot row", async () => {
    stubFetchRoutes([
      { match: (url) => url.includes("/scene-3d/storyboard"), body: storyboardBody },
      {
        match: (url) => url.includes("/previs-clips"),
        status: 409,
        body: { detail: "scene3d_animatic_missing" },
      },
    ]);

    render(
      <StoryboardPanel
        sceneScript={scene()}
        workflowId="wf_1"
        nodeId="node_scene3d"
      />,
    );

    const publish = await screen.findByTestId("scene-script-3d-storyboard-publish-0");
    publish.click();
    await screen.findByTestId("scene-script-3d-storyboard-publish-error-0");
    expect(screen.queryByTestId("scene-script-3d-storyboard-published-0")).toBeNull();
  });

  it("hides the publish action without workflow/node context", async () => {
    stubFetchRoutes([
      { match: (url) => url.includes("/scene-3d/storyboard"), body: storyboardBody },
    ]);

    render(<StoryboardPanel sceneScript={scene()} />);

    await screen.findByTestId("scene-script-3d-storyboard-seek-0");
    expect(screen.queryByTestId("scene-script-3d-storyboard-publish-0")).toBeNull();
  });
});
