/**
 * SceneImageIntake tests — the "drop an image, get a blockout" entry.
 *
 * Locks the fetch contract (multipart to /scene-3d/analyze-image), the
 * success path (script handed to the workbench), the panorama warning
 * surface, client-side validation, and the HTTP error surface.
 */

import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { SceneImageIntake } from "./SceneImageIntake.tsx";

const SCRIPT = {
  scene: { name: "underground-lab", environment: "indoor", lighting: "cool", duration: 6, frame_rate: 30 },
  characters: [],
  props: [],
  environment: [{ id: "env_1", type: "wall", position: [0, 5, 0], scale: 1, rotation_y: 0 }],
  cameras: [
    { id: "cam1", shot_type: "wide", keyframes: [{ frame: 0, position: [8, -10, 5], look_at: [0, 0, 1] }] },
  ],
  shots: [{ id: "shot1", camera: "cam1", start_frame: 0, end_frame: 179, description: "wide" }],
  speech_bindings: [],
};

function pngFile(name = "pano.png") {
  return new File(["fake-bytes"], name, { type: "image/png" });
}

beforeEach(() => {
  vi.restoreAllMocks();
});

afterEach(cleanup);

describe("SceneImageIntake", () => {
  it("renders the drop zone with the panorama hint", () => {
    render(<SceneImageIntake onSceneScriptGenerated={vi.fn()} />);
    expect(screen.getByText("🖼 从图片生成场景")).toBeTruthy();
    expect(screen.getByText(/全景图或参考照片/)).toBeTruthy();
  });

  it("POSTs the file and hands the analyzed script to the workbench", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      status: 200,
      json: async () => ({
        success: true,
        scene_script: SCRIPT,
        summary: { scene_overview: "underground research corridor" },
        image_count: 1,
        analyzed_image_count: 1,
        panorama_image_indices: [],
        warnings: [],
      }),
    });
    vi.stubGlobal("fetch", fetchMock);
    const onGenerated = vi.fn();

    render(<SceneImageIntake onSceneScriptGenerated={onGenerated} />);
    const input = document.querySelector("input[type=file]") as HTMLInputElement;
    fireEvent.change(input, { target: { files: [pngFile()] } });

    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalledTimes(1);
    });
    const [url, options] = fetchMock.mock.calls[0];
    expect(url).toBe("/api/v1/scene-3d/analyze-image");
    expect((options as RequestInit).method).toBe("POST");
    expect((options as RequestInit).body).toBeInstanceOf(FormData);

    await waitFor(() => {
      expect(onGenerated).toHaveBeenCalledTimes(1);
    });
    expect(onGenerated.mock.calls[0][0]).toEqual(SCRIPT);
    // The result banner surfaces what was analyzed.
    expect(screen.getByTestId("scene-image-intake-result").textContent).toContain(
      "underground research corridor",
    );
  });

  it("surfaces panorama slicing warnings", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        status: 200,
        json: async () => ({
          scene_script: SCRIPT,
          summary: {},
          image_count: 1,
          analyzed_image_count: 6,
          panorama_image_indices: [0],
          warnings: ["panorama_sliced_to_cubemap: image 1 (2048x1024) sliced into 6 faces"],
        }),
      }),
    );
    const onGenerated = vi.fn();
    render(<SceneImageIntake onSceneScriptGenerated={onGenerated} />);

    const input = document.querySelector("input[type=file]") as HTMLInputElement;
    fireEvent.change(input, { target: { files: [pngFile()] } });

    await waitFor(() => {
      expect(screen.getByTestId("scene-image-intake-result").textContent).toContain("全景切面");
    });
    expect(screen.getByText(/panorama_sliced_to_cubemap/)).toBeTruthy();
  });

  it("rejects unsupported extensions before any request", async () => {
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);
    render(<SceneImageIntake onSceneScriptGenerated={vi.fn()} />);

    const input = document.querySelector("input[type=file]") as HTMLInputElement;
    fireEvent.change(input, { target: { files: [new File(["x"], "notes.txt")] } });

    await waitFor(() => {
      expect(screen.getByText(/不支持的格式/)).toBeTruthy();
    });
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("surfaces the API error message", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        status: 400,
        json: async () => ({
          detail: { error: "LLM not configured: set LLM_API_KEY", error_type: "configuration" },
        }),
      }),
    );
    render(<SceneImageIntake onSceneScriptGenerated={vi.fn()} />);

    const input = document.querySelector("input[type=file]") as HTMLInputElement;
    fireEvent.change(input, { target: { files: [pngFile()] } });

    await waitFor(() => {
      expect(screen.getByText("LLM not configured: set LLM_API_KEY")).toBeTruthy();
    });
  });
});


describe("SceneImageIntake — depth white model", () => {
  it("extracts and shows the depth map when the toggle is on", async () => {
    const fetchMock = vi.fn(async (url: string) => {
      if (url === "/api/v1/scene-3d/analyze-image") {
        return {
          status: 200,
          json: async () => ({
            scene_script: SCRIPT,
            summary: {},
            image_count: 1,
            analyzed_image_count: 1,
            panorama_image_indices: [],
            warnings: [],
          }),
        };
      }
      return {
        status: 200,
        json: async () => ({
          success: true,
          depth_url: "/media/assets/provider-output/depth/depth_abc.png",
          width: 800,
          height: 400,
        }),
      };
    });
    vi.stubGlobal("fetch", fetchMock);
    const onGenerated = vi.fn();
    render(<SceneImageIntake onSceneScriptGenerated={onGenerated} />);

    fireEvent.click(screen.getByText(/同时提取深度白模/));
    const input = document.querySelector("input[type=file]") as HTMLInputElement;
    fireEvent.change(input, { target: { files: [pngFile()] } });

    await waitFor(() => {
      expect(screen.getByTestId("scene-image-intake-depth")).toBeTruthy();
    });
    expect(
      screen.getByTestId("scene-image-intake-depth").getAttribute("src"),
    ).toBe("/media/assets/provider-output/depth/depth_abc.png");
    // Two calls: analysis first, then depth.
    expect(fetchMock).toHaveBeenCalledTimes(2);
    expect(onGenerated).toHaveBeenCalledTimes(1);
  });

  it("a depth failure is a warning, not a failed analysis", async () => {
    const fetchMock = vi.fn(async (url: string) => {
      if (url === "/api/v1/scene-3d/analyze-image") {
        return {
          status: 200,
          json: async () => ({
            scene_script: SCRIPT,
            summary: {},
            image_count: 1,
            analyzed_image_count: 1,
            panorama_image_indices: [],
            warnings: [],
          }),
        };
      }
      return {
        status: 400,
        json: async () => ({
          detail: { error: "Depth estimation dependencies are not installed", error_type: "missing_dependency" },
        }),
      };
    });
    vi.stubGlobal("fetch", fetchMock);
    const onGenerated = vi.fn();
    render(<SceneImageIntake onSceneScriptGenerated={onGenerated} />);

    fireEvent.click(screen.getByText(/同时提取深度白模/));
    const input = document.querySelector("input[type=file]") as HTMLInputElement;
    fireEvent.change(input, { target: { files: [pngFile()] } });

    // The blockout still lands; the depth failure is a surfaced warning.
    await waitFor(() => {
      expect(onGenerated).toHaveBeenCalledTimes(1);
    });
    expect(screen.getByText(/深度白模提取失败/)).toBeTruthy();
    expect(screen.queryByTestId("scene-image-intake-depth")).toBeNull();
  });
});


describe("SceneImageIntake — orbit preview", () => {
  it("renders a 2.5D orbit video after analysis", async () => {
    const fetchMock = vi.fn(async (url: string) => {
      if (url === "/api/v1/scene-3d/analyze-image") {
        return {
          status: 200,
          json: async () => ({
            scene_script: SCRIPT,
            summary: {},
            image_count: 1,
            analyzed_image_count: 1,
            panorama_image_indices: [],
            warnings: [],
          }),
        };
      }
      return {
        status: 200,
        json: async () => ({
          success: true,
          video_url: "/media/assets/provider-output/orbit/orbit.mp4",
          frame_count: 48,
          keyframe_urls: [],
          max_hole_fraction: 0.3,
          warnings: ["frame 0: 30% disocclusion filled by inpainting"],
        }),
      };
    });
    vi.stubGlobal("fetch", fetchMock);
    render(<SceneImageIntake onSceneScriptGenerated={vi.fn()} />);

    // Analyze first (the orbit button appears with the result).
    const input = document.querySelector("input[type=file]") as HTMLInputElement;
    fireEvent.change(input, { target: { files: [pngFile()] } });
    await screen.findByTestId("scene-image-intake-result");

    fireEvent.click(screen.getByText("🎥 生成深度环绕预览"));

    await waitFor(() => {
      expect(screen.getByTestId("scene-image-intake-orbit")).toBeTruthy();
    });
    expect(
      screen.getByTestId("scene-image-intake-orbit").getAttribute("src"),
    ).toBe("/media/assets/provider-output/orbit/orbit.mp4");
  });

  it("surfaces an orbit failure as an error", async () => {
    const fetchMock = vi.fn(async (url: string) => {
      if (url === "/api/v1/scene-3d/analyze-image") {
        return {
          status: 200,
          json: async () => ({
            scene_script: SCRIPT,
            summary: {},
            image_count: 1,
            analyzed_image_count: 1,
            panorama_image_indices: [],
            warnings: [],
          }),
        };
      }
      return {
        status: 400,
        json: async () => ({
          detail: { error: "orbit render failed", error_type: "orbit_render_failed" },
        }),
      };
    });
    vi.stubGlobal("fetch", fetchMock);
    render(<SceneImageIntake onSceneScriptGenerated={vi.fn()} />);

    const input = document.querySelector("input[type=file]") as HTMLInputElement;
    fireEvent.change(input, { target: { files: [pngFile()] } });
    await screen.findByTestId("scene-image-intake-result");

    fireEvent.click(screen.getByText("🎥 生成深度环绕预览"));

    await waitFor(() => {
      expect(screen.getByText("orbit render failed")).toBeTruthy();
    });
    expect(screen.queryByTestId("scene-image-intake-orbit")).toBeNull();
  });
});
