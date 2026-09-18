import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import {
  SceneScriptPlaybackProvider,
  useSceneScriptPlayback,
} from "./SceneScriptPlaybackContext.tsx";

const SCENE = {
  scene: {
    name: "Test scene",
    environment: "indoor",
    lighting: "neutral",
    duration: 5,
    frame_rate: 30,
  },
  characters: [],
  props: [],
  environment: [],
  cameras: [],
  shots: [],
  speech_bindings: [],
};

function Harness() {
  const { currentFrame, currentTime, isPlaying, toggle, seekToTime } =
    useSceneScriptPlayback();
  return (
    <div>
      <span data-testid="frame">{currentFrame}</span>
      <span data-testid="time">{currentTime.toFixed(3)}</span>
      <span data-testid="playing">{String(isPlaying)}</span>
      <button onClick={toggle}>toggle</button>
      <button onClick={() => seekToTime(2)}>seek-local</button>
    </div>
  );
}

afterEach(() => {
  cleanup();
  vi.useRealTimers();
});

describe("SceneScriptPlaybackProvider external sync", () => {
  it("seeks to an externally driven time, quantized to its fps", () => {
    const onTimeChange = vi.fn();
    render(
      <SceneScriptPlaybackProvider
        sceneScript={SCENE}
        externalPlayhead={{ time: 1, playing: false }}
        onTimeChange={onTimeChange}
      >
        <Harness />
      </SceneScriptPlaybackProvider>,
    );

    expect(screen.getByTestId("frame").textContent).toBe("30");
    expect(screen.getByTestId("time").textContent).toBe("1.000");
    // External seeks must not echo back through onTimeChange.
    expect(onTimeChange).not.toHaveBeenCalled();
  });

  it("clamps external time into the scene duration", () => {
    render(
      <SceneScriptPlaybackProvider
        sceneScript={SCENE}
        externalPlayhead={{ time: 99, playing: false }}
      >
        <Harness />
      </SceneScriptPlaybackProvider>,
    );

    // duration 5s @ 30fps -> last frame is 150 - 1.
    expect(screen.getByTestId("frame").textContent).toBe("149");
  });

  it("mirrors external play state without reporting onPlayingChange", () => {
    const onPlayingChange = vi.fn();
    render(
      <SceneScriptPlaybackProvider
        sceneScript={SCENE}
        externalPlayhead={{ time: 0, playing: true }}
        onPlayingChange={onPlayingChange}
      >
        <Harness />
      </SceneScriptPlaybackProvider>,
    );

    expect(screen.getByTestId("playing").textContent).toBe("true");
    expect(onPlayingChange).not.toHaveBeenCalled();
  });

  it("reports local toggles and seeks when no external transport drives it", () => {
    const onTimeChange = vi.fn();
    const onPlayingChange = vi.fn();
    render(
      <SceneScriptPlaybackProvider
        sceneScript={SCENE}
        onTimeChange={onTimeChange}
        onPlayingChange={onPlayingChange}
      >
        <Harness />
      </SceneScriptPlaybackProvider>,
    );

    fireEvent.click(screen.getByText("toggle"));
    expect(onPlayingChange).toHaveBeenCalledWith(true);

    fireEvent.click(screen.getByText("seek-local"));
    expect(onTimeChange).toHaveBeenCalledWith(2, 60);
  });
});
